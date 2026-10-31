"""Proxy gateway: scrub-out + restore-in, with a mocked upstream and fake engine.

Skipped entirely if the optional proxy deps (httpx/starlette) aren't installed.
"""

from __future__ import annotations

import json
import re
import warnings

import pytest

pytest.importorskip("httpx")
pytest.importorskip("starlette")

import httpx  # noqa: E402

from pii_scrub.mapping import Mapping  # noqa: E402
from pii_scrub.proxy import build_app  # noqa: E402


class FakeEngine:
    """Stub ScrubEngine: replaces the literal name 'Alice' with a stable token."""

    def __init__(self):
        self.collected: list[str] = []

    def scrub_all(self, run, mapping, texts=None):
        from pii_scrub.engine import collect_texts

        self.collected.extend(collect_texts(run))
        return run(lambda t: self.scrub(t, mapping))

    def scrub(self, text: str, mapping: Mapping, language=None) -> str:
        if "Alice" in text:
            token = mapping.token_for("PERSON", "Alice")
            return text.replace("Alice", token)
        return text


class CountingStore:
    def __init__(self):
        self.created = 0
        self.saved = 0
        self.loaded = 0
        self.deleted = 0
        self._mapping = None
        self._key = "k1"

    def create(self, key=None, *, surrogates=False) -> Mapping:
        self.created += 1
        return Mapping(key, surrogates=surrogates)

    def save(self, mapping: Mapping, *, key: str | None = None) -> str:
        self.saved += 1
        self._mapping = mapping
        return key or self._key

    def load(self, key: str) -> Mapping:
        self.loaded += 1
        assert self._mapping is not None
        return self._mapping

    def delete(self, key: str) -> None:
        self.deleted += 1


def _app(handler):
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    return build_app(engine=FakeEngine(), client=client)


def _client(app):
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=(
                r"Using `httpx` with `starlette\.testclient` is deprecated; "
                r"install `httpx2` instead\."
            ),
        )
        from starlette.testclient import TestClient

    return TestClient(app)


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

    client = _client(_app(upstream))
    resp = client.post(
        "/openai/v1/chat/completions",
        json={"model": "gpt-x", "messages": [{"role": "user", "content": "call Alice"}]},
    )
    assert resp.status_code == 200
    # upstream must have seen the scrubbed token, NOT the real name
    assert "Alice" not in seen["sent"]
    assert re.search(r"<PERSON_\d{6}>", seen["sent"])  # stable token
    # client must get the real name back
    assert resp.json()["choices"][0]["message"]["content"] == "call Alice"


