# Explaining PayGuard AI in a Technical Interview

How to walk an interviewer through this project, with answers tied to the actual code. For a line-by-line explanation of every file, see [LEARNING_GUIDE.md](LEARNING_GUIDE.md).

PayGuard AI is a portfolio project. All data is synthetic, the gateway codes are invented for the simulator, and nothing touches a real payment network.

---

## 1. The 60-second version

> "PayGuard AI is a payment-failure triage service. Merchants send a failed-payment event to `POST /v1/events`. Pydantic validates it, it's deduplicated by `event_id`, and a gateway adapter turns the provider's raw code into an internal category. A deterministic router then picks one of three paths: known, safe cases follow an approved rule; valid but uncovered cases get an AI investigation that a human must approve; risky or invalid cases go straight to a person. Every step is saved with an audit trail, and the merchant gets a webhook when the case is final. It has 33 tests and CI on GitHub."

---

## 2. Core questions

**How do you decide between simple and complex failures?**
> "A deterministic router runs before any LLM call. Safety gates first: an invalid merchant config or a risk flag goes to EXCEPTION. Then rule coverage: one matching approved rule means DETERMINISTIC; conflicting rules mean EXCEPTION. No rule and AI enabled means AI_REVIEW; otherwise EXCEPTION."

Code: `decide()` in [`app/router.py`](../app/router.py). Schema validation happens earlier, at the API boundary (a missing field returns 422).

**If it's simple, why not let an agent decide?**
> "For simple cases there's no agent and no human: the rule decides. Rules are cheaper, faster, testable and auditable. An LLM adds cost, latency and hallucination risk, so it's used only where context is genuinely needed, and consequential actions need an accountable approver."

**How is the rules engine built?**
> "Rules are data: id, version, category, priority, action. The evaluator is a pure function: it filters by category, sorts by priority, and flags a conflict when two top-priority rules disagree instead of picking one. It returns a decision with the rule id and version and has no side effects."

Code: [`app/rules.py`](../app/rules.py), tests in [`tests/test_rules.py`](../tests/test_rules.py).

**Do you send anything back to Visa or Mastercard?**
> "No. PayGuard works after the gateway has returned its result; it never authorizes. What differs per gateway is the code vocabulary, so each gateway has its own mapping. The raw code is stored next to the normalized category for audit."

Code: [`app/normalizer.py`](../app/normalizer.py).

**Is the rules engine a separate service?**
> "Not yet: it's an internal module, because it's small with no independent scaling need. The API handles auth and validation, an orchestrator persists the decision and triggers next steps, and the rules module just returns a decision. I'd split it out for independent scaling, ownership or deployment."

**How does the merchant find out?**
> "They can poll `GET /v1/cases/{id}`. And when a case reaches a final status, a notification is written to an outbox in the same transaction; a worker delivers it as a webhook with an `Idempotency-Key`. Failures retry with exponential backoff, and after five failures the message goes to a dead-letter queue."

Code: [`app/notifier.py`](../app/notifier.py), [`app/worker.py`](../app/worker.py).

**How do you make AI output reliable?**
> "I don't trust the model's own confidence. The output must match a strict schema, the action must be on an allowlist (no refunds or retries), every cited policy must be one we actually retrieved, and human review is forced on in code. If any check fails, or the model is down, the case goes to a person."

Code: `validate_recommendation()` in [`app/ai/investigator.py`](../app/ai/investigator.py), tests in [`tests/test_ai_safety.py`](../tests/test_ai_safety.py).

**Is a confidence score enough?**
> "No. A model saying '95%' isn't a calibrated probability. Judge it on schema validity, groundedness against retrieved evidence, policy consistency, risk tier and results on a labelled evaluation set."

**How is an LLM application different from traditional software?**
> "Traditional code follows explicit control flow. LLM output is probabilistic and varies across runs, prompts and model versions. So on top of normal tests, CI and security, you add evaluation sets, guardrails, human gates, and monitoring of tokens, cost, trajectories and drift. It extends software engineering; it doesn't replace it."

