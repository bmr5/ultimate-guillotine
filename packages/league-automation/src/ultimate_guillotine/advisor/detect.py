"""Deterministic routing and ask parsing for the Trade Advisor.

Three gates decide whether a message is an advice request, and all three run
before any model does: the Concierge tag, an advice-intent phrase rule, and
(in ``skill.py``) the delivery-target allowlist. A message that asks a factual
question is a lookup even when it also contains advice language -- somebody who
asked what a trade was does not want three new ones proposed at them.

Phrase rules match on **word boundaries**, never as bare substrings: "workshop"
is not a request to shop a player, and "rent" inside "different" is not a
rental. Every phrase list is compiled into a single alternation by
:func:`_phrase_re` so the rule and its escaping live in one place. Rules
questions are matched as whole questions ("is it allowed", "against the
rules") rather than as the bare words "allowed" and "legal", which turn up
inside genuine advice asks -- "am I allowed to shop my WR" wants three
proposals, not a rules citation.

``INJECTION`` is the fourth deterministic check, and it is deliberately narrow:
it fires only on an explicit rule override or an imperative instruction to carry
a trade out. Asking the Advisor to *propose* something -- "make me a trade",
"find me a trade" -- is the whole point of the skill; a sensitive word that
happens to appear inside an ordinary ask ("who is behind on dues, and who should
I trade with") is not an attack; and neither is asking for the answer to be
shared ("... and post it in the group chat", "... then approve it"). Refusing
those would refuse the league. Only ``execute``/``register``/``process`` are
hostile with a bare pronoun; ``approve``/``submit``/``post``/``file`` need an
explicit object ("register this trade", "post the deal") before they refuse.
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

#: Curly apostrophes, folded to the ASCII one first so every rule below can be
#: written with a single quote character.
_APOSTROPHE = re.compile(r"[’‘´`]")

#: Words that take ``'s`` as a contraction and never as a possessive. A stripper
#: that ate these would turn "who's got Ja'Marr Chase" into "who got ...", which
#: matches no rule at all, and would do it precisely when the sentence starts
#: with one and capitalizes it.
_CONTRACTIONS = frozenset(
    {
        "who",
        "what",
        "that",
        "there",
        "here",
        "it",
        "he",
        "she",
        "one",
        "let",
        "everyone",
        "someone",
        "anyone",
        "nobody",
        "everybody",
    }
)

#: A possessive ending, dropped only after a **name-like** token -- one that is
#: capitalized, or that a caller told us is a member name. ``normalize_name``
#: strips the apostrophe rather than the ending, so an untouched "Joel's" would
#: tokenize to "joels" and match no member. "Ja'Marr" has no ``'s`` to lose.
_POSSESSIVE = re.compile(r"\b([\w']+?)'s\b")

#: Whitespace inside a phrase. Rental phrases also accept a hyphen, so
#: "one-week" and "one week" are the same ask.
_SPACE = r"\s+"
_SPACE_OR_HYPHEN = r"[\s-]+"


def _alternation(phrases: Sequence[str], separator: str = _SPACE) -> str:
    """One word-boundary alternation over ``phrases``, each word escaped."""
    joined = "|".join(
        separator.join(re.escape(word) for word in phrase.split()) for phrase in phrases
    )
    return rf"\b(?:{joined})\b"


def _phrase_re(phrases: Sequence[str], separator: str = _SPACE) -> re.Pattern[str]:
    return re.compile(_alternation(phrases, separator), re.IGNORECASE)


_ADVICE = (
    "who should i trade",
    "should i trade",
    "who wants",
    "trade ideas",
    "any trade ideas",
    "trade advice",
    "help me trade",
    "make me a trade",
    "find me a trade",
    "what can i get for",
    "what would it take to get",
    "who would give me",
    "who needs",
    "opportunities to move",
    "move a",
    "move one",
    "shop",
    "shopping",
    "sell high",
    "buy low",
    "dump",
    "offload",
    "upgrade my",
    "i have too many",
    "i need a",
    "trade advisor",
    "advisor",
)
#: A factual question, plus the rules questions that read like one. Checked
#: first: a lookup is never an advice request, so "is a rental even allowed"
#: asks what the rules permit rather than for three proposals. The rules
#: entries are whole questions, never the bare words "allowed" or "legal" --
#: those appear inside real advice asks ("am I allowed to shop my WR", "who
#: should I trade with if that's allowed") and would swallow them.
_LOOKUP = (
    "what did",
    "who did",
    "when did",
    "how much did",
    "what was",
    "who has",
    "who won",
    "who's got",
    "whos got",
    "what does the rule",
    "what do the rules",
    "how many",
    "how much faab does",
    "show me the trade",
    "look up",
    "is it allowed",
    "even allowed",
    "is that legal",
    "against the rules",
)
_MOVE = (
    "move a",
    "move one",
    "opportunities to move",
    "shop",
    "shopping",
    "sell high",
    "dump",
    "offload",
    "i have too many",
    "rent one out",
    "who wants",
    "what can i get for",
)
_RENTAL = (
    "rental",
    "rent a",
    "rent me",
    "rent one",
    "rent out",
    "borrow",
    "one week",
    "for this week only",
)
#: Words that make an answer depend on a projected number, which the Advisor
#: cannot give when the coverage gate failed. Matched as substrings on purpose:
#: "project" has to cover "projects" and "projection".
_NUMBERS = ("project", "points", "delta", "outscore", "better than my")

#: Week counts the league writes out as words as often as digits.
_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}
_COUNT = rf"\d{{1,2}}|{'|'.join(_NUMBER_WORDS)}"

_ADVICE_RE = _phrase_re(_ADVICE)
_LOOKUP_RE = _phrase_re(_LOOKUP)
_MOVE_RE = _phrase_re(_MOVE)
#: "for the next 3 weeks" is rental language in its own right (design doc,
#: Trigger gate 2), so it routes to the Advisor even without the word "rent".
_RENTAL_RE = re.compile(
    f"{_alternation(_RENTAL, _SPACE_OR_HYPHEN)}"
    rf"|\bfor\s+the\s+next\s+(?:{_COUNT})[\s-]+weeks?\b",
    re.IGNORECASE,
)
_ACQUIRE_RE = _phrase_re(("i need a", "what would it take to get", "upgrade my"))

#: An explicit attempt to overwrite the Advisor's own instructions.
_OVERRIDE = (
    r"\b(?:ignore|disregard|forget|override|bypass)\s+"
    r"(?:(?:your|the|all|any|previous|prior|above)\s+){1,3}"
    r"(?:rules?|instructions?|prompts?|guidelines?|constraints?)"
    r"|\bsystem prompt\b"
)
#: An imperative instruction to carry a trade out. The Advisor proposes; it has
#: no write path to ``public.trades`` and never claims one. Verbs that mean
#: "commit this" on their own take a bare pronoun; verbs that are ordinary chat
#: ("post it in the group chat", "approve it") need a named trade first.
_EXECUTE = (
    r"\b(?:execute|register|process)\s+(?:it|this|that)\b"
    r"|\b(?:execute|register|process|approve|submit|post|file|do|make)\s+"
    r"(?:the|this|that)\s+(?:trade|deal|swap)\b"
)
INJECTION = re.compile(f"{_OVERRIDE}|{_EXECUTE}", re.IGNORECASE)

_WEEKS = re.compile(rf"\b({_COUNT})[\s-]+weeks?\b", re.IGNORECASE)
#: Open-ended horizons the league says out loud. ``Ask.horizon_weeks`` counts
#: weeks, and "the rest of the season" is not a week count, so these record
#: ``None``: read it as "no bounded horizon", the same value an ask that names
#: no horizon at all carries.
_OPEN_ENDED = re.compile(
    r"\brest of (?:the\s+)?season\b|\bthrough the deadline\b|\ball season\b",
    re.IGNORECASE,
)
_POSITION = re.compile(rf"\b({'|'.join(POSITIONS)})s?\b", re.IGNORECASE)


@dataclass(frozen=True)
class Ask:
    """What the asker asked for, as far as deterministic parsing can tell."""

    positions: tuple[str, ...]
    direction: Literal["acquire", "move", "either"]
    horizon_weeks: int | None
    rental: bool
    named_counterparties: tuple[str, ...]
    wants_numbers: bool


def _strip_possessives(text: str, member_tokens: frozenset[str]) -> str:
    """Drop ``'s`` after name-like tokens only, leaving contractions intact."""

    def _stem(match: re.Match[str]) -> str:
        word = match.group(1)
        token = normalize_name(word)
        if token in member_tokens:
            return word
        if word[:1].isupper() and token not in _CONTRACTIONS:
            return word
        return match.group(0)

    return _POSSESSIVE.sub(_stem, text)


