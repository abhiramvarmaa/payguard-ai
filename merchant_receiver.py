"""Fake merchant server that receives PayGuard webhooks, for local demos.

Run:  uvicorn merchant_receiver:app --port 9000
"""
from fastapi import FastAPI, Header

app = FastAPI(title="Demo merchant")
seen_keys: set[str] = set()


@app.post("/webhooks")
def receive(payload: dict, idempotency_key: str = Header()) -> dict:
    if idempotency_key in seen_keys:
        print(f"duplicate {idempotency_key} ignored")
        return {"status": "duplicate_ignored"}
    seen_keys.add(idempotency_key)
    print(f"received {idempotency_key}: case {payload['case_id']} is {payload['status']} ({payload['action']})")
    return {"status": "ok"}
