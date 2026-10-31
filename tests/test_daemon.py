"""Hook daemon over a real Unix socket and over loopback TCP, with a fake engine (no Presidio)."""

import json
import os
import shutil
import socket
import stat
import sys
import tempfile
import threading
from pathlib import Path

import pytest

from pii_scrub import daemon
from pii_scrub.engine import Detection

posix_only = pytest.mark.skipif(os.name != "posix", reason="file modes are POSIX")


class FakeEngine:
    def __init__(self, fail=False):
        self.fail = fail

    def prime(self, texts, language=None):
        pass

    def detect(self, text, language=None):
        if self.fail:
            raise RuntimeError("spaCy model(s) not installed: en_core_web_lg.")
        i = text.find("jean@acme.fr")
        return [] if i < 0 else [Detection("EMAIL_ADDRESS", i, i + 12, 1.0)]


@pytest.fixture(params=["unix", "tcp"])
def mode(request, monkeypatch):
    if request.param == "unix" and not daemon.UNIX:
        pytest.skip("needs Unix sockets")
    monkeypatch.setenv("PII_AIRLOCK_DAEMON_TRANSPORT", request.param)
    return request.param


@pytest.fixture
def runtime(mode, monkeypatch):
    # Short path: Unix socket paths are limited to ~104 bytes on macOS.
    base = tempfile.mkdtemp(prefix="pa-", dir="/tmp" if os.name == "posix" else None)
    monkeypatch.setenv("XDG_RUNTIME_DIR", base)
    yield daemon.runtime_dir()
    shutil.rmtree(base, ignore_errors=True)


@pytest.fixture
def running(runtime, monkeypatch):
    engine = FakeEngine()
    monkeypatch.setattr(daemon._Engines, "get", lambda self, config: engine)
    monkeypatch.setattr(daemon, "load_config", lambda cwd=None: daemon.Config())
    thread = threading.Thread(target=daemon.serve, daemon=True)
    thread.start()
    assert daemon.wait_until_up(5) is not None
    yield engine
    daemon.call({"op": "stop"})
    thread.join(5)


def test_detect_round_trip(running):
    assert daemon.detect("/proj", ["hi", "mail jean@acme.fr"]) == [
        [], [("EMAIL_ADDRESS", 5, 17, 1.0)]
    ]


@posix_only
def test_socket_or_info_file_and_dir_are_private(running, runtime):
    assert stat.S_IMODE(os.stat(daemon.endpoint()).st_mode) == 0o600
    assert not stat.S_IMODE(os.stat(runtime).st_mode) & 0o077


def test_detection_error_is_raised_for_fail_closed(running):
    running.fail = True
    with pytest.raises(daemon.DaemonError, match="not installed"):
        daemon.detect(None, ["text"])


def test_second_daemon_exits_at_once(running):
    assert daemon.serve() == 0
    assert daemon.call({"op": "ping"})["pid"] == os.getpid()


def test_older_code_is_not_trusted_and_stops(running, monkeypatch):
    monkeypatch.setattr(daemon, "build_id", lambda: "newer")
    assert daemon.detect(None, ["mail jean@acme.fr"]) is None
    monkeypatch.undo()


def test_no_daemon_means_none(runtime):
    assert daemon.detect(None, ["x"]) is None
    assert daemon.call({"op": "ping"}) is None


@posix_only
def test_socket_in_a_dir_others_can_write_is_not_used(running, runtime):
    os.chmod(runtime, 0o777)
    try:
        assert daemon.call({"op": "ping"}) is None
    finally:
        os.chmod(runtime, 0o700)


def test_older_client_is_refused_without_stopping_the_daemon(running, monkeypatch):
    real = daemon.build_id
    monkeypatch.setattr(daemon, "build_id", lambda: "0.0.1+1")
    assert daemon.detect(None, ["mail jean@acme.fr"]) is None
    monkeypatch.setattr(daemon, "build_id", real)
    assert daemon.call({"op": "ping"}) is not None        # still running
    assert daemon.detect(None, ["mail jean@acme.fr"]) is not None


def test_build_ordering():
    key = daemon._build_key
    assert key("0.3.0+5") > key("0.2.3+999") and key("0.3.0+6") > key("0.3.0+5")
    assert key("0.10.0+1") > key("0.9.0+1") and key("garbage") < key("0.0.1+0")


# --- loopback TCP (the Windows transport): authentication ---------------------


@pytest.fixture
def tcp(monkeypatch):
    monkeypatch.setenv("PII_AIRLOCK_DAEMON_TRANSPORT", "tcp")
    base = tempfile.mkdtemp(prefix="pa-")
    monkeypatch.setenv("XDG_RUNTIME_DIR", base)
    engine = FakeEngine()
    monkeypatch.setattr(daemon._Engines, "get", lambda self, config: engine)
    monkeypatch.setattr(daemon, "load_config", lambda cwd=None: daemon.Config())
    thread = threading.Thread(target=daemon.serve, daemon=True)
    thread.start()
    assert daemon.wait_until_up(5) is not None
    original = daemon.info_path().read_text()
    yield daemon.info_path()
    daemon.info_path().write_text(original)  # a test may have pointed it elsewhere
    daemon.call({"op": "stop"})
    thread.join(5)
    shutil.rmtree(base, ignore_errors=True)


