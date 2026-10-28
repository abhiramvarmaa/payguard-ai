"""Rules engine: pure functions over versioned rule data. No network calls, no side effects."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    rule_id: str
    version: int
    category: str
    priority: int  # lower number wins
    action: str
    reason: str


RULES: tuple[Rule, ...] = (
    Rule("rule-insufficient-funds", 1, "INSUFFICIENT_FUNDS", 10,
         "NOTIFY_MERCHANT", "Ask the customer to use another payment method"),
    Rule("rule-expired-card", 3, "EXPIRED_CARD", 20,
         "REQUEST_CARD_UPDATE", "Request updated card information"),
    Rule("rule-exceeds-limit", 1, "EXCEEDS_LIMIT", 30,
         "NOTIFY_MERCHANT", "Amount exceeds the card limit; ask the customer for another method"),
)


@dataclass(frozen=True)
class RuleMatch:
    rule: Rule | None
    conflict: bool


def find_applicable_rule(category: str, rules: tuple[Rule, ...] = RULES) -> RuleMatch:
    matches = sorted((r for r in rules if r.category == category), key=lambda r: r.priority)
    if not matches:
        return RuleMatch(rule=None, conflict=False)
    best = [r for r in matches if r.priority == matches[0].priority]
    # Two top-priority rules that disagree: never pick one arbitrarily.
    if len({r.action for r in best}) > 1:
        return RuleMatch(rule=None, conflict=True)
    return RuleMatch(rule=best[0], conflict=False)
