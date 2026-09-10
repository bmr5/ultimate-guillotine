"""Which messages are worth putting to the model.

This is a *cheap filter*, not a classifier. Its only job is to keep the model
call off the overwhelming majority of a group chat; the model's own
``not_a_trade`` verdict is the real filter, and every rule here is written on the
assumption that a false positive costs one extraction and a silent run row, while
a false negative costs a trade nobody logged.
"""

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

#: The verbs that move something between two people. Narrower than
#: :data:`TRADE_TERMS`, because with no siren in the message these have to carry
#: the whole weight: `trade` and `trading` are what people *talk* about all day
#: and are left out, while `trades` and `traded` report something that happened.
#: `for` is in the list because half the league writes an alert with no verb at
#: all -- `Player Alpha for 300` -- which is why an asset word is required
#: alongside it.
NO_SIREN_VERBS = re.compile(
    r"\b(sends|trades|traded|buys|bought|sells|sold|swap|swaps|rent|rents|rental|for)\b",
    re.IGNORECASE,
)
#: What is being paid. `$1` matches without a word boundary, which `\b` before a
#: dollar sign would not give.
ASSET_WORDS = re.compile(r"\bfaab\b|\$\d|\bdraft\b|\brental\b|\bround\b|\bpick\b", re.IGNORECASE)


def is_trade_candidate(text: str) -> bool:
    """Is this message worth putting to the model?

    The siren is still the strongest signal and the cheapest to trust: with a
    🚨 in the message, a trade word, a rescission word or a `trade alert` header
    is enough, and a rescission counts even when it names no trade word at all --
    `🚨 Cancel T-2026-014 🚨` is exactly the message the registrar has to act on.

    Without a siren the message has to say more, because most of the chat has no
    siren in it. Two shapes get through: a `trade alert` header, which is
    unmistakable; and a verb that moves something between two people together
    with a word for what is being paid (`buys … for $65 FAAB`, `sends … for a 3rd
    round pick`). Requiring both is what keeps `anyone want to trade for a WR`
    out while letting `Ben buys Parker Washington from Ryland for $65 FAAB` in.

    **This function does not decide what is a trade.** The model's `not_a_trade`
    verdict does, and it sees the announcement, the league members, the rosters
    and the rest of the context pack. Everything here is answering the much
    smaller question of whether a model call is worth making, so the rules are
    tuned to let banter through rather than to hold a real alert out.
    """
    if ALERT in text:
        return (
            HEADER.search(text) is not None
            or TRADE_TERMS.search(text) is not None
            or RESCIND_TERMS.search(text) is not None
        )
    if HEADER.search(text) is not None:
        return True
    return NO_SIREN_VERBS.search(text) is not None and ASSET_WORDS.search(text) is not None


def is_rescission_candidate(text: str) -> bool:
    """Does this message cancel a trade by name?

    Still siren-gated, and deliberately so: the caller acts on it *before* any
    model call, rescinding by the code it finds in the text, so a false positive
    here un-logs a real trade rather than costing an extraction. `undo` and
    `never mind` in a chat are common; `🚨 Cancel T-2026-014 🚨` is a decision.
    """
    return ALERT in text and RESCIND_TERMS.search(text) is not None
