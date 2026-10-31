"""Hook daemon: keeps Presidio and the spaCy models loaded between hook calls.

Claude Code starts a new process for every hook call, and loading the models
costs 0.5-3 s each time: on every Bash, Read or Edit. The daemon loads them
once and answers detection requests over a Unix socket, so a hook call costs
the analysis itself plus a few milliseconds.

Protocol: one JSON object per line, each way.
    -> {"build": id, "cwd": "/project", "texts": ["...", ...]}
    <- {"build": id, "detections": [[[entity, start, end, score], ...], ...]}
    <- {"build": id, "error": "message"}
    -> {"op": "ping"} / {"op": "stop"}
The config of `cwd` is loaded for every request, so policy edits apply at once;
projects that use the same models share one loaded engine and its cache.

Security: the socket (mode 0600) lives in a directory only the user can write
to, and clients check that before connecting, so another local user can
neither read the requests nor impersonate the daemon. Nothing leaves the
machine. POSIX only (Unix sockets, flock); elsewhere hooks analyze in-process.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import socketserver
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import __version__
from .config import Config, load_config
from .mapping_store import default_state_dir

SUPPORTED = os.name == "posix" and hasattr(socket, "AF_UNIX")

_CONNECT_TIMEOUT = 0.5
# Long enough for a cold model load plus a 2 MB file; a dead daemon fails fast.
_REPLY_TIMEOUT = 120.0


def runtime_dir() -> Path:
    """``$XDG_RUNTIME_DIR/pii-airlock`` if set, else the user state dir."""
    base = os.environ.get("XDG_RUNTIME_DIR")
    return Path(base) / "pii-airlock" if base else default_state_dir()


def socket_path() -> Path:
    return runtime_dir() / "hook.sock"


def log_path() -> Path:
    return runtime_dir() / "daemon.log"


def build_id() -> str:
    """Version plus source mtime: a daemon running older code must not answer."""
    package = Path(__file__).resolve().parent
    newest = max((p.stat().st_mtime_ns for p in package.rglob("*.py")), default=0)
    return f"{__version__}+{newest}"


def _is_private(path: Path, kind: int) -> bool:
    """`path` exists with file type `kind`, is ours, and no one else can write it."""
    try:
        st = path.lstat()
    except OSError:
        return False
    return (stat.S_IFMT(st.st_mode) == kind and st.st_uid == os.getuid()
            and not st.st_mode & (stat.S_IWGRP | stat.S_IWOTH))


# --- client ------------------------------------------------------------------


class DaemonError(RuntimeError):
    """The daemon ran the request and detection failed (e.g. model missing)."""


def call(message: dict, timeout: float = _REPLY_TIMEOUT) -> dict | None:
    """Send one request; the reply, or None if no trusted daemon is reachable."""
    if not SUPPORTED:
        return None
    path = socket_path()
    if not (_is_private(path.parent, stat.S_IFDIR) and _is_private(path, stat.S_IFSOCK)):
        return None
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(_CONNECT_TIMEOUT)
            sock.connect(str(path))
            sock.settimeout(timeout)
            sock.sendall(json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n")
            with sock.makefile("rb") as reply:
                return json.loads(reply.readline())
    except (OSError, ValueError):
        return None


def detect(cwd: str | None, texts: list[str]) -> list[list[tuple]] | None:
    """Detections per text from the daemon, or None to analyze another way.

    Raises DaemonError when the daemon itself could not detect: the caller must
    fail closed then, exactly as for an in-process failure.
    """
    build = build_id()
    reply = call({"build": build, "cwd": cwd, "texts": texts})
    if reply is None or reply.get("build") != build:
        return None  # not running, or older code (it exits on its own)
    if "error" in reply:
        raise DaemonError(reply["error"])
    return [[tuple(d) for d in per_text] for per_text in reply["detections"]]


def spawn(cwd: str | None = None) -> None:
    """Start a daemon in the background and return at once (no-op if unsupported).

    If one is already running (or starting), the new process exits right away.
    """
    if not SUPPORTED:
        return
    directory = runtime_dir()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "pii_scrub.daemon"]
    if cwd:
        cmd += ["--cwd", cwd]
    with open(log_path(), "ab") as log:
        subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            start_new_session=True, close_fds=True, cwd=str(directory),
        )


def wait_until_up(seconds: float) -> dict | None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        reply = call({"op": "ping"}, timeout=1.0)
        if reply is not None:
            return reply
        time.sleep(0.1)
    return None


# --- server ------------------------------------------------------------------


class _Engines:
    """One loaded engine per (languages, models), re-policied per request."""

    def __init__(self) -> None:
        self._base: dict[tuple, object] = {}
        self._lock = threading.Lock()

    def get(self, config: Config):
        from .engine import ScrubEngine

        key = (tuple(config.languages), tuple(sorted(config.models.items())),
               config.analysis_cache_size)
        with self._lock:  # one model load at a time, never twice
            base = self._base.get(key)
            if base is None:
                base = ScrubEngine(config)
                base.load()
                self._base[key] = base
        return base.with_config(config)


class _Handler(socketserver.StreamRequestHandler):
    server: _Server

    def handle(self) -> None:
        self.server.last_used = time.monotonic()
        try:
            reply = self.server.answer(json.loads(self.rfile.readline()))
        # SystemExit included: spaCy's model downloader calls sys.exit().
        except (Exception, SystemExit) as exc:
            reply = {"error": str(exc) or type(exc).__name__}
        reply["build"] = self.server.build
        self.wfile.write(json.dumps(reply, ensure_ascii=False).encode("utf-8") + b"\n")
        self.server.last_used = time.monotonic()


class _Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True

    def __init__(self, path: str) -> None:
        super().__init__(path, _Handler)
        self.build = build_id()
        self.engines = _Engines()
        self.last_used = time.monotonic()

    def stop(self) -> None:
        threading.Thread(target=self.shutdown, daemon=True).start()

    def answer(self, request: dict) -> dict:
        op = request.get("op")
        if op == "ping":
            return {"pid": os.getpid()}
        if op == "stop":
            self.stop()
            return {"stopping": True}
        if request.get("build") != self.build:
            self.stop()  # the package was upgraded: let a fresh daemon take over
            return {"error": "pii-airlock daemon is running older code; restarting"}
        texts = [t for t in request.get("texts", []) if isinstance(t, str)]
        engine = self.engines.get(load_config(cwd=request.get("cwd") or None))
        engine.prime(texts)
        return {"detections": [
            [[d.entity_type, d.start, d.end, d.score] for d in engine.detect(t)]
            for t in texts
        ]}


def serve(cwd: str | None = None) -> int:
    """Run the daemon in the foreground until stopped or idle (see config)."""
    import fcntl

    if not SUPPORTED:
        print("pii-airlock daemon needs Unix sockets (not available here).", file=sys.stderr)
        return 1
    directory = runtime_dir()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not _is_private(directory, stat.S_IFDIR):
        print(f"refusing to serve: {directory} is writable by other users", file=sys.stderr)
        return 1
    lock = open(directory / "hook.lock", "a+")  # held (and flocked) for our lifetime
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return 0  # another daemon is running or starting
    config = load_config(cwd=cwd)
    path = socket_path()
    path.unlink(missing_ok=True)  # stale: its owner no longer holds the lock
    old_umask = os.umask(0o177)
    try:
        server = _Server(str(path))
    finally:
        os.umask(old_umask)
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, lambda *_: server.stop())
    idle = config.hook_daemon_idle_minutes * 60

    def watch_idle() -> None:
        while idle > 0:
            time.sleep(min(idle, 30))
            if time.monotonic() - server.last_used > idle:
                server.stop()
                return

    threading.Thread(target=watch_idle, daemon=True).start()
    # Load the models now, so the first hook call does not wait for them.
    threading.Thread(target=lambda: _preload(server, config), daemon=True).start()
    print(f"pii-airlock daemon {server.build} pid {os.getpid()} on {path}", file=sys.stderr)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        path.unlink(missing_ok=True)
    return 0


def _preload(server: _Server, config: Config) -> None:
    try:
        server.engines.get(config)
    except (Exception, SystemExit) as exc:  # reported again on each request
        print(f"model preload failed: {exc}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m pii_scrub.daemon")
    parser.add_argument("--cwd", help="project whose config picks the models to preload")
    return serve(parser.parse_args(argv).cwd)


if __name__ == "__main__":
    raise SystemExit(main())
