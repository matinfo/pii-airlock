"""Payload adapters + streaming reassembly (pure, no Presidio needed)."""

from __future__ import annotations

import json

from pii_scrub.payload import (
    StreamRestorer,
    StreamState,
    get_adapter,
    json_escaped,
    restore_payload,
    restore_sse_event,
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
    # role/model untouched
    assert out["messages"][1]["role"] == "user" and out["model"] == "gpt-x"
    # original not mutated
    assert body["messages"][1]["content"] == "hello secret"


def test_openai_chat_tool_calls_and_tool_results():
    a = get_adapter("openai")
    body = {"messages": [
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "send_mail", "arguments": '{"to": "secret"}'}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "sent to secret"},
    ]}
    out = scrub_payload(body, a, UP)
    fn = out["messages"][0]["tool_calls"][0]["function"]
    assert json.loads(fn["arguments"]) == {"to": "SECRET"}
    assert fn["name"] == "send_mail"
    assert out["messages"][1]["content"] == "SENT TO SECRET"


def test_openai_responses_api_request():
    a = get_adapter("openai")
    body = {
        "model": "gpt-x",
        "instructions": "sys secret",
        "input": [
            {"role": "user", "content": [{"type": "input_text", "text": "hi secret"}]},
            {"type": "function_call", "call_id": "c1", "name": "shell",
             "arguments": '{"cmd": ["cat", "secret.txt"]}'},
            {"type": "function_call_output", "call_id": "c1", "output": "file says secret"},
            {"type": "message", "role": "assistant",
             "content": [{"type": "output_text", "text": "ok secret"}]},
        ],
    }
    out = scrub_payload(body, a, UP)
    assert out["instructions"] == "SYS SECRET"
    assert out["input"][0]["content"][0]["text"] == "HI SECRET"
    assert json.loads(out["input"][1]["arguments"]) == {"cmd": ["CAT", "SECRET.TXT"]}
    assert out["input"][1]["call_id"] == "c1"
    assert out["input"][2]["output"] == "FILE SAYS SECRET"
    assert out["input"][3]["content"][0]["text"] == "OK SECRET"


def test_openai_input_string_prompt_list_and_embeddings():
    a = get_adapter("openai")
    assert scrub_payload({"input": "hi secret"}, a, UP)["input"] == "HI SECRET"
    assert scrub_payload({"input": ["a", "b"]}, a, UP)["input"] == ["A", "B"]
    assert scrub_payload({"prompt": ["x", "y"]}, a, UP)["prompt"] == ["X", "Y"]
    # token-id inputs are left alone
    assert scrub_payload({"input": [[1, 2, 3]]}, a, UP)["input"] == [[1, 2, 3]]


def test_openai_response_restore_covers_tool_calls_and_responses_output():
    a = get_adapter("openai")
    full = {"choices": [{"message": {"role": "assistant", "content": "hi there",
                                     "tool_calls": [{"function": {"arguments": '{"a": "b"}'}}]}}]}
    out = restore_payload(full, a, UP)
    assert out["choices"][0]["message"]["content"] == "HI THERE"

    resp = {"object": "response", "output": [
        {"type": "message", "content": [{"type": "output_text", "text": "hey"}]},
    ]}
    assert restore_payload(resp, a, UP)["output"][0]["content"][0]["text"] == "HEY"


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


def test_anthropic_tool_use_tool_result_document_and_thinking():
    a = get_adapter("anthropic")
    body = {"messages": [
        {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "secret plan", "signature": "sig"},
            {"type": "tool_use", "id": "t1", "name": "read", "input": {"path": "secret.txt"}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "file has secret"},
            {"type": "tool_result", "tool_use_id": "t2",
             "content": [{"type": "text", "text": "nested secret"}]},
            {"type": "document", "source": {"type": "text", "media_type": "text/plain",
                                            "data": "doc secret"}},
        ]},
    ]}
    out = scrub_payload(body, a, UP)
    blocks = out["messages"][0]["content"]
    assert blocks[0]["thinking"] == "secret plan"  # signed: untouched
    assert blocks[1]["input"] == {"path": "SECRET.TXT"}
    assert blocks[1]["name"] == "read"
    results = out["messages"][1]["content"]
    assert results[0]["content"] == "FILE HAS SECRET"
    assert results[0]["tool_use_id"] == "t1"
    assert results[1]["content"][0]["text"] == "NESTED SECRET"
    assert results[2]["source"]["data"] == "DOC SECRET"