def _raw(port, *lines):
    """Talk to the daemon without the client's handshake; the reply lines."""
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        for line in lines:
            sock.sendall(json.dumps(line).encode() + b"\n")
        sock.shutdown(socket.SHUT_WR)
        with sock.makefile("rb") as reply:
            return [json.loads(x) for x in reply]


def test_tcp_listens_on_loopback_only(tcp):
    info = json.loads(tcp.read_text())
    assert info["port"] > 0 and len(info["token"]) == 64
    assert daemon.detect("/p", ["mail jean@acme.fr"]) == [[("EMAIL_ADDRESS", 5, 17, 1.0)]]


def test_tcp_request_without_the_token_is_refused(tcp):
    port = json.loads(tcp.read_text())["port"]
    (reply,) = _raw(port, {"build": daemon.build_id(), "cwd": None, "texts": ["jean@acme.fr"]})
    assert reply["error"] == "unauthorized" and "detections" not in reply
    (reply,) = _raw(port, {"op": "stop", "token": "wrong"})
    assert reply["error"] == "unauthorized"
    assert daemon.call({"op": "ping"}) is not None  # still up


def test_tcp_server_proves_the_token_without_revealing_it(tcp):
    info = json.loads(tcp.read_text())
    (reply,) = _raw(info["port"], {"hello": "abc"})
    assert reply["proof"] == daemon._proof(info["token"], "abc", info["port"])
    assert reply["proof"] != daemon._proof(info["token"], "abc", info["port"] + 1)
    assert info["token"] not in json.dumps(reply)


def test_client_sends_no_text_to_a_port_squatter(tcp, monkeypatch):
    """A stale daemon.json pointing at someone else's listener must not get any text."""
    received: list[bytes] = []
    squatter = socket.socket()
    squatter.bind(("127.0.0.1", 0))
    squatter.listen(1)

    def serve_one():
        conn, _ = squatter.accept()
        with conn:
            conn.settimeout(2)
            try:
                received.append(conn.recv(65536))
                conn.sendall(b'{"proof": "not-the-proof"}\n')
                received.append(conn.recv(65536))  # would hold the request if it were sent
            except OSError:
                pass

    thread = threading.Thread(target=serve_one, daemon=True)
    thread.start()
    info = json.loads(tcp.read_text())
    tcp.write_text(json.dumps({**info, "port": squatter.getsockname()[1]}))
    assert daemon.detect("/p", ["mail jean@acme.fr"]) is None
    thread.join(5)
    squatter.close()
    assert b"jean@acme.fr" not in b"".join(received)


def test_a_relayed_proof_is_rejected(tcp):
    """A process on another port that forwards the hello to the real daemon (so it gets a
    valid proof for *that* port) must not pass as the daemon, nor see the request."""
    info = json.loads(tcp.read_text())
    seen: list[bytes] = []
    relay = socket.socket()
    relay.bind(("127.0.0.1", 0))
    relay.listen(1)

    def forward_hello():
        conn, _ = relay.accept()
        with conn, socket.create_connection(("127.0.0.1", info["port"]), timeout=5) as real:
            conn.settimeout(3)
            hello = conn.recv(65536)
            seen.append(hello)
            real.sendall(hello)
            conn.sendall(real.recv(65536))  # the real daemon's genuine proof
            try:
                seen.append(conn.recv(65536))  # the request, if the client were fooled
            except OSError:
                pass

    thread = threading.Thread(target=forward_hello, daemon=True)
    thread.start()
    tcp.write_text(json.dumps({**info, "port": relay.getsockname()[1]}))
    assert daemon.detect("/p", ["mail jean@acme.fr"]) is None
    thread.join(5)
    relay.close()
    assert b"jean@acme.fr" not in b"".join(seen) and info["token"].encode() not in b"".join(seen)


def test_tcp_info_file_with_garbage_means_no_daemon(tcp):
    tcp.write_text("not json")
    assert daemon.call({"op": "ping"}) is None


@pytest.mark.skipif(sys.platform == "win32", reason="spawns a real daemon process")
def test_spawn_detaches_a_real_daemon_process(tmp_path, monkeypatch):
    monkeypatch.setenv("PII_AIRLOCK_DAEMON_TRANSPORT", "tcp")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    # The daemon starts in the runtime dir: make the package importable from there.
    monkeypatch.setenv("PYTHONPATH", str(Path(daemon.__file__).resolve().parent.parent))
    daemon.spawn(str(tmp_path))
    reply = daemon.wait_until_up(30)
    try:
        assert reply is not None and reply["pid"] != os.getpid()
    finally:
        daemon.call({"op": "stop"})
