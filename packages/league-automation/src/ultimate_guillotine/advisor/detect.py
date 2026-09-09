"""Deterministic routing and ask parsing for the Trade Advisor.

Three gates decide whether a message is an advice request, and all three run
before any model does: the Concierge tag, an advice-intent phrase rule, and
(in ``skill.py``) the delivery-target allowlist. A message that asks a factual
question is a lookup even when it also contains advice language -- somebody who
asked what a trade was does not want three new ones proposed at them.

``INJECTION`` is the fourth deterministic check, and it is deliberately narrow:
it fires only on an explicit rule override or an imperative instruction to carry
a trade out. Asking the Advisor to *propose* something -- "make me a trade",
"find me a trade" -- is the whole point of the skill, and a sensitive word that
happens to appear inside an ordinary ask ("who is behind on dues, and who should
I trade with") is not an attack. Refusing those would refuse the league.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from ultimate_guillotine.trades.names import normalize_name

#: Pending Ben's answer to open question 3, a rental with no stated horizon runs
#: two weeks. One constant, so overruling it is a one-line change.
DEFAULT_RENTAL_WEEKS = 2

POSITIONS = ("QB", "RB", "WR", "TE")

BOT_TAG = re.compile(r"@\s*(?:bot|guillotinebot)\b", re.IGNORECASE)

_ADVICE = (
    "who should i trade", "should i trade", "who wants", "trade ideas",
    "any trade ideas", "trade advice", "help me trade", "make me a trade",
    "find me a trade", "what can i get for", "what would it take to get",
    "who would give me", "who needs", "rental", "rent a", "rent me", "rent one",
    "borrow", "for this week only", "one week", "opportunities to move",
    "move a", "move one", "shop", "shopping", "sell high", "buy low", "dump",
    "offload", "upgrade my", "i have too many", "i need a", "trade advisor",
    "advisor",
)
#: A factual question. Checked first: a lookup is never an advice request.
_LOOKUP = (
    "what did", "who did", "when did", "how much did", "what was", "who has",
    "who won", "what does the rule", "what do the rules", "how many",
    "how much faab does", "show me the trade", "look up",
)
_MOVE = (
    "move a", "move one", "opportunities to move", "shop", "shopping",
    "sell high", "dump", "offload", "i have too many", "rent one out",
    "who wants", "what can i get for",
)
_RENTAL = ("rental", "rent a", "rent me", "rent one", "borrow", "one week")
#: Words that make an answer depend on a projected number, which the Advisor
#: cannot give when the coverage gate failed.
_NUMBERS = ("project", "points", "delta", "outscore", "better than my")

#: An explicit attempt to overwrite the Advisor's own instructions.
_OVERRIDE = (
    r"\b(?:ignore|disregard|forget|override|bypass)\s+"
    r"(?:(?:your|the|all|any|previous|prior|above)\s+){1,3}"
    r"(?:rules?|instructions?|prompts?|guidelines?|constraints?)"
    r"|\bsystem prompt\b"
)
#: An imperative instruction to carry a trade out. The Advisor proposes; it has
#: no write path to ``public.trades`` and never claims one.
_EXECUTE = (
    r"\b(?:execute|register|approve|submit|post|file|process)\s+"
    r"(?:it|this|that|(?:the|this|that)\s+(?:trade|deal|swap))\b"
    r"|\b(?:execute|do|make|process)\s+(?:the|this|that)\s+(?:trade|deal|swap)\b"
)
INJECTION = re.compile(f"{_OVERRIDE}|{_EXECUTE}", re.IGNORECASE)

_WEEKS = re.compile(r"(?:next|for)\s+(\d{1,2})\s+weeks?", re.IGNORECASE)
_POSITION = re.compile(r"\b(qb|rb|wr|te)s?\b", re.IGNORECASE)


@dataclass(frozen=True)
class Ask:
    """What the asker asked for, as far as deterministic parsing can tell."""

    positions: tuple[str, ...]
    direction: Literal["acquire", "move", "either"]
    horizon_weeks: int | None
    rental: bool
    named_counterparties: tuple[str, ...]
    wants_numbers: bool


def _normalized(text: str) -> str:
    stripped = BOT_TAG.sub(" ", text)
    return re.sub(r"\s+", " ", stripped.lower()).strip()


def has_bot_tag(text: str) -> bool:
    return BOT_TAG.search(text) is not None


def is_lookup_request(text: str) -> bool:
    body = _normalized(text)
    return any(phrase in body for phrase in _LOOKUP)


def is_advice_request(text: str) -> bool:
    if not has_bot_tag(text) or is_lookup_request(text):
        return False
    body = _normalized(text)
    return any(phrase in body for phrase in _ADVICE)


def is_injection_attempt(text: str) -> bool:
    """Is this an attempt to steer the Advisor rather than ask it something?

    Independent of :func:`is_advice_request`: a hostile message is usually
    phrased as an advice ask, and the handler checks this first.
    """
    return INJECTION.search(_normalized(text)) is not None


def parse_ask(text: str, member_names: Sequence[str]) -> Ask:
    """Read the ask deterministically. Nothing here guesses beyond the words."""
    body = _normalized(text)
    positions = tuple(
        dict.fromkeys(match.group(1).upper() for match in _POSITION.finditer(body))
    )
    rental = any(phrase in body for phrase in _RENTAL)
    direction: Literal["acquire", "move", "either"] = "either"
    if any(phrase in body for phrase in _MOVE):
        direction = "move"
    elif "i need a" in body or "what would it take to get" in body or "upgrade my" in body:
        direction = "acquire"
    weeks = _WEEKS.search(body)
    horizon = int(weeks.group(1)) if weeks else (DEFAULT_RENTAL_WEEKS if rental else None)
    tokens = set(normalize_name(body).split(" "))
    named = tuple(
        name for name in member_names if normalize_name(name) in tokens
    )
    return Ask(
        positions=positions,
        direction=direction,
        horizon_weeks=horizon,
        rental=rental,
        named_counterparties=named,
        wants_numbers=any(word in body for word in _NUMBERS),
    )