def test_anthropic_message_batches():
    a = get_adapter("anthropic")
    body = {"requests": [{"custom_id": "r1", "params": {
        "messages": [{"role": "user", "content": "batch secret"}]}}]}
    out = scrub_payload(body, a, UP)
    assert out["requests"][0]["params"]["messages"][0]["content"] == "BATCH SECRET"
    assert out["requests"][0]["custom_id"] == "r1"


def test_anthropic_response_restores_tool_use_but_not_thinking():
    a = get_adapter("anthropic")
    full = {"content": [
        {"type": "thinking", "thinking": "keep", "signature": "s"},
        {"type": "text", "text": "answer"},
        {"type": "tool_use", "input": {"q": "x"}},
    ]}
    out = restore_payload(full, a, UP)
    assert out["content"][0]["thinking"] == "keep"
    assert out["content"][1]["text"] == "ANSWER"
    assert out["content"][2]["input"] == {"q": "X"}


def test_gemini_request_and_response():
    a = get_adapter("gemini")
    body = {
        "contents": [{"role": "user", "parts": [
            {"text": "ask secret"},
            {"functionResponse": {"name": "f", "response": {"r": "secret"}}},
        ]}],
        "systemInstruction": {"parts": [{"text": "sys secret"}]},
    }
    out = scrub_payload(body, a, UP)
    assert out["contents"][0]["parts"][0]["text"] == "ASK SECRET"
    assert out["contents"][0]["parts"][1]["functionResponse"] == {
        "name": "f", "response": {"r": "SECRET"}}
    assert out["systemInstruction"]["parts"][0]["text"] == "SYS SECRET"

    resp = {"candidates": [{"content": {"parts": [{"text": "reply"}]}}]}
    assert restore_payload(resp, a, UP)["candidates"][0]["content"]["parts"][0]["text"] == "REPLY"
    # non-SSE stream arrives as a JSON array
    assert restore_payload([resp], a, UP)[0]["candidates"][0]["content"]["parts"][0]["text"] \
        == "REPLY"


def test_gemini_embed_and_count_tokens():
    a = get_adapter("gemini")
    out = scrub_payload({"content": {"parts": [{"text": "e secret"}]}}, a, UP)
    assert out["content"]["parts"][0]["text"] == "E SECRET"
    out = scrub_payload({"requests": [{"content": {"parts": [{"text": "b"}]}}]}, a, UP)
    assert out["requests"][0]["content"]["parts"][0]["text"] == "B"
    out = scrub_payload({"generateContentRequest": {"contents": [{"parts": [{"text": "c"}]}]}},
                        a, UP)
    assert out["generateContentRequest"]["contents"][0]["parts"][0]["text"] == "C"


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


def test_json_escaped_restore():
    restore = json_escaped(lambda t: t.replace("<PERSON_1>", 'A "quoted" name'))
    out = restore('{"to": "<PERSON_1>"}')
    assert json.loads(out) == {"to": 'A "quoted" name'}


def test_split_sse_event():
    assert split_sse_event("data: hello") == (None, "hello")
    assert split_sse_event("event: ping\ndata: {}") == ("ping", "{}")
    assert split_sse_event(": keep-alive comment") == (None, None)


def _events(text: str) -> list[tuple[str | None, dict | str]]:
    out = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        name, data = split_sse_event(block)
        out.append((name, data if data == "[DONE]" else json.loads(data)))
    return out


def test_restore_sse_event_openai_delta():
    a = get_adapter("openai")
    state = StreamState(_swap)
    data = json.dumps({"choices": [{"delta": {"content": "<PERSON_1>"}}]})
    (_, chunk), = _events(restore_sse_event(f"data: {data}", a, state))
    assert chunk["choices"][0]["delta"]["content"] == "Alice"


def test_restore_sse_event_done_passthrough():
    a = get_adapter("openai")
    assert restore_sse_event("data: [DONE]", a, StreamState(_swap)) == "data: [DONE]\n\n"


