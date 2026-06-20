"""Provider-agnostic payload scrubbing.

The :class:`~pii_scrub.engine.ScrubEngine` and :class:`~pii_scrub.mapping.Mapping`
are provider-agnostic. The *only* provider-specific knowledge is **where the
user text lives in a request body, and where the model text lives in a response
body**. That knowledge is captured here as a :class:`PayloadAdapter`.

This mirrors the ``formats/`` design: a structural locator plus a ``str -> str``
transform. ``scrub_payload`` passes a scrubbing transform; ``restore_payload``
passes ``Mapping.restore``. One engine, many adapters.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

Transform = Callable[[str], str]


# --- shared helpers ------------------------------------------------------


def _apply_content(content: Any, transform: Transform, text_key: str = "text") -> Any:
    """Apply `transform` to a chat "content" field.

    Handles both shapes seen across providers:
      * a plain string                         -> transform it
      * a list of typed parts (``{type, text}``) -> transform each ``text`` part
    Anything else is returned unchanged.
    """
    if isinstance(content, str):
        return transform(content)
    if isinstance(content, list):
        out = []
        for part in content:
            if isinstance(part, dict) and isinstance(part.get(text_key), str):
                part = {**part, text_key: transform(part[text_key])}
            out.append(part)
        return out
    return content


def _apply_parts(node: Any, transform: Transform) -> Any:
    """Apply `transform` to every ``parts[].text`` under a Gemini content node."""
    if not isinstance(node, dict) or not isinstance(node.get("parts"), list):
        return node
    parts = [
        {**p, "text": transform(p["text"])}
        if isinstance(p, dict) and isinstance(p.get("text"), str)
        else p
        for p in node["parts"]
    ]
    return {**node, "parts": parts}


# --- adapters ------------------------------------------------------------


class PayloadAdapter:
    """Locate user/model text inside one provider's wire format."""

    #: registry key and CLI/proxy route name
    name: str = ""
    #: path fragments whose POST bodies carry a generation request
    request_endpoints: tuple[str, ...] = ()

    def scrub_request(self, body: dict, transform: Transform) -> dict:
        """Return a copy of a request body with user text transformed."""
        raise NotImplementedError

    def restore_response(self, body: dict, transform: Transform) -> dict:
        """Return a copy of a (non-streaming) response body with model text transformed."""
        raise NotImplementedError

    def restore_delta(self, chunk: dict, transform: Transform) -> dict:
        """Return a copy of a single streaming delta chunk with model text transformed.

        Defaults to :meth:`restore_response`; override when the streaming shape
        differs from the full-body shape (e.g. OpenAI ``delta`` vs ``message``).
        """
        return self.restore_response(chunk, transform)

    def text_chunk(self, text: str) -> dict | None:
        """Build a minimal streaming chunk carrying `text`, in this provider's shape.

        Used only to flush a reassembled token tail at end of stream. Returns
        None if the provider's stream isn't SSE-shaped.
        """
        return None