def _normalized(text: str, member_tokens: frozenset[str] = frozenset()) -> str:
    body = _APOSTROPHE.sub("'", BOT_TAG.sub(" ", text))
    body = _strip_possessives(body, member_tokens)
    return re.sub(r"\s+", " ", body.lower()).strip()


def _week_count(token: str) -> int:
    return int(token) if token.isdigit() else _NUMBER_WORDS[token]


def has_bot_tag(text: str) -> bool:
    return BOT_TAG.search(text) is not None


def is_lookup_request(text: str) -> bool:
    return _LOOKUP_RE.search(_normalized(text)) is not None


def is_advice_request(text: str) -> bool:
    if not has_bot_tag(text) or is_lookup_request(text):
        return False
    body = _normalized(text)
    return _ADVICE_RE.search(body) is not None or _RENTAL_RE.search(body) is not None


def is_injection_attempt(text: str) -> bool:
    """Is this an attempt to steer the Advisor rather than ask it something?

    Independent of :func:`is_advice_request`: a hostile message is usually
    phrased as an advice ask, and the handler checks this first.
    """
    return INJECTION.search(_normalized(text)) is not None


def parse_ask(text: str, member_names: Sequence[str]) -> Ask:
    """Read the ask deterministically. Nothing here guesses beyond the words."""
    member_tokens = frozenset(
        token for name in member_names for token in normalize_name(name).split()
    )
    body = _normalized(text, member_tokens)
    positions = tuple(dict.fromkeys(match.group(1).upper() for match in _POSITION.finditer(body)))
    rental = _RENTAL_RE.search(body) is not None
    direction: Literal["acquire", "move", "either"] = "either"
    if _MOVE_RE.search(body):
        direction = "move"
    elif _ACQUIRE_RE.search(body):
        direction = "acquire"
    weeks = _WEEKS.search(body)
    if weeks is not None:
        horizon: int | None = _week_count(weeks.group(1))
    elif _OPEN_ENDED.search(body):
        horizon = None
    else:
        horizon = DEFAULT_RENTAL_WEEKS if rental else None
    tokens = set(normalize_name(body).split(" "))
    named = tuple(name for name in member_names if normalize_name(name) in tokens)
    return Ask(
        positions=positions,
        direction=direction,
        horizon_weeks=horizon,
        rental=rental,
        named_counterparties=named,
        wants_numbers=any(word in body for word in _NUMBERS),
    )
