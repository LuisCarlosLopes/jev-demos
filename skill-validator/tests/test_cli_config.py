import json
from dataclasses import replace

import pytest
import yaml

from skill_validator.cli import main
from skill_validator.config import Settings
from skill_validator.policy import load_policy


def test_env_selects_provider_without_exposing_key(tmp_path, monkeypatch):
    monkeypatch.delenv("JEV_PROVIDER", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("JEV_PROVIDER=openrouter\nOPENROUTER_API_KEY=fake-key-from-file\n")
    settings = Settings.load(env_file)
    assert settings.provider == "openrouter"
    assert settings.model == "typesafe/jev-1.13"
    assert settings.api_key == "fake-key-from-file"
    assert settings.api_key not in repr(settings)
    assert settings.api_key not in repr(replace(settings, known_secrets=(settings.api_key,)))
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key-from-process")
    assert Settings.load(env_file).api_key == "fake-key-from-process"


def test_cli_writes_reports_without_api(skill, policy, tmp_path):
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(yaml.safe_dump(policy))
    json_path = tmp_path / "reports" / "result.json"
    markdown_path = tmp_path / "reports" / "result.md"
    code = main(
        [
            str(skill / "SKILL.md"),
            "--local-only",
            "--policy",
            str(policy_path),
            "--env-file",
            str(tmp_path / "absent.env"),
            "--json",
            str(json_path),
            "--markdown",
            str(markdown_path),
        ]
    )
    assert code == 0
    assert json.loads(json_path.read_text())["status"] == "local_only"
    assert "SOMENTE LOCAL" in markdown_path.read_text()


def test_cli_cannot_overwrite_input_skill(skill, policy, tmp_path):
    manifest = skill / "SKILL.md"
    before = manifest.read_bytes()
    with pytest.raises(SystemExit) as error:
        main([str(skill), "--local-only", "--json", str(manifest)])
    assert error.value.code == 2
    assert manifest.read_bytes() == before


@pytest.mark.parametrize(
    "change",
    [
        {"min_quality": 101},
        {"min_confidence": float("nan")},
        {"required_paths": ["../private"]},
        {"max_files": True},
        {"risk_review": 0.9, "risk_block": 0.8},
    ],
)
def test_policy_rejects_invalid_thresholds_and_paths(policy, tmp_path, change):
    policy.update(change)
    path = tmp_path / "policy.yaml"
    path.write_text(yaml.safe_dump(policy))
    with pytest.raises(ValueError):
        load_policy(path)