def test_request_strings_are_scrubbed_together():
    engine = FakeEngine()

    def upstream(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    resp = _client(build_app(engine=engine, client=client)).post(
        "/openai/v1/chat/completions",
        json={"model": "gpt-x", "messages": [
            {"role": "system", "content": "be brief"},
            {"role": "user", "content": "call Alice"},
        ]},
    )
    assert resp.status_code == 200
    assert {"be brief", "call Alice"} <= set(engine.collected)


def test_streaming_roundtrip_restores_tokens():
    def upstream(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        scrubbed = body["messages"][0]["content"]  # contains <PERSON_nnnnnn>
        token = scrubbed.split("call ")[1]
        sse = (
            f'data: {json.dumps({"choices": [{"delta": {"content": "call "}}]})}\n\n'
            f'data: {json.dumps({"choices": [{"delta": {"content": token}}]})}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=sse.encode()
        )

    client = _client(_app(upstream))
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

    client = _client(_app(upstream))
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

    client = _client(_app(upstream))
    resp = client.get("/openai/v1/models")
    assert resp.status_code == 200
    assert resp.json()["data"] == ["model-a", "model-b"]


def test_unknown_provider_404():
    def upstream(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        return httpx.Response(200)

    client = _client(_app(upstream))
    assert client.post("/bogus/v1/x", json={}).status_code == 404


def test_healthz():
    def upstream(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        return httpx.Response(200)

    client = _client(_app(upstream))
    assert client.get("/healthz").status_code == 200


def test_upstream_failure_returns_502():
    def upstream(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = _client(_app(upstream))
    resp = client.post(
        "/openai/v1/chat/completions",
        json={"model": "x", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 502
    assert "upstream request failed" in resp.text


def test_missing_model_returns_503_and_does_not_leak():
    class RaisingEngine:
        def scrub_all(self, run, mapping, texts=None):
            raise RuntimeError("No spaCy models configured for languages ['en', 'fr'].")

        def scrub(self, text, mapping, language=None):
            raise RuntimeError("No spaCy models configured for languages ['en', 'fr'].")

    sent = {}

    def upstream(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        sent["hit"] = True
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(upstream)
    app = build_app(engine=RaisingEngine(), client=httpx.AsyncClient(transport=transport))
    resp = _client(app).post(
        "/openai/v1/chat/completions",
        json={"model": "x", "messages": [{"role": "user", "content": "call Alice"}]},
    )
    assert resp.status_code == 503
    assert "download-models" in resp.text
    assert "hit" not in sent  # never forwarded upstream → no PII leak on failure


def test_proxy_uses_injected_mapping_store():
    store = CountingStore()

    def upstream(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
        )

    transport = httpx.MockTransport(upstream)
    app = build_app(
        engine=FakeEngine(),
        client=httpx.AsyncClient(transport=transport),
        mapping_store=store,
    )
    resp = _client(app).post(
        "/openai/v1/chat/completions",
        json={"model": "x", "messages": [{"role": "user", "content": "call Alice"}]},
    )
    assert resp.status_code == 200
    assert store.created == 1
    assert store.saved == 1
    assert store.loaded == 1
    assert store.deleted == 1


def _app_cfg(handler, **config):
    from pii_scrub.config import Config

    transport = httpx.MockTransport(handler)
    return build_app(Config(**config), engine=FakeEngine(),
                     client=httpx.AsyncClient(transport=transport))


def test_unknown_endpoint_with_body_is_refused():
    sent = {}

    def upstream(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        sent["hit"] = True
        return httpx.Response(200, json={})

    client = _client(_app(upstream))
    resp = client.post("/openai/v1/files", content=b"call Alice")
    assert resp.status_code == 403
    assert "passthrough_paths" in resp.text
    assert "hit" not in sent


def test_passthrough_paths_opt_in_forwards_raw():
    sent = {}

    def upstream(request: httpx.Request) -> httpx.Response:
        sent["body"] = request.content
        return httpx.Response(200, json={"ok": True})

    client = _client(_app_cfg(upstream, passthrough_paths=["openai/v1/files"]))
    resp = client.post("/openai/v1/files", content=b"raw bytes")
    assert resp.status_code == 200
    assert sent["body"] == b"raw bytes"


def test_unparseable_generation_body_is_refused():
    def upstream(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("must not be forwarded")

    client = _client(_app(upstream))
    resp = client.post("/openai/v1/chat/completions", content=b"call Alice, not json")
    assert resp.status_code == 400


def test_responses_api_scrubbed_and_restored():
    seen = {}

    def upstream(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen["body"] = request.content.decode()
        token = body["input"][0]["content"][0]["text"].split("call ")[1]
        return httpx.Response(200, headers={"content-type": "application/json"}, json={
            "object": "response",
            "output": [
                {"type": "function_call", "name": "dial", "arguments": json.dumps({"who": token})},
                {"type": "message", "content": [{"type": "output_text", "text": f"ok {token}"}]},
            ],
        })

    client = _client(_app(upstream))
    resp = client.post("/openai/v1/responses", json={
        "model": "x", "instructions": "Alice is the user",
        "input": [
            {"role": "user", "content": [{"type": "input_text", "text": "call Alice"}]},
            {"type": "function_call_output", "call_id": "c", "output": "Alice's file"},
        ],
    })
    assert resp.status_code == 200
    assert "Alice" not in seen["body"]
    out = resp.json()["output"]
    assert json.loads(out[0]["arguments"]) == {"who": "Alice"}
    assert out[1]["content"][0]["text"] == "ok Alice"


def test_anthropic_tool_result_scrubbed_and_stream_restored():
    seen = {}

    def upstream(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content.decode()
        token = json.loads(request.content)["messages"][0]["content"][0]["content"]

        def ev(name, data):
            return f"event: {name}\ndata: {json.dumps({'type': name, **data})}\n\n"

        sse = (
            ev("message_start", {"message": {"content": []}})
            + ev("content_block_start", {"index": 0, "content_block": {"type": "text", "text": ""}})
            + ev("content_block_delta", {"index": 0, "delta": {"type": "text_delta",
                                                                "text": "hi " + token[:4]}})
            + ev("content_block_delta", {"index": 0, "delta": {"type": "text_delta",
                                                                "text": token[4:]}})
            + ev("content_block_stop", {"index": 0})
            + ev("message_stop", {})
        )
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=sse.encode())

    client = _client(_app(upstream))
    resp = client.post("/anthropic/v1/messages", json={
        "model": "x", "stream": True,
        "messages": [{"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t", "content": "Alice"}]}],
    })
    assert "Alice" not in seen["body"]
    text = ""
    names = []
    for block in resp.text.split("\n\n"):
        if not block.strip():
            continue
        name, _, data = block.partition("\ndata: ")
        chunk = json.loads(data)
        names.append(name.removeprefix("event: "))
        assert names[-1] == chunk["type"]
        if chunk["type"] == "content_block_delta":
            text += chunk["delta"]["text"]
    assert text == "hi Alice"
    assert names[-1] == "message_stop"


def test_tokens_are_stable_across_requests_in_any_order():
    sent = []

    def upstream(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content)["messages"])
        return httpx.Response(200, json={"choices": []})

    client = _client(_app(upstream))
    client.post("/openai/v1/chat/completions", json={"model": "m", "messages": [
        {"role": "user", "content": "call Alice"}]})
    client.post("/openai/v1/chat/completions", json={"model": "m", "messages": [
        {"role": "user", "content": "something else first"},
        {"role": "user", "content": "then Alice again"}]})
    first = sent[0][0]["content"].split()[-1]
    assert first.startswith("<PERSON_")
    assert sent[1][1]["content"] == f"then {first} again"  # same token, other position


def test_sequential_token_style_still_available():
    seen = {}

    def upstream(request: httpx.Request) -> httpx.Response:
        seen["sent"] = json.loads(request.content)["messages"][0]["content"]
        return httpx.Response(200, json={"choices": []})

    _client(_app_cfg(upstream, token_style="sequential")).post(
        "/openai/v1/chat/completions",
        json={"model": "m", "messages": [{"role": "user", "content": "call Alice"}]},
    )
    assert seen["sent"] == "call <PERSON_1>"


def test_bad_token_settings_fail_at_startup():
    from pii_scrub.config import Config

    with pytest.raises(ValueError, match="token_rotation"):
        build_app(Config(token_rotation="hourly"), engine=FakeEngine(),
                  client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: None)))


def test_blocked_entity_is_refused_without_echoing_the_value():
    from pii_scrub.engine import PolicyBlocked

    class BlockingEngine(FakeEngine):
        def scrub_all(self, run, mapping, texts=None):
            raise PolicyBlocked(__import__("collections").Counter({"IBAN_CODE": 1}))

    hits = []
    transport = httpx.MockTransport(lambda r: hits.append(r) or httpx.Response(200, json={}))
    app = build_app(engine=BlockingEngine(), client=httpx.AsyncClient(transport=transport))
    resp = _client(app).post("/openai/v1/chat/completions", json={
        "model": "m", "messages": [{"role": "user", "content": "pay FR7630006000011234567890189"}]})
    assert resp.status_code == 403 and "IBAN_CODE×1" in resp.text
    assert "FR76" not in resp.text and hits == []
