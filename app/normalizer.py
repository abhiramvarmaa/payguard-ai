"""Gateway adapter: turns provider-specific raw codes into one internal vocabulary.

These codes are invented for the simulator. They are NOT official Visa/Mastercard codes.
"""
from app.schemas import Gateway

UNKNOWN = "UNKNOWN"

GATEWAY_CODE_MAPS: dict[Gateway, dict[str, str]] = {
    Gateway.SIMULATOR_VISA: {
        "V51": "INSUFFICIENT_FUNDS",
        "V54": "EXPIRED_CARD",
        "V91": "GATEWAY_TIMEOUT",
    },
    Gateway.SIMULATOR_MASTERCARD: {
        "M51": "INSUFFICIENT_FUNDS",
        "M54": "EXPIRED_CARD",
        "M91": "GATEWAY_TIMEOUT",
    },
}


def normalize(gateway: Gateway, raw_code: str) -> str:
    return GATEWAY_CODE_MAPS[gateway].get(raw_code.strip().upper(), UNKNOWN)
