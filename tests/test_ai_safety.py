"""AI safety tests: a misbehaving model must never get its way."""
import json

import pytest
from fastapi.testclient import TestClient

from app.ai.investigator import GuardrailViolation, validate_recommendation
from app.config import Settings
from app.main import create_app
from tests.conftest import MERCHANT, make_event


def good_output(**overrides) -> str:
    output = {
        "suspected_category": "GATEWAY_TIMEOUT",
        "recommended_action": "VERIFY_FINAL_STATUS",
        "summary": "Verify first",
        "evidence_document_ids": ["policy-timeouts-v2"],
        "uncertainties": [],
        "requires_human_review": False,
    }
    output.update(overrides)
    return json.dumps(output)


def test_human_review_is_forced_even_if_model_says_no():
    assert validate_recommendation(good_output(), {"policy-timeouts-v2"}).requires_human_review is True


@pytest.mark.parametrize("raw_output", [
    "not json at all",
    good_output(recommended_action="ISSUE_REFUND"),          # forbidden financial action
    good_output(evidence_document_ids=["made-up-policy"]),   # hallucinated citation
    good_output(execute_sql="DROP TABLE cases"),             # unexpected field
])
def test_bad_model_output_is_blocked(raw_output):
    with pytest.raises(GuardrailViolation):
        validate_recommendation(raw_output, {"policy-timeouts-v2"})


class RogueLLM:
    model_name = "rogue"

    def complete(self, system_prompt, context):
        return good_output(recommended_action="ISSUE_REFUND")


class BrokenLLM:
    model_name = "broken"

    def complete(self, system_prompt, context):
        raise TimeoutError("model provider unavailable")


@pytest.mark.parametrize("llm", [RogueLLM(), BrokenLLM()])
def test_unsafe_or_failed_model_sends_case_to_a_human(tmp_path, llm):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}", ai_enabled=True)
    with TestClient(create_app(settings, llm=llm)) as client:
        case = client.post("/v1/events", json=make_event(raw_code="V99"), headers=MERCHANT).json()
    assert case["status"] == "EXCEPTION_PENDING"
    assert case["recommendation"] is None
