"""Hook tests with a fake engine (no Presidio)."""

import io
import json

import hooks._common as common
from pii_scrub.config import Config
from pii_scrub.engine import Detection


class FakeEngine:
    """Flags the literal substring 'jean@acme.fr' as an EMAIL_ADDRESS."""

    def __init__(self, *_a, **_k):
        pass

    def detect(self, text, language=None):
        out = []
        idx = text.find("jean@acme.fr")
        if idx != -1:
            out.append(Detection("EMAIL_ADDRESS", idx, idx + 12, 0.99))
        return out


class BrokenEngine:
    def __init__(self, *_a, **_k):
        pass

    def detect(self, text, language=None):
        raise OSError("Can't find model 'en_core_web_lg'")


def _run(fn, event, monkeypatch, capsys, engine=FakeEngine, **config):
    monkeypatch.setattr(common, "ScrubEngine", engine)
    monkeypatch.setattr(common, "load_config", lambda: Config(**config))
    monkeypatch.setattr(common.sys, "stdin", io.StringIO(json.dumps(event)))
    fn()
    return capsys.readouterr().out


def test_pre_tool_use_flags_bash_pii(monkeypatch, capsys):
    out = _run(
        common.run_pre_tool_use,
        {"tool_name": "Bash", "tool_input": {"command": "echo jean@acme.fr"}},
        monkeypatch,
        capsys,
    )
    payload = json.loads(out)
    hso = payload["hookSpecificOutput"]
    assert hso["permissionDecision"] == "ask"
    assert "EMAIL_ADDRESS" in hso["permissionDecisionReason"]


def test_pre_tool_use_clean_is_silent(monkeypatch, capsys):
    out = _run(
        common.run_pre_tool_use,
        {"tool_name": "Bash", "tool_input": {"command": "echo hello"}},
        monkeypatch,
        capsys,
    )
    assert out.strip() == ""


def test_pre_tool_use_irrelevant_tool_silent(monkeypatch, capsys):
    out = _run(
        common.run_pre_tool_use,
        {"tool_name": "TodoWrite", "tool_input": {"todos": ["jean@acme.fr"]}},
        monkeypatch,
        capsys,
    )
    assert out.strip() == ""


def test_pre_tool_use_web_and_mcp_tools_scanned(monkeypatch, capsys):
    for tool, tool_input in [
        ("WebFetch", {"url": "https://x.test/?u=jean@acme.fr"}),
        ("mcp__crm__lookup", {"query": {"email": "jean@acme.fr"}}),
    ]:
        out = _run(common.run_pre_tool_use, {"tool_name": tool, "tool_input": tool_input},
                   monkeypatch, capsys)
        assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "ask", tool


def test_pre_tool_use_read_scans_file_content(tmp_path, monkeypatch, capsys):
    (tmp_path / "contacts.txt").write_text("line1\nmail: jean@acme.fr\n", encoding="utf-8")
    out = _run(
        common.run_pre_tool_use,
        {"tool_name": "Read", "cwd": str(tmp_path), "tool_input": {"file_path": "contacts.txt"}},
        monkeypatch,
        capsys,
    )
    hso = json.loads(out)["hookSpecificOutput"]
    assert hso["permissionDecision"] == "ask"
    assert "EMAIL_ADDRESS" in hso["permissionDecisionReason"]


def test_pre_tool_use_read_honours_offset_limit(tmp_path, monkeypatch, capsys):
    (tmp_path / "f.txt").write_text("clean\njean@acme.fr\n", encoding="utf-8")
    out = _run(
        common.run_pre_tool_use,
        {"tool_name": "Read", "tool_input": {"file_path": str(tmp_path / "f.txt"),
                                             "offset": 1, "limit": 1}},
        monkeypatch,
        capsys,
    )
    assert out.strip() == ""


def test_pre_tool_use_read_oversized_file_fails_closed(tmp_path, monkeypatch, capsys):
    big = tmp_path / "big.txt"
    big.write_text("x" * 100, encoding="utf-8")
    out = _run(
        common.run_pre_tool_use,
        {"tool_name": "Read", "tool_input": {"file_path": str(big)}},
        monkeypatch,
        capsys,
        hook_max_file_bytes=10,
    )
    hso = json.loads(out)["hookSpecificOutput"]
    assert hso["permissionDecision"] == "ask"
    assert "hook_max_file_bytes" in hso["permissionDecisionReason"]


def test_pre_tool_use_engine_error_fails_closed(monkeypatch, capsys):
    event = {"tool_name": "Bash", "tool_input": {"command": "echo hi"}}
    out = _run(common.run_pre_tool_use, event, monkeypatch, capsys,
               engine=BrokenEngine, hook_decision="deny")
    hso = json.loads(out)["hookSpecificOutput"]
    assert hso["permissionDecision"] == "deny"
    assert "could not check" in hso["permissionDecisionReason"]
    # explicit opt-out
    out = _run(common.run_pre_tool_use, event, monkeypatch, capsys,
               engine=BrokenEngine, hook_on_error="open")
    assert out.strip() == ""


def test_user_prompt_submit_blocks_with_scrubbed_version(monkeypatch, capsys):
    out = _run(
        common.run_user_prompt_submit,
        {"prompt": "mail jean@acme.fr please"},
        monkeypatch,
        capsys,
    )
    payload = json.loads(out)
    assert payload["decision"] == "block"
    assert "EMAIL_ADDRESS" in payload["reason"]
    assert "mail <EMAIL_ADDRESS_1> please" in payload["reason"]


def test_user_prompt_submit_warn_mode_sends(monkeypatch, capsys):
    out = _run(
        common.run_user_prompt_submit,
        {"prompt": "mail jean@acme.fr please"},
        monkeypatch,
        capsys,
        prompt_decision="warn",
    )
    payload = json.loads(out)
    assert "decision" not in payload
    assert "EMAIL_ADDRESS" in payload["systemMessage"]


def test_user_prompt_submit_engine_error_blocks(monkeypatch, capsys):
    out = _run(common.run_user_prompt_submit, {"prompt": "hello"}, monkeypatch, capsys,
               engine=BrokenEngine)
    payload = json.loads(out)
    assert payload["decision"] == "block"
    assert "could not check" in payload["reason"]


def test_pre_tool_use_system_exit_still_decides(monkeypatch, capsys):
    """spaCy's downloader calls sys.exit(); the hook must still print a decision."""

    class ExitingEngine(BrokenEngine):
        def detect(self, text, language=None):
            print("✘ No compatible package found")  # stdout chatter
            raise SystemExit(1)

    out = _run(common.run_pre_tool_use, {"tool_name": "Bash", "tool_input": {"command": "ls"}},
               monkeypatch, capsys, engine=ExitingEngine)
    payload = json.loads(out)  # stdout is pure JSON
    assert payload["hookSpecificOutput"]["permissionDecision"] == "ask"
