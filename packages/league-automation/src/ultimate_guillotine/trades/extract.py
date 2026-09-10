"""The single language-model step: one versioned prompt, one structured-output call."""
from functools import lru_cache
from pathlib import Path

from ultimate_guillotine.ai.structured import AIUsage, StructuredOutputClient
from ultimate_guillotine.trades.models import ExtractedTrade

PROMPT_VERSION = "2026.3"
_PROMPT_PATH = Path(__file__).resolve().parents[5] / "agents" / "trade-registrar" / "prompt.md"


@lru_cache(maxsize=1)
def load_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def extract_trade(
    client: StructuredOutputClient,
    text: str,
    season: int,
    week_hint: int | None,
    member_names: list[str],
    announcer: str | None = None,
    context: str | None = None,
) -> tuple[ExtractedTrade, AIUsage]:
    """Put one announcement to the model, with the context lines the prompt reads.

    ``announcer`` is the Sleeper username of whoever posted the message -- the
    same spelling ``member_names`` uses -- and is what first-person references in
    the announcement name. It is written out as ``unknown`` rather than omitted
    when nobody could be placed: the prompt has a rule for an unknown announcer
    (first person then names nobody), and a line that is sometimes missing would
    leave the model to guess which case it is in.

    ``context`` is the context pack from
    :func:`~ultimate_guillotine.trades.context.build_registrar_context` -- the
    current week, the rosters, the FAAB and the season's trades -- and is the
    opposite case: it is *omitted* when there is none, because every one of its
    sections is a list of facts and an empty list of facts is a claim. `Rosters:`
    over nothing says every roster is empty, which is worse than saying nothing
    at all. A missing announcer, by contrast, is itself a fact the prompt has a
    rule for.

    The pack goes after the announcer and before the announcement, so the
    announcement is the last thing the model reads.
    """
    user = (
        f"Season: {season}\nWeek hint: {week_hint if week_hint is not None else 'unknown'}\n"
        f"League members (Sleeper username: names people use): {'; '.join(member_names)}\n"
        f"Announcer: {announcer or 'unknown'}\n\n"
        + (f"{context}\n\n" if context else "")
        + f"Announcement:\n{text}"
    )
    return client.parse(load_prompt(), user, ExtractedTrade, "extracted_trade")
