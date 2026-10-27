"""Three-way router. Decides DETERMINISTIC / AI_REVIEW / EXCEPTION before any model is called."""
from dataclasses import dataclass

from app.normalizer import normalize
from app.rules import find_applicable_rule
from app.schemas import PaymentFailureEvent, Route


@dataclass(frozen=True)
class Decision:
    route: Route
    category: str
    action: str
    reason: str
    rule_id: str | None = None
    rule_version: int | None = None


def decide(event: PaymentFailureEvent, ai_enabled: bool) -> Decision:
    category = normalize(event.gateway, event.raw_code)

    # 1. Safety gates come first: no rule or model may act on unsafe data.
    if not event.merchant_config_valid:
        return Decision(Route.EXCEPTION, category, "MANUAL_REVIEW", "Merchant configuration is invalid")
    if event.risk_flag:
        return Decision(Route.EXCEPTION, category, "RISK_REVIEW", "Risk flag set; automation not allowed")

    # 2. Rule coverage.
    match = find_applicable_rule(category)
    if match.conflict:
        return Decision(Route.EXCEPTION, category, "MANUAL_REVIEW", "Conflicting rules matched")
    if match.rule:
        rule = match.rule
        return Decision(Route.DETERMINISTIC, category, rule.action, rule.reason, rule.rule_id, rule.version)

    # 3. Valid but not covered by a rule: AI may help, if it is switched on.
    if ai_enabled:
        return Decision(Route.AI_REVIEW, category, "AI_INVESTIGATION", "No approved rule; eligible for AI review")
    return Decision(Route.EXCEPTION, category, "MANUAL_REVIEW", "No approved rule and AI review is disabled")
