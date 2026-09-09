import re

ALERT = "🚨"

TRADE_TERMS = re.compile(
    r"\b(send|sends|sent|sending|receive|receives|received|trade|trades|traded|trading|"
    r"buy|buys|bought|sell|sells|sold|rent|rents|rented|renting|swap|swaps|swapped|"
    r"faab|option|protection|pays|paid|insurance)\b",
    re.IGNORECASE,
)
RESCIND_TERMS = re.compile(
    r"\b(rescind|rescinds|rescinded|cancel|cancels|cancelled|canceled|void|voided)\b",
    re.IGNORECASE,
)
HEADER = re.compile(r"trade\s+alert", re.IGNORECASE)


def is_trade_candidate(text: str) -> bool:
    if ALERT not in text:
        return False
    return HEADER.search(text) is not None or TRADE_TERMS.search(text) is not None


def is_rescission_candidate(text: str) -> bool:
    return ALERT in text and RESCIND_TERMS.search(text) is not None
