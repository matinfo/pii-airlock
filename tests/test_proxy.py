"""Proxy gateway: scrub-out + restore-in, with a mocked upstream and fake engine.

Skipped entirely if the optional proxy deps (httpx/starlette) aren't installed.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("httpx")
pytest.importorskip("starlette")

import httpx  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from pii_scrub.mapping import Mapping  # noqa: E402
from pii_scrub.proxy import build_app  # noqa: E402


class FakeEngine:
    """Stub ScrubEngine: replaces the literal name 'Alice' with a stable token."""

    def scrub(self, text: str, mapping: Mapping, language=None) -> str:
        if "Alice" in text:
            token = mapping.token_for("PERSON", "Alice")
            return text.replace("Alice", token)
        return text


def _app(handler):
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    return build_app(engine=FakeEngine(), client=client)


def test_non_streaming_roundtrip():
    seen = {}

    def upstream(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen["sent"] = body["messages"][0]["content"]
        # echo the (scrubbed) prompt back as the assistant message
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"choices": [{"message": {"role": "assistant", "content": seen["sent"]}}]},
        )

    client = TestClient(_app(upstream))
    resp = client.post(
        "/openai/v1/chat/completions",
        json={"model": "gpt-x", "messages": [{"role": "user", "content": "call Alice"}]},
    )
    assert resp.status_code == 200
    # upstream must have seen the scrubbed token, NOT the real name
    assert "Alice" not in seen["sent"]
    assert "<PERSON_1>" in seen["sent"]
    # client must get the real name back
    assert resp.json()["choices"][0]["message"]["content"] == "call Alice"


def test_streaming_roundtrip_restores_tokens():
    def upstream(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        scrubbed = body["messages"][0]["content"]  # contains <PERSON_1>
        token = scrubbed.split("call ")[1]
        sse = (
            f'data: {json.dumps({"choices": [{"delta": {"content": "call "}}]})}\n\n'
            f'data: {json.dumps({"choices": [{"delta": {"content": token}}]})}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=sse.encode()
        )

    client = TestClient(_app(upstream))
    resp = client.post(
        "/openai/v1/chat/completions",
        json={"model": "gpt-x", "stream": True,
              "messages": [{"role": "user", "content": "call Alice"}]},
    )
    assert resp.status_code == 200
    # reassemble the streamed text the way a client would
    text = ""
    for line in resp.text.splitlines():
        if line.startswith("data:") and "[DONE]" not in line:
            chunk = json.loads(line[5:].strip())
            text += chunk["choices"][0]["delta"].get("content", "")
    assert text == "call Alice"


def test_streaming_handles_crlf_event_boundaries():
    def upstream(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        token = body["messages"][0]["content"].split("call ")[1]
        # provider that uses CRLF SSE separators
        sse = (
            f'data: {json.dumps({"choices": [{"delta": {"content": "call "}}]})}\r\n\r\n'
            f'data: {json.dumps({"choices": [{"delta": {"content": token}}]})}\r\n\r\n'
            "data: [DONE]\r\n\r\n"
        )
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=sse.encode()
        )

    client = TestClient(_app(upstream))
    resp = client.post(
        "/openai/v1/chat/completions",
        json={"model": "gpt-x", "stream": True,
              "messages": [{"role": "user", "content": "call Alice"}]},
    )
    text = ""
    for line in resp.text.splitlines():
        if line.startswith("data:") and "[DONE]" not in line:
            text += json.loads(line[5:].strip())["choices"][0]["delta"].get("content", "")
    assert text == "call Alice"


def test_non_generation_endpoint_passes_through():
    def upstream(request: httpx.Request) -> httpx.Response:
        # body must be forwarded unchanged for non-generation paths
        return httpx.Response(200, json={"data": ["model-a", "model-b"]})

    client = TestClient(_app(upstream))
    resp = client.get("/openai/v1/models")
    assert resp.status_code == 200
    assert resp.json()["data"] == ["model-a", "model-b"]


def test_unknown_provider_404():
    def upstream(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        return httpx.Response(200)

    client = TestClient(_app(upstream))
    assert client.post("/bogus/v1/x", json={}).status_code == 404


def test_healthz():
    def upstream(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        return httpx.Response(200)

    client = TestClient(_app(upstream))
    assert client.get("/healthz").status_code == 200
