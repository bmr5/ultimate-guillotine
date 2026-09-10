"""Compact facts in, one validated schema out: the Advisor's only model call.

The facts block is the privacy boundary. It is built by hand, field by field,
from public league values -- the member labels the league renders, team names,
player names, points, FAAB integers, pressure ranks, and historical trade
summaries -- so nothing private can reach the model by accident. Nothing here
serializes a row, a settings object, or a message.

**One call, and no loop around it.** :func:`advise` calls
:meth:`~ultimate_guillotine.ai.structured.StructuredOutputClient.parse` exactly
once. The client's own single validation retry is the only retry there is; a
second `advise` would be a second answer to the same question, priced twice and
possibly different, and the caller is a webhook with a chat message waiting. The
budget for the whole thing is :data:`ADVICE_TIMEOUT_SECONDS`, set explicitly by
:func:`advisor_client` rather than left to the client's default.

**The model ranks; it does not compose.** Candidates are numbered in the facts
and the schema refers to them by that number, so a proposal is a pointer into a
list the package generated plus prose about it. Everything a proposal names is
checked back against the candidate the index points at, which is why the number
may be opaque: it means nothing but "this one".
"""

import subprocess
from collections.abc import Callable, Sequence
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from ultimate_guillotine.advisor.candidates import (
    Candidate,
    CandidateLeg,
    DeltaBasis,
    span_text,
    weeks_covered,
)
from ultimate_guillotine.advisor.detect import Ask
from ultimate_guillotine.advisor.models import TradeAdviceResponse
from ultimate_guillotine.advisor.pricing import (
    COMPARABLE_KINDS,
    PricePoint,
    comparables_for,
)
from ultimate_guillotine.advisor.scoring import POSITIONS, TeamScore
from ultimate_guillotine.advisor.state import LeagueSnapshot
from ultimate_guillotine.ai.hermes import HermesStructuredClient
from ultimate_guillotine.ai.structured import AIUsage, StructuredOutputClient
from ultimate_guillotine.trades.context import league_rules

PROMPT_VERSION = "2026.1"
SCHEMA_NAME = "TradeAdviceResponse"
_PROMPT_PATH = Path(__file__).resolve().parents[5] / "agents" / "trade-advisor" / "prompt.md"

#: Said once, and said the same way everywhere, when the data layer's coverage
#: gate failed: no projected number may appear anywhere in the run.
NO_PROJECTIONS = "projections unavailable"

#: Said once, and said the same way everywhere, for a figure that is unknown
#: rather than zero. A lineup change the package could not compute -- because the
#: gate withheld the numbers behind it, or because somebody contesting the slots
#: has no projection for a covered week -- is rendered with this and never with
#: ``0``, ``+0.00`` or an omitted line. The prompt names the same string, so the
#: rule the model is given and the token it will actually see are one thing.
NOT_COMPUTED = "could not be computed"

#: The budget for the whole call, retry included -- the same minute the
#: Registrar gets, and for the same reason. The listener holds its single-flight
#: lock for the length of this call, so every other member's question is queued
#: behind it; a longer budget does not buy a better answer, it buys a longer
#: silence for everybody else. A question that has not been answered in a minute
#: gets an apology instead, which is what a group chat can actually use.
ADVICE_TIMEOUT_SECONDS = 60.0


@lru_cache(maxsize=1)
def load_prompt() -> str:
    """The Advisor's prompt, with the league's own rules appended.

    The same curated file the Registrar puts in its context pack
    (`agents/trade-registrar/league-rules.md`), read through
    :func:`~ultimate_guillotine.trades.context.league_rules`. One file for both
    agents, because two copies of "draft dollars are FAAB at five to one" would
    eventually be two different rates -- and because an Advisor that does not
    know a rental or an option is ordinary here will propose neither.

    Appended to the system prompt rather than to the facts block: the facts are
    this league tonight, built field by field and checked; the rules are the same
    on every call and are part of what the model is, not part of what it is being
    told. A missing file leaves the prompt exactly as it was.
    """
    prompt = _PROMPT_PATH.read_text(encoding="utf-8")
    rules = league_rules()
    return f"{prompt}\n\n## League rules\n\n{rules}\n" if rules else prompt