**What is an agent trajectory?**
> "The sequence of tool calls, observations and final output. Each AI run stores its steps, model, prompt version, tokens and latency in the `ai_runs` table. You check it chose the right tools in the right order, stayed in budget and stopped safely."

---

## 3. Quick follow-ups

| Question | Short answer | Code |
|---|---|---|
| Which fields are validated? | IDs by pattern, gateway as an enum, raw_code 1–16 chars; unknown fields rejected | `app/schemas.py` |
| Same event twice? | Same body: original case (200). Different body: 409. Races caught by the primary key | `app/service.py` |
| Duplicate charge after a timeout? | No rule for timeouts; verify the authoritative status first; policy forbids a blind retry | `app/ai/policies.py` |
| Why persist before the AI call? | A crash or model outage can't lose the event | `app/service.py` |
| LLM down? | Run logged as FAILED, case goes to EXCEPTION_PENDING | `tests/test_ai_safety.py` |
| Hallucinated citations? | Cited ids must be a subset of the retrieved ids | `validate_recommendation()` |
| Prompt injection? | Enforced in code (allowlist, schema, human gate), not by trusting the prompt | `app/ai/investigator.py` |
| 401 vs 403? | 401: unknown caller. 403: known caller, not allowed | `app/auth.py` |
| Why 404 for another merchant's case? | So case IDs can't be discovered | `app/main.py` |
| Webhook delivered twice? | At-least-once by design; the Idempotency-Key lets merchants ignore repeats | `app/notifier.py` |
| Why not retry a 400? | 4xx means our request is wrong; dead-letter it. Retry 5xx, timeouts and 429 | `deliver_due()` |
| Deployment? | Planned: ECR, ECS Fargate (API + worker), RDS PostgreSQL, SQS, Secrets Manager, Terraform | `Dockerfile` |

Always say "built" or "planned" clearly.

---

## 4. Payments vocabulary

| Term | Meaning | PayGuard's scope |
|---|---|---|
| Authorization | The issuer approves or declines a payment attempt | Before PayGuard |
| Decline | The issuer said no | Main input |
| Technical failure | No clear answer; money may or may not have moved | AI review: verify status first |
| Capture / settlement | The merchant claims funds / funds move between banks | Out of scope |
| Refund | Merchant returns money by choice | Forbidden to the AI |
| Chargeback | Cardholder disputes a completed payment | Different process; out of scope |
| Inquiry / representment / arbitration | Dispute stages; vary by network | Out of scope |
| Issuer / acquirer / gateway | Cardholder's bank / merchant's bank / the companies in between | Gateway codes are normalized |

---

## 5. The SDLC, shown in this repo

- [PR #1](https://github.com/abhiramvarmaa/payguard-ai/pull/1): `PG-104`, a new rule for code V61
- [PR #2](https://github.com/abhiramvarmaa/payguard-ai/pull/2): `PG-301`, webhooks with outbox, backoff and DLQ

1. A story with acceptance criteria (in a team: written by the product owner, refined with engineers).
2. Branch from an up-to-date `main`: `feature/PG-301-webhook-notifications`.
3. Build with tests; the full suite passes locally.
4. Commit with the ticket number and a short "why".
5. Push and open a PR (What / Why / Testing).
6. CI runs every test on a clean machine.
7. Review the diff, then merge, delete the branch and pull `main`.
8. In a company: staging, QA, UAT, approved release, monitoring and rollback.

---

## 6. Three-minute demo

| Step | Command | Point to make |
|---|---|---|
| 1 | `python -m pytest -q` | 33 tests: rules, API, AI safety, webhooks |
| 2 | `uvicorn --factory app.main:create_app` | API up; `/docs` is generated |
| 3 | `uvicorn merchant_receiver:app --port 9000` | Plays the merchant |
| 4 | `python simulator.py` | Six scenarios across all three routes |
| 5 | `python -m app.worker` | Only the two final cases are delivered |
| 6 | Open `app/router.py` | The routing gate in one function |
| 7 | Open PR #2 | Branch, CI, review, merge |

If the demo breaks, don't debug live: open `app/router.py` and explain the code instead.
