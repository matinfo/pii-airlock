"""Project policy in SKILL.md: parsing, editing, config layering, engine rules."""

import pytest

from pii_scrub import policy
from pii_scrub.config import Config, load_config
from pii_scrub.engine import Detection, ScrubEngine
from pii_scrub.mapping import Mapping


def _isolate_user(monkeypatch, tmp_path):
    monkeypatch.setattr(policy.Path, "home", lambda: tmp_path / "home")
    import pii_scrub.config as config

    monkeypatch.setattr(config, "_USER_FILE", tmp_path / "home" / "none.yaml")


def test_init_writes_skill_with_frontmatter_and_empty_policy(tmp_path):
    path = policy.skill_path("project", tmp_path)
    assert policy.init_skill(path)
    text = path.read_text()
    assert text.startswith("---\nname: pii-airlock\n")
    assert "```yaml pii-airlock" in text
    assert policy.read_policy(path) == {"allow_list": [], "deny_list": {}}
    assert not policy.init_skill(path)  # never overwrites without force


def test_allow_and_deny_edit_only_the_policy_block(tmp_path):
    path = policy.skill_path("project", tmp_path)
    policy.init_skill(path)
    path.write_text(path.read_text() + "\nCustom note kept.\n")
    assert policy.add_allow(path, "Acme SA")
    assert not policy.add_allow(path, "acme sa")  # case-insensitive duplicate
    assert policy.add_deny(path, "Projet Phoenix")
    assert policy.add_deny(path, "Globex", entity="client")
    data = policy.read_policy(path)
    assert data["allow_list"] == ["Acme SA"]
    assert data["deny_list"] == {"CONFIDENTIAL": ["Projet Phoenix"], "CLIENT": ["Globex"]}
    assert "Custom note kept." in path.read_text()
    assert "## Rules for Claude" in path.read_text()


def test_invalid_policy_block_raises_clear_error(tmp_path):
    path = tmp_path / "SKILL.md"
    path.write_text("```yaml pii-airlock\n- just\n- a list\n```\n")
    with pytest.raises(policy.PolicyError, match="must be a YAML mapping"):
        policy.read_policy(path)


def test_load_config_layers_user_and_project_skills(tmp_path, monkeypatch):
    _isolate_user(monkeypatch, tmp_path)
    user = policy.skill_path("user")
    policy.add_allow(user, "Mathieu Meylan")
    project = tmp_path / "proj"
    p = policy.skill_path("project", project)
    policy.add_allow(p, "Acme SA")
    policy.add_deny(p, "Phoenix")
    p.write_text(p.read_text().replace("deny_list:", "prompt_decision: warn\ndeny_list:"))

    cfg = load_config(cwd=project)
    assert cfg.allow_list == ["Mathieu Meylan", "Acme SA"]  # accumulated
    assert cfg.deny_list == {"CONFIDENTIAL": ["Phoenix"]}
    assert cfg.prompt_decision == "warn"


def test_deny_list_plain_list_normalized():
    cfg = Config().merged_with({"deny_list": ["Phoenix"]}).merged_with(
        {"deny_list": {"client": ["Globex", "phoenix"]}})
    assert cfg.deny_list == {"CONFIDENTIAL": ["Phoenix"], "CLIENT": ["Globex", "phoenix"]}


def _engine(model_detections, **config):
    eng = ScrubEngine(Config(**config))
    eng._analyze = lambda text, language=None: model_detections  # type: ignore[method-assign]
    return eng


def test_allow_list_drops_model_detections_inside_term():
    text = "Ask Acme SA about Jean"
    eng = _engine([Detection("ORGANIZATION", 4, 8, 0.9), Detection("PERSON", 18, 22, 0.9)],
                  allow_list=["acme sa"])
    assert [d.entity_type for d in eng.detect(text)] == ["PERSON"]


def test_deny_list_and_custom_patterns_always_detected():
    text = "Project phoenix, contract CT-123456; phoenixes are birds"
    eng = _engine([], deny_list={"CONFIDENTIAL": ["Phoenix"]},
                  custom_patterns=[{"entity": "contract_id", "regex": r"CT-\d{6}"}])
    found = {(d.entity_type, d.text(text)) for d in eng.detect(text)}
    assert found == {("CONFIDENTIAL", "phoenix"), ("CONTRACT_ID", "CT-123456")}
    scrubbed = eng.scrub(text, Mapping())
    assert scrubbed.startswith("Project <CONFIDENTIAL_1>, contract <CONTRACT_ID_1>")


def test_invalid_custom_pattern_message():
    eng = _engine([], custom_patterns=[{"entity": "X", "regex": "("}])
    with pytest.raises(ValueError, match="custom_patterns"):
        eng.detect("anything")
