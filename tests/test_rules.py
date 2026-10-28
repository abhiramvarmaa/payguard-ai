"""Unit tests: normalizer, rules engine and router, with no web server or database."""
from app.normalizer import UNKNOWN, normalize
from app.router import decide
from app.rules import Rule, find_applicable_rule
from app.schemas import Gateway, PaymentFailureEvent, Route
from tests.conftest import make_event


def test_normalizer_maps_each_gateway_and_keeps_unknown_codes_safe():
    assert normalize(Gateway.SIMULATOR_VISA, "V54") == "EXPIRED_CARD"
    assert normalize(Gateway.SIMULATOR_MASTERCARD, " m51 ") == "INSUFFICIENT_FUNDS"
    # A Visa code sent through the Mastercard adapter means nothing there.
    assert normalize(Gateway.SIMULATOR_MASTERCARD, "V54") == UNKNOWN


def test_exceeds_limit_is_handled_by_a_rule():
    decision = decide(PaymentFailureEvent(**make_event(raw_code="V61")), ai_enabled=True)
    assert (decision.route, decision.action) == (Route.DETERMINISTIC, "NOTIFY_MERCHANT")
    assert decision.rule_id == "rule-exceeds-limit"


def test_conflicting_top_priority_rules_are_not_picked_arbitrarily():
    rules = (
        Rule("a", 1, "EXPIRED_CARD", 10, "REQUEST_CARD_UPDATE", "x"),
        Rule("b", 1, "EXPIRED_CARD", 10, "NOTIFY_MERCHANT", "y"),
    )
    match = find_applicable_rule("EXPIRED_CARD", rules)
    assert match.conflict and match.rule is None


def test_lower_priority_number_wins():
    rules = (
        Rule("slow", 1, "EXPIRED_CARD", 50, "NOTIFY_MERCHANT", "x"),
        Rule("fast", 1, "EXPIRED_CARD", 10, "REQUEST_CARD_UPDATE", "y"),
    )
    assert find_applicable_rule("EXPIRED_CARD", rules).rule.rule_id == "fast"


def test_router_paths():
    known = decide(PaymentFailureEvent(**make_event()), ai_enabled=True)
    assert (known.route, known.action, known.rule_version) == (Route.DETERMINISTIC, "REQUEST_CARD_UPDATE", 3)

    risky = decide(PaymentFailureEvent(**make_event(risk_flag=True)), ai_enabled=True)
    assert risky.route == Route.EXCEPTION  # risk overrides a perfectly good rule

    unknown = decide(PaymentFailureEvent(**make_event(raw_code="V99")), ai_enabled=True)
    assert unknown.route == Route.AI_REVIEW

    ai_off = decide(PaymentFailureEvent(**make_event(raw_code="V99")), ai_enabled=False)
    assert ai_off.route == Route.EXCEPTION
