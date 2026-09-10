"""Which messages are worth putting to the model.

This is a *cheap filter*, not a classifier. Its only job is to keep the model
call off the overwhelming majority of a group chat; the model's own
``not_a_trade`` verdict is the real filter, and every rule here is written on the
assumption that a false positive costs one extraction and a silent run row, while
a false negative costs a trade nobody logged.
"""

import re

ALERT = "🚨"
#: The league's header, the shape every alert should take.
TRADE_HEADER = f"{ALERT} Trade alert {ALERT}"

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
#: The word "trade" beside a siren, on the same line: `🚨 Trade alert 🚨`,
#: `Trade alert 🚨`, `🚨 traded …`. Up to fifteen characters may sit between
#: them, which is "alert " and a colon, not a sentence.
TRADE_BY_SIREN = re.compile(r"🚨[^\n🚨]{0,15}\btrade|\btrade\w*[^\n🚨]{0,15}🚨", re.IGNORECASE)


def is_trade_candidate(text: str) -> bool:
    """Is this message worth putting to the model?

    Ben (2026-09-10): "Trades need to be explicitly marked with the Siren."
    And later that day: the word *trade* has to sit next to the siren too --
    "🚨 Trade alert 🚨" -- so a siren used for anything else (a FAAB shout, a
    big game) never costs a model call, and a trade nobody marked that way is
    the announcer's to re-post. A siren with a rescission word still counts:
    `🚨 Cancel T-2026-014 🚨` is exactly the message the registrar acts on.

    **This function does not decide what is a trade.** The model's
    `not_a_trade` verdict does; this only decides whether a model call is worth
    making.
    """
    if ALERT not in text:
        return False
    return TRADE_BY_SIREN.search(text) is not None or RESCIND_TERMS.search(text) is not None


def is_rescission_candidate(text: str) -> bool:
    """Does this message cancel a trade by name?

    Still siren-gated, and deliberately so: the caller acts on it *before* any
    model call, rescinding by the code it finds in the text, so a false positive
    here un-logs a real trade rather than costing an extraction. `undo` and
    `never mind` in a chat are common; `🚨 Cancel T-2026-014 🚨` is a decision.
    """
    return ALERT in text and RESCIND_TERMS.search(text) is not None
