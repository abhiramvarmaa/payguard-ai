"""API and integration tests: HTTP -> validation -> routing -> database -> response."""
from tests.conftest import ANALYST, MERCHANT, OTHER_MERCHANT, make_event


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_known_failure_is_handled_by_rules_without_ai(client):
    response = client.post("/v1/events", json=make_event(), headers=MERCHANT)
    assert response.status_code == 201
    body = response.json()
    assert body["route"] == "DETERMINISTIC"
    assert body["status"] == "RULE_COMPLETE"
    assert body["rule_id"] == "rule-expired-card"
    assert body["recommendation"] is None
    assert response.headers["X-Correlation-ID"]


def test_missing_field_and_extra_field_are_rejected(client):
    event = make_event()
    del event["merchant_id"]
    assert client.post("/v1/events", json=event, headers=MERCHANT).status_code == 422
    leaky = make_event(card_number="4111111111111111")
    assert client.post("/v1/events", json=leaky, headers=MERCHANT).status_code == 422


def test_auth_is_required_and_merchants_cannot_post_for_others(client):
    assert client.post("/v1/events", json=make_event()).status_code == 401
    assert client.post("/v1/events", json=make_event(), headers=OTHER_MERCHANT).status_code == 403


def test_duplicate_event_returns_same_case(client):
    first = client.post("/v1/events", json=make_event(), headers=MERCHANT)
    second = client.post("/v1/events", json=make_event(), headers=MERCHANT)
    assert second.status_code == 200
    assert second.json()["case_id"] == first.json()["case_id"]
    assert len(client.get("/v1/cases", headers=ANALYST).json()) == 1


def test_reused_event_id_with_different_payload_conflicts(client):
    client.post("/v1/events", json=make_event(), headers=MERCHANT)
    changed = make_event(raw_code="V51")
    assert client.post("/v1/events", json=changed, headers=MERCHANT).status_code == 409


def test_timeout_goes_to_ai_then_human_approves(client):
    event = make_event(event_id="evt-3001", transaction_id="txn-3001", raw_code="V91")
    case = client.post("/v1/events", json=event, headers=MERCHANT).json()
    assert case["route"] == "AI_REVIEW"
    assert case["status"] == "REVIEW_PENDING"
    assert case["recommendation"]["recommended_action"] == "VERIFY_FINAL_STATUS"
    assert case["recommendation"]["evidence_document_ids"] == ["policy-timeouts-v2"]

    # A merchant can't approve its own case.
    review = {"reason": "Checked with processor"}
    url = f"/v1/cases/{case['case_id']}/approve"
    assert client.post(url, json=review, headers=MERCHANT).status_code == 403

    approved = client.post(url, json=review, headers=ANALYST)
    assert approved.json()["status"] == "APPROVED"
    # Approving twice is an invalid state transition.
    assert client.post(url, json=review, headers=ANALYST).status_code == 409

    detail = client.get(f"/v1/cases/{case['case_id']}", headers=ANALYST).json()
    assert [a["event_type"] for a in detail["audit_trail"]] == [
        "CASE_CREATED", "STATUS_AI_PENDING_TO_REVIEW_PENDING", "STATUS_REVIEW_PENDING_TO_APPROVED"]
    tools = [step["tool"] for step in detail["ai_runs"][0]["steps"]]
    assert tools == ["get_transaction_status", "search_policy", "llm.complete", "validate_recommendation"]


def test_risk_flag_goes_to_exception_and_can_be_resolved(client):
    case = client.post("/v1/events", json=make_event(risk_flag=True), headers=MERCHANT).json()
    assert (case["route"], case["status"]) == ("EXCEPTION", "EXCEPTION_PENDING")
    resolved = client.post(f"/v1/cases/{case['case_id']}/resolve",
                           json={"reason": "Risk team cleared it"}, headers=ANALYST)
    assert resolved.json()["status"] == "RESOLVED"


def test_merchants_only_see_their_own_cases(client):
    case = client.post("/v1/events", json=make_event(), headers=MERCHANT).json()
    assert client.get(f"/v1/cases/{case['case_id']}", headers=OTHER_MERCHANT).status_code == 404
    assert client.get("/v1/cases", headers=OTHER_MERCHANT).json() == []
    assert len(client.get("/v1/cases", headers=MERCHANT).json()) == 1