class OpenAIAdapter(PayloadAdapter):
    """OpenAI-compatible Chat Completions (also Codex, Cursor, Ollama, LiteLLM, ...)."""

    name = "openai"
    request_endpoints = ("chat/completions", "completions", "responses")

    def scrub_request(self, body: dict, transform: Transform) -> dict:
        out = dict(body)
        if isinstance(body.get("messages"), list):
            out["messages"] = [
                {**m, "content": _apply_content(m["content"], transform)}
                if isinstance(m, dict) and "content" in m
                else m
                for m in body["messages"]
            ]
        if isinstance(body.get("prompt"), str):  # legacy completions
            out["prompt"] = transform(body["prompt"])
        return out

    def restore_response(self, body: dict, transform: Transform) -> dict:
        out = dict(body)
        if isinstance(body.get("choices"), list):
            out["choices"] = [_restore_choice(c, transform, "message") for c in body["choices"]]
        return out

    def restore_delta(self, chunk: dict, transform: Transform) -> dict:
        out = dict(chunk)
        if isinstance(chunk.get("choices"), list):
            out["choices"] = [_restore_choice(c, transform, "delta") for c in chunk["choices"]]
        return out

    def text_chunk(self, text: str) -> dict | None:
        return {"choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]}


def _restore_choice(choice: Any, transform: Transform, key: str) -> Any:
    if not isinstance(choice, dict) or not isinstance(choice.get(key), dict):
        return choice
    inner = choice[key]
    if isinstance(inner.get("content"), str | list):
        inner = {**inner, "content": _apply_content(inner["content"], transform)}
    return {**choice, key: inner}


class AnthropicAdapter(PayloadAdapter):
    """Anthropic Messages API."""

    name = "anthropic"
    request_endpoints = ("messages",)

    def scrub_request(self, body: dict, transform: Transform) -> dict:
        out = dict(body)
        if "system" in body:
            out["system"] = _apply_content(body["system"], transform)
        if isinstance(body.get("messages"), list):
            out["messages"] = [
                {**m, "content": _apply_content(m["content"], transform)}
                if isinstance(m, dict) and "content" in m
                else m
                for m in body["messages"]
            ]
        return out

    def restore_response(self, body: dict, transform: Transform) -> dict:
        out = dict(body)
        if isinstance(body.get("content"), str | list):
            out["content"] = _apply_content(body["content"], transform)
        return out

    def restore_delta(self, chunk: dict, transform: Transform) -> dict:
        # content_block_delta events carry {"delta": {"type": "text_delta", "text": "..."}}
        delta = chunk.get("delta")
        if isinstance(delta, dict) and isinstance(delta.get("text"), str):
            return {**chunk, "delta": {**delta, "text": transform(delta["text"])}}
        # content_block_start may carry an initial text block
        block = chunk.get("content_block")
        if isinstance(block, dict) and isinstance(block.get("text"), str):
            return {**chunk, "content_block": {**block, "text": transform(block["text"])}}
        return chunk

    def text_chunk(self, text: str) -> dict | None:
        return {"type": "content_block_delta", "index": 0,
                "delta": {"type": "text_delta", "text": text}}


class GeminiAdapter(PayloadAdapter):
    """Google Gemini generateContent / streamGenerateContent."""

    name = "gemini"
    request_endpoints = ("generateContent", "streamGenerateContent")

    def scrub_request(self, body: dict, transform: Transform) -> dict:
        out = dict(body)
        if isinstance(body.get("contents"), list):
            out["contents"] = [_apply_parts(c, transform) for c in body["contents"]]
        if isinstance(body.get("systemInstruction"), dict):
            out["systemInstruction"] = _apply_parts(body["systemInstruction"], transform)
        return out

    def restore_response(self, body: dict, transform: Transform) -> dict:
        out = dict(body)
        if isinstance(body.get("candidates"), list):
            out["candidates"] = [
                {**c, "content": _apply_parts(c["content"], transform)}
                if isinstance(c, dict) and isinstance(c.get("content"), dict)
                else c
                for c in body["candidates"]
            ]
        return out

    def text_chunk(self, text: str) -> dict | None:
        return {"candidates": [{"content": {"parts": [{"text": text}], "role": "model"}}]}


_ADAPTERS: dict[str, PayloadAdapter] = {
    a.name: a for a in (OpenAIAdapter(), AnthropicAdapter(), GeminiAdapter())
}


def get_adapter(name: str) -> PayloadAdapter:
    try:
        return _ADAPTERS[name]
    except KeyError:
        raise ValueError(
            f"Unknown provider '{name}'. Known: {', '.join(sorted(_ADAPTERS))}."
        ) from None


def adapter_names() -> list[str]:
    return sorted(_ADAPTERS)


# --- top-level scrub / restore over a parsed body ------------------------


def scrub_payload(body: dict, adapter: PayloadAdapter, scrub: Transform) -> dict:
    """Scrub user text in a request `body`. `scrub` is `text -> tokenized text`."""
    return adapter.scrub_request(body, scrub)


def restore_payload(body: dict, adapter: PayloadAdapter, restore: Transform) -> dict:
    """Restore model text in a non-streaming response `body`."""
    return adapter.restore_response(body, restore)


# --- streaming token reassembly ------------------------------------------


class StreamRestorer:
    """Restore tokens across a stream where a token may split between chunks.

    A placeholder like ``<PERSON_1>`` can arrive as ``<PERS`` then ``ON_1>``.
    Feeding fragments, this holds back any trailing partial-token prefix and
    only restores+emits text that cannot still be part of an unfinished token.
    Call :meth:`flush` once at end of stream to release any remainder.
    """

    # A trailing run that could still grow into a token: '<' + token-ish chars.
    _PARTIAL = re.compile(r"<[A-Z0-9_]*$")

    def __init__(self, restore: Transform) -> None:
        self._restore = restore
        self._buf = ""

    def feed(self, fragment: str) -> str:
        self._buf += fragment
        m = self._PARTIAL.search(self._buf)
        if m:
            safe, self._buf = self._buf[: m.start()], self._buf[m.start() :]
        else:
            safe, self._buf = self._buf, ""
        return self._restore(safe)

    def flush(self) -> str:
        out = self._restore(self._buf)
        self._buf = ""
        return out


# --- SSE helpers (used by the proxy) -------------------------------------


def split_sse_event(raw: str) -> tuple[str | None, str | None]:
    """Parse a single SSE event block into (event_name, data_string).

    Returns (None, None) when there is no ``data:`` line (comment/keep-alive).
    """
    event = None
    data_lines: list[str] = []
    for line in raw.splitlines():
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
        elif line.startswith("event:"):
            event = line[6:].strip()
    if not data_lines:
        return event, None
    return event, "\n".join(data_lines)


def restore_sse_data(
    data: str, adapter: PayloadAdapter, restorer: StreamRestorer
) -> str:
    """Restore one SSE ``data:`` payload. Passes through ``[DONE]`` and non-JSON."""
    if data.strip() == "[DONE]":
        return data
    try:
        chunk = json.loads(data)
    except (ValueError, TypeError):
        return data
    if not isinstance(chunk, dict):
        return data
    restored = adapter.restore_delta(chunk, restorer.feed)
    return json.dumps(restored, ensure_ascii=False)
