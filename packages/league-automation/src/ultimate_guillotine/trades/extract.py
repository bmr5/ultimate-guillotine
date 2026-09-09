"""The single language-model step: one versioned prompt, one structured-output call."""
from functools import lru_cache
from pathlib import Path

from ultimate_guillotine.ai.structured import AIUsage, StructuredOutputClient
from ultimate_guillotine.trades.models import ExtractedTrade

PROMPT_VERSION = "2026.1"
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
) -> tuple[ExtractedTrade, AIUsage]:
    user = (
        f"Season: {season}\nWeek hint: {week_hint if week_hint is not None else 'unknown'}\n"
        f"League members (Sleeper username: names people use): {'; '.join(member_names)}\n\n"
        f"Announcement:\n{text}"
    )
    return client.parse(load_prompt(), user, ExtractedTrade, "extracted_trade")
