"""The per-turn query: the week, the asker, the fenced message, the contract.

Nothing else. Rosters, history, prices and rules reach the agent through its
tools and its skill, not through this envelope, so the one string that carries
a member's own words carries no other member's anything.
"""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ultimate_guillotine.agent.answer import LeagueAnswer

_ENVELOPE_PATH = Path(__file__).resolve().parents[5] / "agents" / "league-agent" / "envelope.md"
_VERSION = re.compile(r"<!--\s*prompt_version:\s*(\S+)\s*-->")
#: A template slot: capital words joined by single underscores, so two slots side by side are
#: two slots. Anything else shaped like one is left where it stands.
_TOKEN = re.compile(r"__[A-Z]+(?:_[A-Z]+)*__")
MESSAGE_OPEN = "<<<MESSAGE"
MESSAGE_CLOSE = "MESSAGE>>>"
#: A marker in a member's own text, respelled with a space so it cannot open or close the fence.
DEFANGED = {MESSAGE_OPEN: "<<< MESSAGE", MESSAGE_CLOSE: "MESSAGE >>>"}
UNKNOWN_SENDER = (
    "unknown sender -- the league cannot place this handle; ask which team to plan for, "
    "and plan for nobody until told"
)


@lru_cache(maxsize=1)
def _template() -> tuple[str, str]:
    """The version off the first line and the body after it; no version, no template."""
    text = _ENVELOPE_PATH.read_text(encoding="utf-8")
    first_line, _, body = text.partition("\n")
    match = _VERSION.fullmatch(first_line.strip())
    if match is None:
        raise RuntimeError(f"{_ENVELOPE_PATH} does not open with a prompt_version comment")
    return match.group(1), body.lstrip()


PROMPT_VERSION = _template()[0]


@dataclass(frozen=True)
class Turn:
    season: int
    week: int
    local_time: str
    asker_label: str | None
    is_follow_up: bool
    message: str


def _neutralize(text: str) -> str:
    """The text with each fence marker respelled, and otherwise verbatim."""
    for marker, spelling in DEFANGED.items():
        text = text.replace(marker, spelling)
    return text


def build_envelope(turn: Turn) -> str:
    """The turn rendered into the template.

    The member's words are verbatim inside the fence, save that a marker they typed is
    respelled (see ``DEFANGED``) so the fence stays exactly where the template put it.
    """
    replacements = {
        "__SEASON__": str(turn.season),
        "__WEEK__": str(turn.week),
        "__LOCAL_TIME__": turn.local_time,
        "__ASKER__": _neutralize(turn.asker_label or UNKNOWN_SENDER),
        "__TURN__": (
            "a follow-up in the conversation you are resuming"
            if turn.is_follow_up
            else "the first question in a new conversation"
        ),
        "__MESSAGE__": _neutralize(turn.message.strip()),
        "__SCHEMA__": json.dumps(LeagueAnswer.model_json_schema(), separators=(",", ":")),
    }
    # One pass, so no substituted value can be read as a later slot: a message
    # that says __SCHEMA__ is a message, not a slot.
    return _TOKEN.sub(lambda m: replacements.get(m.group(0), m.group(0)), _template()[1])


def retry_envelope(problems: Sequence[str]) -> str:
    lines = "\n".join(f"- {problem}" for problem in problems)
    return (
        "Your unsent draft failed verification:\n"
        f"{lines}\n\n"
        "Correct the facts -- check them with your tools -- and resend the complete "
        "LeagueAnswer JSON block. Do not repeat a claim the data does not support. "
        "This was an internal unsent draft. Correct it silently; do not describe the "
        "verification or apologize for a previous answer the member never received."
    )
