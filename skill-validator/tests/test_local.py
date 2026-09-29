import json
from unittest.mock import Mock

import pytest

from skill_validator.local import inspect_skill
from skill_validator.reporting import markdown
from skill_validator.validator import validate


def rules(snapshot):
    return {finding.rule for finding in snapshot.findings}


def test_minimal_skill_needs_no_optional_directories(skill, policy):
    assert inspect_skill(skill, policy).findings == []


@pytest.mark.parametrize(
    "text, rule",
    [
        ("# Missing metadata\n", "frontmatter.missing"),
        ("---\nname: example-skill\n", "frontmatter.unclosed"),
        ("---\n- item\n---\nBody", "frontmatter.mapping"),
        ("---\nname: first\nname: example-skill\n---\nBody", "frontmatter.yaml"),
        ("---\nname: example-skill\ndescription: 123\n---\nBody", "frontmatter.description"),
        ("---\nname: Other\ndescription: Valid\n---\nBody", "frontmatter.name"),
        ("---\nname: different\ndescription: Valid\n---\nBody", "frontmatter.name_directory"),
        ("---\nname: example-skill\ndescription: Valid\n---\n", "body.empty"),
        (
            "---\nname: example-skill\ndescription: &a Valid\nlicense: *a\n---\nBody",
            "frontmatter.yaml",
        ),
    ],
)
def test_bad_manifest_is_actionable(skill, policy, text, rule):
    (skill / "SKILL.md").write_text(text, encoding="utf-8")
    assert rule in rules(inspect_skill(skill, policy))


def test_missing_and_escaping_references(skill, policy):
    with (skill / "SKILL.md").open("a") as file:
        file.write("[missing](references/missing.md)\n[outside](../outside.md)\n")
    assert {"reference.missing", "reference.outside"} <= rules(inspect_skill(skill, policy))


def test_missing_link_reported_once(skill, policy):
    with (skill / "SKILL.md").open("a") as file:
        file.write("[missing](references/missing.md)\n")
    snapshot = inspect_skill(skill, policy)
    assert sum(f.rule == "reference.missing" for f in snapshot.findings) == 1


def test_markdown_image_reference_is_checked(skill, policy):
    with (skill / "SKILL.md").open("a") as file:
        file.write("![image](image.png)\n")
    assert "reference.missing" in rules(inspect_skill(skill, policy))


def test_malformed_url_is_finding_not_crash(skill, policy):
    with (skill / "SKILL.md").open("a") as file:
        file.write("[invalid](https://[invalid)\n")
    assert "reference.invalid" in rules(inspect_skill(skill, policy))


def test_nested_reference_uses_document_directory(skill, policy):
    references = skill / "references"
    references.mkdir()
    (references / "first.md").write_text("[second](second.md)")
    (references / "second.md").write_text("Details")
    assert "reference.missing" not in rules(inspect_skill(skill, policy))


def test_custom_required_directory(skill, policy):
    policy["required_paths"] = ["scripts"]
    assert "structure.required_path" in rules(inspect_skill(skill, policy))


def test_symlink_never_reads_external_secret(skill, policy, tmp_path):
    external = tmp_path / "private.txt"
    external.write_text("EXTERNAL CONTENT")
    (skill / "linked.txt").symlink_to(external)
    snapshot = inspect_skill(skill, policy)
    assert "scan.symlink" in rules(snapshot)
    assert "linked.txt" not in snapshot.files


@pytest.mark.parametrize("limit", ["max_files", "max_file_bytes", "max_total_bytes"])
def test_partial_scans_block_network(skill, policy, settings, limit):
    policy[limit] = 1
    (skill / "other.txt").write_text("hello")
    provider = Mock()
    report = validate(skill, policy, settings, provider=provider)
    assert report.status == "failed"
    assert report.semantic_status == "skipped"
    provider.evaluate.assert_not_called()


@pytest.mark.parametrize("where", ["SKILL.md", ".env", "references/private.txt"])
def test_secret_never_reaches_network_or_reports(skill, policy, settings, where):
    # Valor sintético gerado somente em diretório temporário.
    secret = "sk-or-v1-" + "aB7cD8eF9" * 5
    path = skill / where
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as file:
        file.write(f"\nOPENROUTER_API_KEY={secret}\n")
    provider = Mock()
    report = validate(skill, policy, settings, provider=provider)
    assert report.status == "failed"
    assert any(f.rule.startswith("secret.") for f in report.findings)
    provider.evaluate.assert_not_called()
    assert secret not in json.dumps(report.to_dict())
    assert secret not in markdown(report)


def test_configured_key_detected_without_known_prefix(skill, policy):
    from skill_validator.config import Settings

    secret = "customcredentialvalue"
    settings = Settings("typesafe", secret, "jev-latest", 10, (secret,))
    (skill / "example.txt").write_text(secret)
    report = validate(skill, policy, settings)
    assert any(f.rule == "secret.configured_api_key" for f in report.findings)


def test_binary_scanned_but_not_sent(skill, policy):
    key = ("AKIA" + "A" * 16).encode()
    (skill / "asset.bin").write_bytes(b"\xff\x00" + key)
    snapshot = inspect_skill(skill, policy)
    assert "secret.aws_access_key" in rules(snapshot)
    assert "asset.bin" not in snapshot.files


def test_common_placeholders_not_reported_as_credentials(skill, policy):
    (skill / ".env.example").write_text("API_KEY=${API_KEY}\nTOKEN=<your-token>\nSECRET=\n")
    assert not any(f.rule.startswith("secret.") for f in inspect_skill(skill, policy).findings)


def test_local_only_never_claims_semantic_approval(skill, policy, settings):
    provider = Mock()
    report = validate(skill, policy, settings, local_only=True, provider=provider)
    assert report.status == "local_only"
    assert report.quality_score is None
    assert report.semantic_status == "skipped"
    provider.evaluate.assert_not_called()
