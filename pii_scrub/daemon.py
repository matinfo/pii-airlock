"""Hook daemon: keeps Presidio and the spaCy models loaded between hook calls.

Claude Code starts a new process for every hook call, and loading the models
costs 0.5-3 s each time: on every Bash, Read or Edit. The daemon loads them
once and answers detection requests over a local socket, so a hook call costs
the analysis itself plus a few milliseconds.

Two transports: a Unix socket where available (POSIX), else loopback TCP
(Windows). The TCP one has no file permissions to lean on, so the daemon makes a
secret token (kept in a file only the user can read) and both sides prove they know
it: the client checks the server's proof *before* it sends any text, so a process
that grabbed a stale port never sees a request.

Protocol: one JSON object per line, each way.
    -> {"build": id, "cwd": "/project", "texts": ["...", ...]}
    <- {"build": id, "detections": [[[entity, start, end, score], ...], ...]}
    <- {"build": id, "error": "message"}
    -> {"op": "ping"} / {"op": "stop"}
    -> {"hello": nonce} <- {"proof": hmac(token, nonce)}      (TCP only; requests then
       carry "token")
The config of `cwd` is loaded for every request, so policy edits apply at once;
projects that use the same models share one loaded engine and its cache.

Security: the socket (mode 0600) lives in a directory only the user can write
to, and clients check that before connecting, so another local user can
neither read the requests nor impersonate the daemon. Nothing leaves the
machine.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
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

UNIX = os.name == "posix" and hasattr(socket, "AF_UNIX")
_LOOPBACK = "127.0.0.1"

_CONNECT_TIMEOUT = 0.5
# Long enough for a cold model load plus a 2 MB file; a dead daemon fails fast.
_REPLY_TIMEOUT = 120.0


def runtime_dir() -> Path:
    """``$XDG_RUNTIME_DIR/pii-airlock`` if set, else the user state dir."""
    base = os.environ.get("XDG_RUNTIME_DIR")
    return Path(base) / "pii-airlock" if base else default_state_dir()


def transport() -> str:
    """``unix`` where Unix sockets exist, else ``tcp``; env ``PII_AIRLOCK_DAEMON_TRANSPORT=tcp``
    forces TCP (tests, or a filesystem without socket support)."""
    forced = os.environ.get("PII_AIRLOCK_DAEMON_TRANSPORT")
    return "tcp" if forced == "tcp" or not UNIX else "unix"


def socket_path() -> Path:
    return runtime_dir() / "hook.sock"


def info_path() -> Path:
    """Where a TCP daemon publishes its port and secret (private to the user)."""
    return runtime_dir() / "daemon.json"


def endpoint() -> str:
    return str(socket_path()) if transport() == "unix" else str(info_path())


def log_path() -> Path:
    return runtime_dir() / "daemon.log"


def build_id() -> str:
    """Version plus source mtime: a daemon running older code must not answer."""
    package = Path(__file__).resolve().parent
    newest = max((p.stat().st_mtime_ns for p in package.rglob("*.py")), default=0)
    return f"{__version__}+{newest}"


def _build_key(build: object) -> tuple:
    """Orderable form of a build id ("0.3.0+<mtime>"); unparsable sorts oldest."""
    try:
        version, _, mtime = str(build).partition("+")
        return (tuple(int(p) for p in version.split(".")), int(mtime or 0))
    except ValueError:
        return ((), 0)


def _is_private(path: Path, kind: int) -> bool:
    """`path` exists with file type `kind`, is ours, and no one else can write it.

    On Windows there are no such mode bits: the user profile's ACLs keep the
    state directory private, and the TCP token does the rest.
    """
    try:
        st = path.lstat()
    except OSError:
        return False
    if stat.S_IFMT(st.st_mode) != kind:
        return False
    if os.name != "posix":
        return True
    return st.st_uid == os.getuid() and not st.st_mode & (stat.S_IWGRP | stat.S_IWOTH)


# --- client ------------------------------------------------------------------


class DaemonError(RuntimeError):
    """The daemon ran the request and detection failed (e.g. model missing)."""


def call(message: dict, timeout: float = _REPLY_TIMEOUT) -> dict | None:
    """Send one request; the reply, or None if no trusted daemon is reachable."""
    try:
        if transport() == "unix":
            return _call_unix(message, timeout)
        return _call_tcp(message, timeout)
    except (OSError, ValueError):
        return None


def _exchange(sock: socket.socket, message: dict) -> dict:
    sock.sendall(json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n")
    with sock.makefile("rb") as reply:
        return json.loads(reply.readline())


def _call_unix(message: dict, timeout: float) -> dict | None:
    path = socket_path()
    if not (_is_private(path.parent, stat.S_IFDIR) and _is_private(path, stat.S_IFSOCK)):
        return None
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(_CONNECT_TIMEOUT)
        sock.connect(str(path))
        sock.settimeout(timeout)
        return _exchange(sock, message)


def _proof(token: str, nonce: str) -> str:
    return hmac.new(token.encode(), nonce.encode(), "sha256").hexdigest()


def _read_info() -> dict | None:
    path = info_path()
    if not (_is_private(path.parent, stat.S_IFDIR) and _is_private(path, stat.S_IFREG)):
        return None
    info = json.loads(path.read_text(encoding="utf-8"))
    if not (isinstance(info.get("port"), int) and isinstance(info.get("token"), str)):
        return None
    return info


def _call_tcp(message: dict, timeout: float) -> dict | None:
    info = _read_info()
    if info is None:
        return None
    with socket.create_connection((_LOOPBACK, info["port"]), timeout=_CONNECT_TIMEOUT) as sock:
        sock.settimeout(timeout)
        # Whoever listens on that port must prove it holds the token before it gets text.
        nonce = secrets.token_hex(16)
        with sock.makefile("rwb") as stream:
            stream.write(json.dumps({"hello": nonce}).encode() + b"\n")
            stream.flush()
            proof = json.loads(stream.readline()).get("proof", "")
            if not hmac.compare_digest(str(proof), _proof(info["token"], nonce)):
                return None
            stream.write(json.dumps({**message, "token": info["token"]},
                                    ensure_ascii=False).encode("utf-8") + b"\n")
            stream.flush()
            return json.loads(stream.readline())


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
    """Start a daemon in the background and return at once.

    If one is already running (or starting), the new process exits right away.
    """
    directory = runtime_dir()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "pii_scrub.daemon"]
    if cwd:
        cmd += ["--cwd", cwd]
    detach: dict = (
        {"start_new_session": True} if os.name == "posix"
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW: survives the hook
        # that started it and never opens a console window.
        else {"creationflags": 0x00000008 | 0x00000200 | 0x08000000}
    )
    with open(log_path(), "ab") as log:
        subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            close_fds=True, cwd=str(directory), **detach,
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
               config.ner_backend, config.gliner_model, config.analysis_cache_size)
        with self._lock:  # one model load at a time, never twice
            base = self._base.get(key)
            if base is None:
                base = ScrubEngine(config)
                base.load()
                self._base[key] = base
        return base.with_config(config)


class _Handler(socketserver.StreamRequestHandler):
    server: _Core

    def handle(self) -> None:
        self.server.last_used = time.monotonic()
        for line in self.rfile:  # one request per line; a TCP client sends hello first
            try:
                reply = self.server.dispatch(json.loads(line))
            # SystemExit included: spaCy's model downloader calls sys.exit().
            except (Exception, SystemExit) as exc:
                reply = {"error": str(exc) or type(exc).__name__}
            reply["build"] = self.server.build
            self.wfile.write(json.dumps(reply, ensure_ascii=False).encode("utf-8") + b"\n")
            self.wfile.flush()
        self.server.last_used = time.monotonic()


class _Core:
    """What both transports share: the loaded engines and the request handling."""

    token: str | None = None  # set for TCP: every request must carry it

    def _init_core(self) -> None:
        self.build = build_id()
        self.engines = _Engines()
        self.last_used = time.monotonic()

    def stop(self) -> None:
        threading.Thread(target=self.shutdown, daemon=True).start()

    def dispatch(self, request: dict) -> dict:
        if self.token is not None:
            if "hello" in request:  # prove we hold the token, without sending it
                return {"proof": _proof(self.token, str(request["hello"]))}
            if not hmac.compare_digest(str(request.get("token", "")), self.token):
                return {"error": "unauthorized"}
        return self.answer(request)

    def answer(self, request: dict) -> dict:
        op = request.get("op")
        if op == "ping":
            return {"pid": os.getpid()}
        if op == "stop":
            self.stop()
            return {"stopping": True}
        if request.get("build") != self.build:
            # A newer client means the package was upgraded: step aside for a fresh
            # daemon. An older one (another install) is just refused, so two
            # installs never kill each other's daemon in turn.
            if _build_key(request.get("build")) > _build_key(self.build):
                self.stop()
                return {"error": "pii-airlock daemon is running older code; restarting"}
            return {"error": "pii-airlock daemon is running newer code; analyzing in-process"}
        texts = [t for t in request.get("texts", []) if isinstance(t, str)]
        engine = self.engines.get(load_config(cwd=request.get("cwd") or None))
        engine.prime(texts)
        return {"detections": [
            [[d.entity_type, d.start, d.end, d.score] for d in engine.detect(t)]
            for t in texts
        ]}


class _TcpServer(_Core, socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True

    def __init__(self, token: str) -> None:
        super().__init__((_LOOPBACK, 0), _Handler)  # loopback only, any free port
        self.token = token
        self._init_core()


if UNIX:  # socketserver.UnixStreamServer does not exist on Windows

    class _UnixServer(_Core, socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
        daemon_threads = True

        def __init__(self, path: str) -> None:
            super().__init__(path, _Handler)
            self._init_core()


def _lock(handle) -> bool:
    """Take the single-instance lock on an open file; False if another daemon holds it."""
    if os.name == "posix":
        import fcntl

        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True
    import msvcrt

    try:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        return False
    return True


def _publish(port: int, token: str) -> None:
    """Write the port and token where clients look, readable by the user only."""
    path = info_path()
    tmp = path.with_name(f".{path.name}.{os.getpid()}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"port": port, "token": token, "pid": os.getpid()}, fh)
    os.replace(tmp, path)


def serve(cwd: str | None = None) -> int:
    """Run the daemon in the foreground until stopped or idle (see config)."""
    directory = runtime_dir()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name == "posix" and not _is_private(directory, stat.S_IFDIR):
        print(f"refusing to serve: {directory} is writable by other users", file=sys.stderr)
        return 1
    lock = open(directory / "hook.lock", "a+")  # held (and locked) for our lifetime
    if not _lock(lock):
        return 0  # another daemon is running or starting
    config = load_config(cwd=cwd)
    path = socket_path() if transport() == "unix" else info_path()
    path.unlink(missing_ok=True)  # stale: its owner no longer holds the lock
    if transport() == "unix":
        old_umask = os.umask(0o177)
        try:
            server: _Core = _UnixServer(str(path))
        finally:
            os.umask(old_umask)
    else:
        server = _TcpServer(secrets.token_hex(32))
        _publish(server.server_address[1], server.token)
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


def _preload(server: _Core, config: Config) -> None:
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