def test_openai_stream_choices_restored_independently():
    """n>1: a partial token in one choice must not swallow the other's text."""
    a = get_adapter("openai")
    state = StreamState(_swap)

    def chunk(i, text, finish=None):
        return "data: " + json.dumps(
            {"choices": [{"index": i, "delta": {"content": text}, "finish_reason": finish}]})

    out = ""
    for raw in [chunk(0, "Hi <PER"), chunk(1, "Yo <PERSON_1>"), chunk(0, "SON_1>"),
                chunk(0, " <PER", "stop"), "data: [DONE]"]:
        out += restore_sse_event(raw, a, state)
    texts = {0: "", 1: ""}
    for _, c in _events(out):
        if c != "[DONE]":
            ch = c["choices"][0]
            texts[ch["index"]] += ch["delta"].get("content") or ""
    assert texts == {0: "Hi Alice <PER", 1: "Yo Alice"}
    # tail flushed in the finishing chunk, not after [DONE]
    assert _events(out)[-1][1] == "[DONE]"


def test_openai_stream_tool_call_arguments_json_escaped():
    a = get_adapter("openai")
    state = StreamState(lambda t: t.replace("<PERSON_1>", 'Al"ice'))
    frags = ['{"to": "<PER', 'SON_1>"}']
    out = ""
    for n, frag in enumerate(frags):
        out += restore_sse_event("data: " + json.dumps({"choices": [{
            "index": 0, "finish_reason": "tool_calls" if n == len(frags) - 1 else None,
            "delta": {"tool_calls": [{"index": 0, "function": {"arguments": frag}}]}}]}),
            a, state)
    args = "".join(
        tc["function"]["arguments"]
        for _, c in _events(out) for tc in c["choices"][0]["delta"]["tool_calls"])
    assert json.loads(args) == {"to": 'Al"ice'}


def test_openai_responses_stream_flushes_before_done():
    a = get_adapter("openai")
    state = StreamState(_swap)
    base = {"item_id": "m1", "output_index": 0, "content_index": 0}
    raws = [
        ("response.output_text.delta", {**base, "delta": "Hi <PER"}),
        ("response.output_text.delta", {**base, "delta": "SON_1> <PE"}),
        ("response.output_text.done", {**base, "text": "Hi <PERSON_1> <PE"}),
    ]
    out = ""
    for name, data in raws:
        out += restore_sse_event(
            f"event: {name}\ndata: {json.dumps({'type': name, **data})}", a, state)
    events = _events(out)
    deltas = "".join(c["delta"] for n, c in events if n == "response.output_text.delta")
    assert deltas == "Hi Alice <PE"
    assert events[-1][0] == "response.output_text.done"
    assert events[-1][1]["text"] == "Hi Alice <PE"
    assert all(n == c["type"] for n, c in events)


def test_anthropic_stream_flush_inside_block_with_event_name():
    a = get_adapter("anthropic")
    state = StreamState(_swap)

    def ev(name, data):
        return f"event: {name}\ndata: {json.dumps({'type': name, **data})}"

    raws = [
        ev("content_block_start", {"index": 0, "content_block": {"type": "text", "text": ""}}),
        ev("content_block_delta", {"index": 0, "delta": {"type": "text_delta", "text": "x <PER"}}),
        ev("content_block_start", {"index": 1, "content_block": {"type": "tool_use"}}),
        ev("content_block_delta", {"index": 1,
                                   "delta": {"type": "input_json_delta", "partial_json": "{"}}),
        ev("content_block_stop", {"index": 0}),
        ev("content_block_stop", {"index": 1}),
        ev("message_stop", {}),
    ]
    out = "".join(restore_sse_event(r, a, state) for r in raws)
    events = _events(out)
    names = [n for n, _ in events]
    # every event keeps its `event:` line and matches its data type
    assert all(n == c["type"] for n, c in events)
    # the held-back "<PER" of block 0 is emitted before block 0 stops
    stop0 = next(i for i, (n, c) in enumerate(events)
                 if n == "content_block_stop" and c["index"] == 0)
    assert events[stop0 - 1][1] == {"type": "content_block_delta", "index": 0,
                                    "delta": {"type": "text_delta", "text": "<PER"}}
    assert names[-1] == "message_stop"
