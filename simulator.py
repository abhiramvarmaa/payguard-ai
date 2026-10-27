"""Gateway simulator: sends one example of each scenario to a running PayGuard server.

Usage:  python simulator.py            (server must be running on http://127.0.0.1:8000)
"""
import sys
from uuid import uuid4

import httpx

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
MERCHANT = {"X-API-Key": "merchant-demo-key"}

SCENARIOS = [
    ("Expired card (known rule)", {"gateway": "simulator_visa", "raw_code": "V54"}),
    ("Insufficient funds, Mastercard (known rule)", {"gateway": "simulator_mastercard", "raw_code": "M51"}),
    ("Timeout with unknown status (AI review)", {"gateway": "simulator_visa", "raw_code": "V91",
                                                 "transaction_id": "txn-3001"}),
    ("Unmapped code (AI review)", {"gateway": "simulator_visa", "raw_code": "V99"}),
    ("Risk flag (exception)", {"gateway": "simulator_visa", "raw_code": "V54", "risk_flag": True}),
    ("Bad merchant config (exception)", {"gateway": "simulator_visa", "raw_code": "V51",
                                         "merchant_config_valid": False}),
]


def main() -> None:
    for label, fields in SCENARIOS:
        event = {
            "event_id": f"evt-{uuid4().hex[:8]}",
            "transaction_id": f"txn-{uuid4().hex[:8]}",
            "merchant_id": "merchant-demo",
            **fields,
        }
        response = httpx.post(f"{BASE_URL}/v1/events", json=event, headers=MERCHANT)
        case = response.json()
        action = (case.get("recommendation") or {}).get("recommended_action", case["action"])
        print(f"{label:45} -> {case['route']:13} {case['status']:17} {action}")


if __name__ == "__main__":
    main()
