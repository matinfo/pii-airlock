"""Local privacy gateway: a reverse proxy that scrubs PII out and restores it in.

Point any LLM client at this proxy via its base-URL setting. Outbound request
bodies have PII replaced with stable tokens before they leave the machine;
inbound responses (including SSE streams) have the real values restored, so the
client never knows the difference.

    client ──http──▶ pii-scrub proxy ──https──▶ provider API
            ◀────────  (restore)  ◀──────────  (scrub)

No TLS interception: the client connects to this local plaintext endpoint, and
the proxy makes the real HTTPS call upstream. Auth headers pass through verbatim
and are never logged. A fresh in-memory mapping is used per request and is
discarded immediately after the response — nothing touches disk.
"""

from __future__ import annotations

import json

from .config import Config, load_config
from .payload import (
    StreamRestorer,
    get_adapter,
    restore_sse_data,
    scrub_payload,
)

# Default upstreams (override per deployment via build_app / CLI flags).
DEFAULT_UPSTREAMS: dict[str, str] = {
    "openai": "https://api.openai.com",
    "anthropic": "https://api.anthropic.com",
    "gemini": "https://generativelanguage.googleapis.com",
}

# Request/response headers we must not forward verbatim (hop-by-hop or recomputed).
_DROP_REQUEST_HEADERS = {"host", "content-length", "accept-encoding", "connection"}
_DROP_RESPONSE_HEADERS = {"content-length", "content-encoding", "transfer-encoding", "connection"}


def _require_deps():
    try:
        import httpx  # noqa: F401
        import starlette  # noqa: F401
        import uvicorn  # noqa: F401
    except ModuleNotFoundError as exc:  # pragma: no cover - import guard
        raise SystemExit(
            "The proxy requires extra dependencies.\n"
            "Install them with:  pip install 'pii-scrub[proxy]'"
        ) from exc


def _is_generation_endpoint(adapter, path: str) -> bool:
    return any(frag in path for frag in adapter.request_endpoints)


def build_app(
    config: Config | None = None,
    upstreams: dict[str, str] | None = None,
    engine=None,
    client=None,
):
    """Build the Starlette ASGI app for the gateway.

    `engine` and `client` may be injected for testing; otherwise a real
    ScrubEngine and httpx.AsyncClient are created.
    """
    _require_deps()
    import httpx
    from starlette.applications import Starlette
    from starlette.concurrency import run_in_threadpool
    from starlette.requests import Request
    from starlette.responses import Response, StreamingResponse
    from starlette.routing import Route

    from .engine import ScrubEngine

    config = config or load_config()
    upstreams = {**DEFAULT_UPSTREAMS, **(upstreams or {})}
    engine = engine if engine is not None else ScrubEngine(config)
    language = config.languages[0]
    client = client if client is not None else httpx.AsyncClient(
        timeout=httpx.Timeout(600.0, connect=10.0)
    )

    async def handle(request: Request) -> Response:
        provider = request.path_params["provider"]
        path = request.path_params["path"]
        try:
            adapter = get_adapter(provider)
        except ValueError:
            return Response(f"Unknown provider '{provider}'.", status_code=404)

        upstream = upstreams.get(provider)
        if not upstream:
            return Response(f"No upstream configured for '{provider}'.", status_code=404)

        body = await request.body()
        req_headers = {
            k: v for k, v in request.headers.items() if k.lower() not in _DROP_REQUEST_HEADERS
        }

        # --- scrub outbound (generation endpoints with a JSON body only) ---
        mapping = _new_mapping()
        scrub_this = _is_generation_endpoint(adapter, path) and body
        if scrub_this:
            try:
                payload = json.loads(body)
            except ValueError:
                scrub_this = False
            else:
                scrubbed = await run_in_threadpool(
                    scrub_payload, payload, adapter,
                    lambda t: engine.scrub(t, mapping, language),
                )
                body = json.dumps(scrubbed, ensure_ascii=False).encode("utf-8")

        url = f"{upstream.rstrip('/')}/{path}"
        upstream_req = client.build_request(
            request.method, url,
            params=request.query_params, headers=req_headers, content=body,
        )
        upstream_resp = await client.send(upstream_req, stream=True)

        resp_headers = {
            k: v for k, v in upstream_resp.headers.items()
            if k.lower() not in _DROP_RESPONSE_HEADERS
        }
        content_type = upstream_resp.headers.get("content-type", "")

        # --- restore inbound: stream (SSE) ---
        if scrub_this and content_type.startswith("text/event-stream"):
            return StreamingResponse(
                _restore_stream(upstream_resp, adapter, mapping),
                status_code=upstream_resp.status_code,
                headers=resp_headers,
                media_type="text/event-stream",
            )

        # --- restore inbound: buffered (JSON, or Gemini's array stream) ---
        raw = await upstream_resp.aread()
        await upstream_resp.aclose()
        if scrub_this and "json" in content_type:
            try:
                data = json.loads(raw)
                data = adapter.restore_response(data, mapping.restore)
                raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
            except ValueError:
                pass  # not JSON after all (e.g. an error page) — pass through
        return Response(raw, status_code=upstream_resp.status_code, headers=resp_headers)

    async def health(_request: Request) -> Response:
        return Response(json.dumps({"status": "ok", "languages": config.languages}),
                        media_type="application/json")

    routes = [
        Route("/healthz", health, methods=["GET"]),
        Route("/{provider}/{path:path}", handle,
              methods=["GET", "POST", "PUT", "PATCH", "DELETE"]),
    ]
    app = Starlette(routes=routes)
    app.state.engine = engine
    return app


async def _restore_stream(upstream_resp, adapter, mapping):
    """Yield SSE events with tokens restored, reassembling tokens split across chunks."""
    restorer = StreamRestorer(mapping.restore)
    buffer = ""
    async for text in upstream_resp.aiter_text():
        buffer += text
        while "\n\n" in buffer:
            event, _, buffer = buffer.partition("\n\n")
            yield _restore_event(event, adapter, restorer) + "\n\n"
    if buffer.strip():
        yield _restore_event(buffer, adapter, restorer) + "\n\n"
    # Flush any held-back token tail as one final, provider-shaped chunk.
    tail = restorer.flush()
    if tail:
        chunk = adapter.text_chunk(tail)
        if chunk is not None:
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
    await upstream_resp.aclose()


def _restore_event(raw_event: str, adapter, restorer: StreamRestorer) -> str:
    """Rewrite a single SSE event block, restoring tokens in its data payload."""
    from .payload import split_sse_event

    event_name, data = split_sse_event(raw_event)
    if data is None:
        return raw_event  # comment / keep-alive / event-only line — leave as-is
    restored = restore_sse_data(data, adapter, restorer)
    prefix = f"event: {event_name}\n" if event_name else ""
    return f"{prefix}data: {restored}"


def _new_mapping():
    from .mapping import Mapping

    return Mapping()


def run(
    host: str = "127.0.0.1",
    port: int = 8745,
    config: Config | None = None,
    upstreams: dict[str, str] | None = None,
) -> None:
    """Run the gateway with uvicorn (blocking)."""
    _require_deps()
    import uvicorn

    app = build_app(config, upstreams)
    uvicorn.run(app, host=host, port=port, log_level="warning")
