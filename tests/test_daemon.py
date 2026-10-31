"""Hook daemon over a real Unix socket, with a fake engine (no Presidio)."""

import os
import shutil
import stat
import tempfile
import threading

import pytest

from pii_scrub import daemon
from pii_scrub.engine import Detection

pytestmark = pytest.mark.skipif(not daemon.SUPPORTED, reason="needs Unix sockets")


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


@pytest.fixture
def runtime(monkeypatch):
    # Short path: Unix socket paths are limited to ~104 bytes on macOS.
    base = tempfile.mkdtemp(prefix="pa-", dir="/tmp")
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


def test_socket_and_dir_are_private(running, runtime):
    assert stat.S_IMODE(os.stat(daemon.socket_path()).st_mode) == 0o600
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
