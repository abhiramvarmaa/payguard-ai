# PayGuard AI

A payment-failure triage service, built as a portfolio project. When a payment fails, PayGuard decides which of three paths it takes:

| Route | When | What happens |
|---|---|---|
| `DETERMINISTIC` | Known code, approved rule, no risk | A Python rule picks the action. No AI. |
| `AI_REVIEW` | Valid event, but no rule covers it | AI collects evidence and recommends a step. A human approves or rejects it. |
| `EXCEPTION` | Risk flag, bad merchant config, conflicting rules, AI failure | Sent straight to a person. |

All data is synthetic. The gateway codes (`V51`, `M54`, ...) are made up and are **not** real Visa/Mastercard codes. Nothing charges, refunds or contacts a card network.

## Run it

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q                               # 20 tests
uvicorn --factory app.main:create_app --reload    # http://127.0.0.1:8000/docs
python simulator.py                               # in a second terminal
```

Or with Docker:

```bash
docker build -t payguard-ai .
docker run -p 8000:8000 payguard-ai
```

## API

| Method | Path | Who |
|---|---|---|
| `GET` | `/health` | anyone |
| `POST` | `/v1/events` | merchant (own `merchant_id` only) |
| `GET` | `/v1/cases?status=` | merchant (own cases) or analyst (all) |
| `GET` | `/v1/cases/{id}` | same; includes audit trail and AI trajectory |
| `POST` | `/v1/cases/{id}/approve` · `/reject` · `/resolve` | analyst |

Demo API keys (header `X-API-Key`): `merchant-demo-key`, `merchant-other-key`, `analyst-key`.

## What is built vs planned

**Built:** validation, gateway normalisation, versioned rules with priority and conflict detection, three-way routing, SQLite/PostgreSQL persistence, idempotency (with a check for reused IDs that carry a different payload), API-key auth with merchant isolation, a case state machine, an audit trail, AI investigation with allowlisted tools, keyword-based policy retrieval, output guardrails, a forced human approval step, AI run logging (steps, tokens, latency), correlation IDs, 20 tests, Docker and GitHub Actions CI.

**Planned:** async queue and workers with a dead-letter queue, webhook notifications, a real LLM adapter, embedding-based retrieval (pgvector), a React dashboard, database migrations (Alembic), and an AWS deployment (ECS, RDS, SQS) with Terraform.

The full walkthrough is in [docs/LEARNING_GUIDE.md](docs/LEARNING_GUIDE.md).
