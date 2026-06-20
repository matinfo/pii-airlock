"""Payload adapters + streaming reassembly (pure, no Presidio needed)."""

from __future__ import annotations

import json

from pii_scrub.payload import (
    StreamRestorer,
    get_adapter,
    restore_payload,
    restore_sse_data,
    scrub_payload,
    split_sse_event,
)

# A trivial reversible "scrub": uppercase markers around the word "secret".
UP = str.upper


def test_openai_request_string_and_parts():
    a = get_adapter("openai")
    body = {
        "model": "gpt-x",
        "messages": [
            {"role": "system", "content": "be nice"},
            {"role": "user", "content": "hello secret"},
            {"role": "user", "content": [
                {"type": "text", "text": "part secret"},
                {"type": "image_url", "image_url": {"url": "http://x"}},
            ]},
        ],
    }
    out = scrub_payload(body, a, UP)
    assert out["messages"][0]["content"] == "BE NICE"
    assert out["messages"][1]["content"] == "HELLO SECRET"
    assert out["messages"][2]["content"][0]["text"] == "PART SECRET"
    # non-text part untouched
    assert out["messages"][2]["content"][1]["image_url"]["url"] == "http://x"
    # original not mutated
    assert body["messages"][1]["content"] == "hello secret"


def test_openai_response_and_delta():
    a = get_adapter("openai")
    full = {"choices": [{"message": {"role": "assistant", "content": "hi there"}}]}
    assert restore_payload(full, a, UP)["choices"][0]["message"]["content"] == "HI THERE"

    delta = {"choices": [{"delta": {"content": "tok"}}]}
    assert a.restore_delta(delta, UP)["choices"][0]["delta"]["content"] == "TOK"


def test_anthropic_request_system_and_messages():
    a = get_adapter("anthropic")
    body = {
        "system": "sys secret",
        "messages": [
            {"role": "user", "content": "msg secret"},
            {"role": "user", "content": [{"type": "text", "text": "block secret"}]},
        ],
    }
    out = scrub_payload(body, a, UP)
    assert out["system"] == "SYS SECRET"
    assert out["messages"][0]["content"] == "MSG SECRET"
    assert out["messages"][1]["content"][0]["text"] == "BLOCK SECRET"


def test_anthropic_response_and_delta():
    a = get_adapter("anthropic")
    full = {"content": [{"type": "text", "text": "answer"}]}
    assert restore_payload(full, a, UP)["content"][0]["text"] == "ANSWER"

    delta = {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "frag"}}
    assert a.restore_delta(delta, UP)["delta"]["text"] == "FRAG"


def test_gemini_request_and_response():
    a = get_adapter("gemini")
    body = {
        "contents": [{"role": "user", "parts": [{"text": "ask secret"}]}],
        "systemInstruction": {"parts": [{"text": "sys secret"}]},
    }
    out = scrub_payload(body, a, UP)
    assert out["contents"][0]["parts"][0]["text"] == "ASK SECRET"
    assert out["systemInstruction"]["parts"][0]["text"] == "SYS SECRET"

    resp = {"candidates": [{"content": {"parts": [{"text": "reply"}]}}]}
    assert restore_payload(resp, a, UP)["candidates"][0]["content"]["parts"][0]["text"] == "REPLY"


def test_unknown_provider_raises():
    import pytest

    with pytest.raises(ValueError):
        get_adapter("nope")


# --- streaming reassembly ------------------------------------------------


def _swap(text: str) -> str:
    """Restore-like transform: <PERSON_1> -> Alice."""
    return text.replace("<PERSON_1>", "Alice")


def test_stream_restorer_token_split_across_chunks():
    r = StreamRestorer(_swap)
    # "<PERSON_1>" arrives in three fragments
    out = r.feed("Hello <PER")
    out += r.feed("SON")
    out += r.feed("_1> there")
    out += r.flush()
    assert out == "Hello Alice there"


def test_stream_restorer_holds_only_partial_tokens():
    r = StreamRestorer(_swap)
    # a literal '<' that is not a token prefix must not be held forever
    assert r.feed("a < b and ") == "a < b and "
    assert r.flush() == ""


def test_stream_restorer_complete_token_one_chunk():
    r = StreamRestorer(_swap)
    assert r.feed("see <PERSON_1>!") == "see Alice!"
    assert r.flush() == ""


def test_split_sse_event():
    assert split_sse_event("data: hello") == (None, "hello")
    assert split_sse_event("event: ping\ndata: {}") == ("ping", "{}")
    assert split_sse_event(": keep-alive comment") == (None, None)


def test_restore_sse_data_openai_delta():
    a = get_adapter("openai")
    r = StreamRestorer(_swap)
    data = json.dumps({"choices": [{"delta": {"content": "<PERSON_1>"}}]})
    out = restore_sse_data(data, a, r)
    assert json.loads(out)["choices"][0]["delta"]["content"] == "Alice"


def test_restore_sse_data_done_passthrough():
    a = get_adapter("openai")
    r = StreamRestorer(_swap)
    assert restore_sse_data("[DONE]", a, r) == "[DONE]"
