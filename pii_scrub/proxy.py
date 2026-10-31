"""Local privacy gateway: a reverse proxy that scrubs PII out and restores it in.

Point any LLM client at this proxy via its base-URL setting. Outbound request
bodies have PII replaced with stable tokens before they leave the machine;
inbound responses (including SSE streams) have the real values restored, so the
client never knows the difference.

    client ──http──▶ pii-airlock proxy ──https──▶ provider API
            ◀────────  (restore)  ◀──────────  (scrub)

No TLS interception: the client connects to this local plaintext endpoint, and
the proxy makes the real HTTPS call upstream. Auth headers pass through verbatim
and are never logged. A fresh mapping object is used per request (with a
configurable backend).

Fail closed: a request body the proxy cannot scrub (unknown endpoint, or not
valid JSON) is refused rather than forwarded, unless its path matches one of
the configured ``passthrough_paths``.
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import Config, load_config
from .engine import PolicyBlocked
from .mapping_store import build_mapping_store
from .payload import (
    StreamState,
    format_sse,
    get_adapter,
    restore_sse_event,
    scrub_payload,
)
from .token_key import token_key

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
            "Install them with:  pip install 'pii-airlock[proxy]'"
        ) from exc


_BODY_METHODS = {"POST", "PUT", "PATCH"}


def _is_generation_endpoint(adapter, path: str) -> bool:
    return any(frag in path for frag in adapter.request_endpoints)


def _scrub_request(engine, payload: dict, adapter, mapping) -> dict:
    """Scrub a request body: all its strings are analyzed first, so a value found
    in any message (or tool result) is scrubbed in every one, earlier ones too."""
    return engine.scrub_all(lambda f: scrub_payload(payload, adapter, f), mapping)


def _is_passthrough(config: Config, provider: str, path: str) -> bool:
    """Whether an unscrubbable body may be forwarded raw (explicit opt-in)."""
    full = f"{provider}/{path}"
    return any(frag and frag in full for frag in config.passthrough_paths)


def build_app(
    config: Config | None = None,
    upstreams: dict[str, str] | None = None,
    engine=None,
    client=None,
    mapping_store=None,
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
    token_key(config)  # fail at startup on a bad token_style / token_rotation
    upstreams = {**DEFAULT_UPSTREAMS, **(upstreams or {})}
    engine = engine if engine is not None else ScrubEngine(config)
    client = client if client is not None else httpx.AsyncClient(
        timeout=httpx.Timeout(600.0, connect=10.0)
    )
    mapping_store = mapping_store if mapping_store is not None else build_mapping_store(
        config.mapping_backend,
        root=Path(config.mapping_dir) if config.mapping_dir else None,
        encrypt=config.mapping_encryption,
    )

    async def handle(request: Request) -> Response:
        provider = request.path_params["provider"]
        path = request.path_params["path"]
        map_key: str | None = None
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

        # --- scrub outbound; refuse what we can't scrub (fail closed) ---
        # Per request, not at startup: the stable-token key rotates (token_rotation).
        mapping = mapping_store.create(token_key(config),
                                       surrogates=config.token_style == "surrogate")
        has_body = bool(body) and request.method in _BODY_METHODS
        scrub_this = has_body and _is_generation_endpoint(adapter, path)
        if has_body and not scrub_this and not _is_passthrough(config, provider, path):
            return Response(
                f"pii-airlock: refusing to forward a request body to '{provider}/{path}' "
                "— this endpoint is not scrubbed. If it carries no personal data, add it "
                "to `passthrough_paths` in your config.",
                status_code=403,
            )
        if scrub_this:
            try:
                payload = json.loads(body)
            except ValueError:
                payload = None
            if not isinstance(payload, dict):
                return Response(
                    "pii-airlock: refusing to forward a request body that is not a JSON "
                    "object (cannot scrub it).",
                    status_code=400,
                )
            try:
                scrubbed = await run_in_threadpool(
                    _scrub_request, engine, payload, adapter, mapping
                )
            except PolicyBlocked as exc:
                # The value itself is never echoed: only entity types and counts.
                return Response(
                    f"pii-airlock: request not sent — {exc}. Remove it from the "
                    "conversation, or change `entity_actions` in your policy.",
                    status_code=403,
                )
            except RuntimeError as exc:
                # e.g. spaCy model not installed — fail loud, don't leak by
                # silently forwarding the original PII.
                return Response(
                    f"pii-airlock: cannot scrub request — {exc}\n"
                    "Run `pii-airlock download-models`.",
                    status_code=503,
                )
            body = json.dumps(scrubbed, ensure_ascii=False).encode("utf-8")
            map_key = mapping_store.save(mapping)
            mapping = mapping_store.load(map_key)

        # Forward the raw query string so multi-value params (and Gemini's ?key=)
        # are preserved exactly.
        url = f"{upstream.rstrip('/')}/{path}"
        upstream_req = client.build_request(
            request.method, url,
            params=request.url.query or None, headers=req_headers, content=body,
        )
        try:
            upstream_resp = await client.send(upstream_req, stream=True)
        except httpx.HTTPError as exc:
            if map_key is not None:
                mapping_store.delete(map_key)
            return Response(f"pii-airlock: upstream request failed — {exc}", status_code=502)

        resp_headers = {
            k: v for k, v in upstream_resp.headers.items()
            if k.lower() not in _DROP_RESPONSE_HEADERS
        }
        content_type = upstream_resp.headers.get("content-type", "")

        # --- restore inbound: stream (SSE) ---
        if scrub_this and content_type.startswith("text/event-stream"):
            return StreamingResponse(
                _restore_stream(
                    upstream_resp,
                    adapter,
                    mapping,
                    mapping_store=mapping_store,
                    map_key=map_key,
                ),
                status_code=upstream_resp.status_code,
                headers=resp_headers,
                media_type="text/event-stream",
            )

        # --- restore inbound: buffered (JSON, or Gemini's array stream) ---
        try:
            raw = await upstream_resp.aread()
        except httpx.HTTPError as exc:
            if map_key is not None:
                mapping_store.delete(map_key)
            return Response(f"pii-airlock: upstream response failed — {exc}", status_code=502)
        finally:
            await upstream_resp.aclose()
        if scrub_this and "json" in content_type:
            try:
                data = json.loads(raw)
                data = adapter.restore_response(data, mapping.restore)
                raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
            except ValueError:
                pass  # not JSON after all (e.g. an error page) — pass through
        if map_key is not None:
            mapping_store.delete(map_key)
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
    app.state.mapping_store = mapping_store
    return app


async def _restore_stream(
    upstream_resp, adapter, mapping, mapping_store=None, map_key: str | None = None
):
    """Yield SSE events with tokens restored, reassembling tokens split across chunks.

    Each text channel (choice, content block, tool call) is restored separately;
    held-back tails are released before their block/choice closes.
    """
    state = StreamState(mapping.restore)
    buffer = ""
    try:
        async for text in upstream_resp.aiter_text():
            # Normalize CRLF so event boundaries split regardless of provider style.
            # (SSE clients accept LF; data lines are single JSON lines, so this is safe.)
            buffer += text.replace("\r\n", "\n")
            while "\n\n" in buffer:
                event, _, buffer = buffer.partition("\n\n")
                yield restore_sse_event(event, adapter, state)
        if buffer.strip():
            yield restore_sse_event(buffer, adapter, state)
        # Truncated stream: release whatever is still held back.
        tail = format_sse(adapter.finish(state))
        if tail:
            yield tail
    finally:
        await upstream_resp.aclose()
        if map_key is not None and mapping_store is not None:
            mapping_store.delete(map_key)


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
