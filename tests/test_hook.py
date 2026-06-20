"""Hook tests with a fake engine (no Presidio)."""

import io
import json

import hooks._common as common
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


def _run(fn, event, monkeypatch, capsys):
    monkeypatch.setattr(common, "ScrubEngine", FakeEngine)
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
        {"tool_name": "WebFetch", "tool_input": {"url": "jean@acme.fr"}},
        monkeypatch,
        capsys,
    )
    assert out.strip() == ""


def test_user_prompt_submit_flags_prompt(monkeypatch, capsys):
    out = _run(
        common.run_user_prompt_submit,
        {"prompt": "mail jean@acme.fr please"},
        monkeypatch,
        capsys,
    )
    payload = json.loads(out)
    assert "EMAIL_ADDRESS" in payload["hookSpecificOutput"]["additionalContext"]
