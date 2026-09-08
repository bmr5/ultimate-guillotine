import hashlib
import re


def normalize_address(address: str) -> str:
    value = address.strip().lower()
    if "@" in value:
        return value
    digits = re.sub(r"\D", "", value)
    return f"+{digits}" if digits else value


def participant_fingerprint(addresses: list[str]) -> str:
    normalized = sorted({normalize_address(a) for a in addresses if a and a.strip()})
    return hashlib.sha256("\n".join(normalized).encode()).hexdigest()[:32]
