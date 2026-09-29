from unittest.mock import Mock

import pytest

from skill_validator.semantic import decide, parse_response
from skill_validator.validator import validate


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_answer",
        "missing_confidence",
        "wrong_type",
        "nan",
        "invalid_probability",
        "wrong_sum",
        "wrong_mean",
        "missing_risk",
        "invalid_risk",
        "missing_model",
    ],
)
def test_bad_responses_cannot_approve(mutation, skill, policy, settings, response):
    dimension = response["answers"]["trigger_precision"]
    if mutation == "missing_answer":
        del response["answers"]["trigger_precision"]
    elif mutation == "missing_confidence":
        del dimension["confidence"]
    elif mutation == "wrong_type":
        dimension["type"] = "choice"
    elif mutation == "nan":
        dimension["score"] = float("nan")
    elif mutation == "invalid_probability":
        dimension["probabilities"]["0"] = -1
    elif mutation == "wrong_sum":
        dimension["probabilities"]["0"] = 0.5
    elif mutation == "wrong_mean":
        dimension["score"] = 0
    elif mutation == "missing_risk":
        del response["answers"]["unauthorized_exfiltration"]
    elif mutation == "invalid_risk":
        response["answers"]["unauthorized_exfiltration"]["noul"] = True
    elif mutation == "missing_model":
        del response["model"]
    provider = Mock(evaluate=Mock(return_value=response))
    report = validate(skill, policy, settings, provider=provider)
    assert report.status == "error"
    assert report.quality_score is None


def test_low_confidence_requires_review(policy, response):
    response["answers"]["workflow_clarity"]["confidence"] = 0.2
    dimensions, risks, _, _ = parse_response(response, policy)
    status, _, quality = decide(dimensions, risks, policy)
    assert status == "review"
    assert quality == 100


def test_risk_not_compensated_by_perfect_quality(policy, response):
    response["answers"]["unauthorized_exfiltration"]["noul"] = 0.95
    dimensions, risks, _, _ = parse_response(response, policy)
    status, _, quality = decide(dimensions, risks, policy)
    assert status == "failed"
    assert quality == 100


def test_uncertain_risk_requires_review(policy, response):
    response["answers"]["instruction_override"]["noul"] = 0.5
    dimensions, risks, _, _ = parse_response(response, policy)
    assert decide(dimensions, risks, policy)[0] == "review"


def test_weights_and_thresholds_can_be_replayed(policy, response):
    answer = response["answers"]["trigger_precision"]
    answer["score"] = 0
    answer["probabilities"] = {"0": 1, "1": 0, "2": 0, "3": 0}
    dimensions, risks, _, _ = parse_response(response, policy)
    assert decide(dimensions, risks, policy)[2] == 70
    assert decide(dimensions, risks, policy)[0] == "failed"
    policy["min_quality"] = 65
    assert decide(dimensions, risks, policy)[0] == "passed"


def test_large_state_never_silently_truncated(skill, policy, settings):
    policy["max_state_chars"] = 10
    provider = Mock()
    report = validate(skill, policy, settings, provider=provider)
    assert report.status == "error"
    provider.evaluate.assert_not_called()