def advisor_client(
    profile_home: str,
    model: str | None = None,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> HermesStructuredClient:
    """The Advisor's client, with its timeout stated rather than inherited.

    ``runner`` is the subprocess call, injectable so a test can watch what
    budget actually reaches it rather than read the attribute back off the
    client it just built.
    """
    return HermesStructuredClient(
        profile_home, model=model, runner=runner, timeout=ADVICE_TIMEOUT_SECONDS
    )


def _leg_text(leg: CandidateLeg) -> str:
    if leg.kind == "faab":
        return f"{leg.amount} FAAB from {leg.from_member} to {leg.to_member}"
    return (
        f"{leg.player_name} (id {leg.player_id}, {leg.position or 'position unknown'}) "
        f"from {leg.from_member} to {leg.to_member}"
    )


def _rank_text(rank: int | None) -> str:
    """A rank, or the fact that there is not one. Never a zero standing in."""
    return "unknown" if rank is None else str(rank)


def _delta_text(value: Decimal | None, basis: DeltaBasis) -> str:
    """A lineup change, or :data:`NOT_COMPUTED` -- never a zero standing in.

    Both conditions are checked, not just the ``None``: a delta is only a number
    when the basis says the whole lineup comparison was made, so a future change
    that fills one side in while the other stays unknown cannot quietly start
    reading as a computed figure.
    """
    if value is None or basis != "lineup":
        return NOT_COMPUTED
    return f"{value:+.2f}"


def _team_lines(snapshot: LeagueSnapshot, scores: dict[int, TeamScore], known: bool) -> list[str]:
    lines: list[str] = []
    for team in snapshot.teams:
        score = scores[team.member_id]
        if team.is_eliminated:
            lines.append(f"- {team.member_label} ({team.team_name}): eliminated")
            continue
        needs = (
            ", ".join(f"{position} {score.needs[position]:.1f}" for position in POSITIONS)
            if known
            else NO_PROJECTIONS
        )
        spares = (
            ", ".join(
                f"{position} x{len(score.surpluses[position])}"
                for position in POSITIONS
                if score.surpluses[position]
            )
            or "none"
        )
        lines.append(
            f"- {team.member_label} ({team.team_name}): needs {needs}; "
            f"spare {spares}; FAAB {team.faab_remaining}; "
            f"pressure rank {_rank_text(score.pressure_rank)}"
        )
    return lines


def _candidate_lines(
    snapshot: LeagueSnapshot, candidates: Sequence[Candidate], known: bool
) -> list[str]:
    """The numbered list the answer must point back into.

    The number is the whole contract: it is what ``candidate_index`` carries and
    what the verifier looks up, so it is written before anything else about the
    candidate and it counts from one with no gaps.
    """
    lines: list[str] = []
    for index, candidate in enumerate(candidates, start=1):
        reasons = candidate.reasons
        span = span_text(weeks_covered(snapshot, candidate))
        lines.append(f"CANDIDATE {index}: counterparty {candidate.counterparty}")
        for leg in candidate.asker_receives:
            lines.append(f"  asker receives: {_leg_text(leg)}")
        for leg in candidate.asker_sends:
            lines.append(f"  asker sends: {_leg_text(leg)}")
        lines.append(f"  structure: {candidate.structure}")
        if candidate.return_condition:
            lines.append(f"  return condition: {candidate.return_condition}")
        lines.append(f"  position: {reasons.position}; price basis: {reasons.price_basis}")
        if known:
            lines.append(
                f"  receiving side need: {reasons.need_points:.1f} "
                f"(rank {_rank_text(reasons.need_rank)})"
            )
        lines.append(
            f"  counterparty pressure rank: {_rank_text(candidate.counterparty_pressure_rank)}"
        )
        lines.append(
            f"  asker point change ({span}): "
            f"{_delta_text(candidate.asker_delta, reasons.delta_basis)}"
        )
        lines.append(
            f"  counterparty point change ({span}): "
            f"{_delta_text(candidate.counterparty_delta, reasons.delta_basis)}"
        )
        if candidate.comparable_trade_code:
            lines.append(f"  comparable trade: {candidate.comparable_trade_code}")
    return lines or ["- no legal trade answers this ask"]


def _history_lines(points: Sequence[PricePoint], *, rental: bool) -> list[str]:
    """The prices this ask may be compared against, and no others.

    Read out of the same population
    :func:`~ultimate_guillotine.advisor.candidates._price` priced the
    candidates from, so the history block and the FAAB beside each candidate
    can never disagree: a rental ask is shown what the league has paid to
    borrow a position, a permanent one what it has paid to keep one. Handing
    the model both would invite it to argue an offer down against a loan.
    """
    kinds = ("rental",) if rental else COMPARABLE_KINDS
    verb = "was rented for" if rental else "went for"
    lines: list[str] = []
    for position in POSITIONS:
        for point in comparables_for(points, position, limit=2, kinds=kinds):
            lines.append(
                f"- {point.trade_code} ({point.season}): a {position} "
                f"({point.player_name}) {verb} {point.faab} FAAB"
            )
    kind_word = "rental " if rental else ""
    return lines or [f"- no comparable {kind_word}FAAB prices on file"]


def build_facts(
    snapshot: LeagueSnapshot,
    scores: dict[int, TeamScore],
    asker_member_id: int,
    ask: Ask,
    candidates: Sequence[Candidate],
    points: Sequence[PricePoint],
) -> str:
    """Everything the model may see, and nothing else."""
    asker = snapshot.team_for_member(asker_member_id)
    if asker is None:
        raise ValueError(f"member {asker_member_id} has no team in this snapshot")
    known = snapshot.coverage_ok()
    horizon = f"{ask.horizon_weeks} weeks" if ask.horizon_weeks else "unspecified"
    header = [
        f"Season {snapshot.season}, Week {snapshot.week}.",
        f"Asker: {asker.member_label} ({asker.team_name}), FAAB {asker.faab_remaining}.",
        (
            f"Ask: positions {', '.join(ask.positions) or 'any'}; "
            f"direction {ask.direction}; horizon {horizon}; "
            f"rental {'yes' if ask.rental else 'no'}."
        ),
        f"A point change of '{NOT_COMPUTED}' is unknown, not zero.",
        "Each point change is a total over the weeks named beside it.",
    ]
    if not known:
        header.append(f"Projections: {NO_PROJECTIONS}; rank on roster shape alone.")
    return "\n".join(
        [
            *header,
            "",
            "TEAMS",
            *_team_lines(snapshot, scores, known),
            "",
            "LEAGUE PRICE HISTORY",
            *_history_lines(points, rental=ask.rental),
            "",
            "CANDIDATES",
            *_candidate_lines(snapshot, candidates, known),
        ]
    )


def advise(
    client: StructuredOutputClient,
    snapshot: LeagueSnapshot,
    scores: dict[int, TeamScore],
    asker_member_id: int,
    ask: Ask,
    candidates: Sequence[Candidate],
    points: Sequence[PricePoint],
) -> tuple[TradeAdviceResponse, AIUsage]:
    """The one model call in the whole skill. Called once; never looped on.

    The invoking question is deliberately not in the facts block: the
    deterministic :class:`~ultimate_guillotine.advisor.detect.Ask` is what the
    model needs, and passing the raw text back would be the one place a prompt
    injection could reach the model. If a later change does pass it, it must be
    clearly fenced and labelled as data.
    """
    facts = build_facts(snapshot, scores, asker_member_id, ask, candidates, points)
    return client.parse(load_prompt(), facts, TradeAdviceResponse, SCHEMA_NAME)
