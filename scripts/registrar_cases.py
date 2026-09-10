"""Run the Trade Registrar case suite without writing or sending anything.

Each case in `packages/league-automation/tests/fixtures/registrar_cases.json` is
pushed through the same three steps `ug trades extract` takes -- `extract_trade`,
`resolve_extracted`, `validate` -- and the extracted kind and the resolution
outcome are compared with what the case expects. Nothing touches
`public.trades`, `private.outbound_messages`, or the delivery service, so the
suite is safe to leave running overnight against the league chat's real model.

A case may name an `announcer`: the Sleeper username of the member who sent the
alert, which is what the listener works out from the sender's hashed handle and
what first-person announcements ("I sent X to Y") name. A case with no
`announcer` is one whose sender could not be placed, which is a different
question to put to the model rather than a missing field.

Cases that only mean something after another case is on file (a revision, a
repost, a rescission) name that case in `prereq` and are skipped: a dry run has
no database state to revise or rescind. A case whose `expected_status` is
`dropped_upstream` is skipped for a different reason: the listener drops that
message before the trigger ever runs, so putting it to the model would ask a
question production never asks and score the answer as a failure. Everything
else runs.

    uv run --project packages/league-automation python scripts/registrar_cases.py --dry-run-fakes
    uv run --project packages/league-automation python scripts/registrar_cases.py
    uv run --project packages/league-automation python scripts/registrar_cases.py --category sloppy

The results table lands in `docs/testing/2026-09-09-trade-registrar-results.md`
and carries case ids only -- never announcement text, member handles, or the
question the registrar would have asked -- because the results file is read in
Discord and the league chat is private.
"""

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
from ultimate_guillotine.ai.structured import AIUsage
from ultimate_guillotine.cli.deps import build_ai, build_deps
from ultimate_guillotine.data.repositories import MemberAliasRepository, SeasonRepository
from ultimate_guillotine.sleeper.client import SleeperClient
from ultimate_guillotine.sleeper.players import PlayerRepository
from ultimate_guillotine.advisor.state import SnapshotRepository
from ultimate_guillotine.trades.context import (
    TRADE_LIMIT,
    ContextPlayer,
    ContextTeam,
    build_registrar_context,
    context_from_snapshot,
)
from ultimate_guillotine.trades.detect import is_trade_candidate
from ultimate_guillotine.trades.extract import PROMPT_VERSION, extract_trade
from ultimate_guillotine.trades.models import ExtractedAsset, ExtractedParty, ExtractedTrade
from ultimate_guillotine.trades.repository import TradeRepository
from ultimate_guillotine.trades.names import normalize_name
from ultimate_guillotine.trades.resolve import (
    RosterIndex,
    Unresolved,
    build_roster_index,
    resolve_extracted,
    validate,
)

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "packages/league-automation/tests/fixtures/registrar_cases.json"
RESULTS = REPO / "docs/testing/2026-09-09-trade-registrar-results.md"

#: What a dry run can actually observe for each registrar status. `revised`,
#: `duplicate` and `rescinded` all resolve to a valid proposal here -- what
#: separates them from `created` is database state, which is why every case
#: expecting one of them carries a `prereq` and is skipped.
EXPECTED_OUTCOME = {
    "created": "created",
    "revised": "created",
    "duplicate": "created",
    "rescinded": "created",
    "clarification": "clarification",
    "not_a_trade": "not_a_trade",
}
#: A message the detector rejects never reaches the model, which is the correct
#: handling of a non-alert -- so it satisfies a `not_a_trade` expectation.
NOT_A_CANDIDATE = "not-a-candidate"
#: The status of a case the listener drops before the agent is reached at all --
#: the bot's own signed confirmation echoed back into the chat. The suite skips
#: these by design: they are a statement about the listener, and an extraction
#: the listener never asks for is not a result worth scoring.
DROPPED_UPSTREAM = "dropped_upstream"
#: A name no row in `public.players` can match, used by the fake client to force
#: the resolution failure a clarification case expects.
UNRESOLVABLE = "Nonexistent Placeholder Player"

#: The synthetic league the cases are read against: three teams, their rosters,
#: their FAAB, a week, and two trades on file. It is what the context pack is
#: built from and what the roster-aware player resolution reads, so a case
#: exercises the same rendering and the same resolution production does.
#:
#: Deliberately small, and deliberately made of players no other case names. The
#: prompt's rule for a name that matches nobody's roster is to leave it exactly
#: as the announcement wrote it, so the sixty-odd cases that predate the pack are
#: unaffected by it -- and no case can contradict the pack by having somebody
#: trade away a player the pack says is on another team's roster.
#:
#: Each roster is built for one question. `Rhamondre` is a first name only its
#: owner answers to; `Stevenson` is a surname two active players share, so the
#: old whole-directory rule asks which team and only the giver's roster settles
#: it; `Michael` is two men on one roster, which has to stay a question;
#: `Quentin` is on nobody's roster but mdurgin's, which is the league-wide step.
SYNTHETIC_WEEK = 4
SYNTHETIC_ROSTERS: dict[str, tuple[str, ...]] = {
    "kpbowe": ("Rhamondre Stevenson", "Michael Pittman", "Michael Wilson"),
    "mdurgin": ("Quentin Johnston", "Khalil Shakir"),
    "chobes": ("Zay Flowers", "Courtland Sutton"),
}
SYNTHETIC_FAAB = {"kpbowe": 480, "mdurgin": 260, "chobes": 55}
#: Two trades in `TradeRepository.list_recent` shape, so the pack's
#: `Trades this season` section is rendered the way production renders it. The
#: terms agree with the rosters above: kpbowe holds Michael Pittman because
#: T-2026-002 is how he got him.
SYNTHETIC_TRADES = [
    {
        "trade_code": "T-2026-002",
        "status": "accepted",
        "effective_week": 3,
        "terms": {
            "parties": [
                {"member_id": 1, "display_name": "chobes"},
                {"member_id": 2, "display_name": "kpbowe"},
            ],
            "assets": [
                {"kind": "player", "from_member_id": 1, "to_member_id": 2,
                 "player_name": "Michael Pittman", "player_id": None,
                 "amount": None, "unit": None, "description": None},
                {"kind": "faab", "from_member_id": 2, "to_member_id": 1,
                 "player_name": None, "player_id": None,
                 "amount": 120, "unit": "faab", "description": None},
            ],
        },
    },
    {
        "trade_code": "T-2026-001",
        "status": "rescinded",
        "effective_week": 2,
        "terms": {
            "parties": [
                {"member_id": 3, "display_name": "mdurgin"},
                {"member_id": 1, "display_name": "chobes"},
            ],
            "assets": [
                {"kind": "faab", "from_member_id": 3, "to_member_id": 1,
                 "player_name": None, "player_id": None,
                 "amount": 40, "unit": "faab", "description": None},
            ],
        },
    },
]


@dataclass(frozen=True)
class Result:
    case_id: int
    category: str
    expected_kind: str
    expected_status: str
    actual_kind: str
    outcome: str
    passed: bool
    reason: str


class FakeClient:
    """A stand-in for the model that answers each case with what it expects.

    It proves the harness end to end -- fixture, filters, resolution, the
    results table -- without spending a model call or waiting on a backend that
    is being swapped. It cannot prove anything about extraction accuracy: every
    case passes by construction, which is the point of the `--dry-run-fakes`
    name.
    """

    def __init__(self, case: dict, members: list) -> None:
        self._case = case
        self._members = members

    def parse(self, system: str, user: str, schema, schema_name: str):
        return self._build(), AIUsage("fake", 0, 0, "fake")

    def _build(self) -> ExtractedTrade:
        kind = self._case["expected_kind"]
        if kind == "not_a_trade":
            return ExtractedTrade(kind="not_a_trade")
        if kind == "unclear":
            return ExtractedTrade(kind="unclear", unclear_reason="fake client")
        giver, taker = self._members[0].display_name, self._members[1].display_name
        if self._case["expected_status"] == "clarification":
            # An unresolvable player is the one failure every clarification
            # case can be forced into without knowing why the real one fails.
            assets = [
                ExtractedAsset(
                    kind="player", from_party=giver, to_party=taker, player_name=UNRESOLVABLE
                )
            ]
            condition = None
        else:
            assets = [
                ExtractedAsset(
                    kind="faab", from_party=taker, to_party=giver, amount=100, unit="faab"
                )
            ]
            condition = "returned after the Week 4 games" if kind == "rental" else None
        return ExtractedTrade(
            kind=kind,
            parties=[ExtractedParty(name=giver), ExtractedParty(name=taker)],
            assets=assets,
            rental_return_condition=condition,
        )


def load_cases() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]


def select(cases: list[dict], ids: str | None, category: str | None, limit: int | None):
    if ids:
        wanted = {int(part) for part in ids.split(",") if part.strip()}
        cases = [c for c in cases if c["id"] in wanted]
    if category:
        cases = [c for c in cases if c["category"] == category]
    if limit is not None:
        cases = cases[:limit]
    return cases


def find_announcer(members: list, username: str):
    """The member a case's `announcer` names, matched on display name or alias."""
    wanted = normalize_name(username)
    for member in members:
        names = {normalize_name(member.display_name)} | {
            normalize_name(alias) for alias in member.aliases
        }
        if wanted in names:
            return member
    return None


def synthetic_league(members: list, players: list) -> tuple[RosterIndex, str]:
    """The rosters and the context pack the cases are read against.

    Returns the index resolution consults and the pack the prompt reads, built
    from the same three teams so the two can never disagree -- a case that
    resolves a first name off the giver's roster is reading the roster the model
    was shown.

    A member `SYNTHETIC_ROSTERS` names but `public.members` does not have, or a
    player `public.players` does not have, is skipped rather than guessed at: the
    resulting pack is smaller and the case that needed him fails, which is the
    honest report.
    """
    by_name = {normalize_name(p.full_name): p for p in players}
    holdings: dict[int, frozenset[str]] = {}
    teams: list[ContextTeam] = []
    for member in members:
        names = SYNTHETIC_ROSTERS.get(member.display_name)
        if not names:
            continue
        rows = [by_name[n] for n in (normalize_name(x) for x in names) if n in by_name]
        holdings[member.member_id] = frozenset(p.sleeper_player_id for p in rows)
        teams.append(
            ContextTeam(
                username=member.display_name,
                aliases=tuple(member.aliases),
                faab_remaining=SYNTHETIC_FAAB.get(member.display_name, 100),
                players=tuple(ContextPlayer(p.full_name, p.position) for p in rows),
            )
        )
    pack = build_registrar_context(SYNTHETIC_WEEK, teams, SYNTHETIC_TRADES)
    return RosterIndex(holdings), pack


def run_case(
    case: dict, ai, members, players, rosters: RosterIndex, season: int, context: str | None = None
) -> Result:
    """Extract, resolve, and validate one case, and say whether it matched.

    Failures are reported structurally -- a kind, an outcome, an exception class
    -- and never as prose lifted from the announcement or from the question the
    registrar would have asked.
    """
    expected_kind = case["expected_kind"]
    expected_outcome = EXPECTED_OUTCOME[case["expected_status"]]
    announcer = None
    if case.get("announcer"):
        announcer = find_announcer(members, case["announcer"])
        if announcer is None:
            # Running it anyway would put the unplaceable-sender question to the
            # model and score the answer against the placed-sender expectation.
            return _result(case, "-", "no-announcer", False, "announcer is not a member")
    kind, outcome = "-", ""
    if not is_trade_candidate(case["text"]):
        outcome = NOT_A_CANDIDATE
    else:
        try:
            extracted, usage = extract_trade(
                ai,
                case["text"],
                season,
                None,
                [_member_line(m) for m in members],
                announcer.display_name if announcer else None,
                context,
            )
        except Exception as exc:  # noqa: BLE001 - any model failure is reported the same way
            return _result(case, "-", f"error:{exc.__class__.__name__}", False, "model call failed")
        kind = extracted.kind
        if kind == "not_a_trade":
            outcome = "not_a_trade"
        else:
            try:
                proposal = resolve_extracted(
                    extracted,
                    members,
                    players,
                    rosters,
                    season,
                    f"case:{case['id']}",
                    case["text"][:2000],
                    PROMPT_VERSION,
                    usage.model,
                    announcer=announcer,
                )
                validate(proposal)
                outcome = "created"
            except Unresolved:
                outcome = "clarification"

    reasons = []
    if outcome == NOT_A_CANDIDATE:
        # The detector answered before the model did: the only expectation that
        # can be checked is that nothing was supposed to be logged.
        if expected_outcome != "not_a_trade":
            reasons.append("detector rejected the message")
    else:
        if kind != expected_kind:
            reasons.append(f"kind {kind}")
        if outcome != expected_outcome:
            reasons.append(f"outcome {outcome}")
    return _result(case, kind, outcome, not reasons, ", ".join(reasons))


def _result(case: dict, kind: str, outcome: str, passed: bool, reason: str) -> Result:
    return Result(
        case_id=case["id"],
        category=case["category"],
        expected_kind=case["expected_kind"],
        expected_status=case["expected_status"],
        actual_kind=kind,
        outcome=outcome,
        passed=passed,
        reason=reason or "",
    )


def _member_line(member) -> str:
    return f"{member.display_name}: {', '.join(member.aliases) or 'no known nicknames'}"


def write_results(
    results: list[Result],
    skipped: list[dict],
    dropped: list[dict],
    fakes: bool,
    started: datetime,
) -> str:
    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed
    mode = "fake client (harness self-check)" if fakes else "live extraction model"
    lines = [
        "# Trade Registrar case results",
        "",
        f"Run {started:%Y-%m-%d %H:%M UTC} against the {mode}.",
        "Cases come from `packages/league-automation/tests/fixtures/registrar_cases.json`;",
        "case text is deliberately not repeated here.",
        "",
        "Two kinds of case are skipped rather than run, and neither counts as a failure:",
        "one that needs a prior case already on file, which a dry run cannot produce, and",
        "one marked `dropped_upstream`, which the listener discards before the agent is",
        "reached at all. Asking the model about a message it never sees in production would",
        "score an answer nothing depends on.",
        "",
        (
            f"**{len(results)} run · {passed} passed · {failed} failed · "
            f"{len(skipped)} skipped (prerequisite state) · "
            f"{len(dropped)} dropped upstream.**"
        ),
        "",
        (
            "| # | category | expected kind | expected status | actual kind | outcome"
            " | result | mismatch |"
        ),
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        verdict = "pass" if r.passed else "FAIL"
        lines.append(
            f"| {r.case_id} | {r.category} | `{r.expected_kind}` | `{r.expected_status}` | "
            f"`{r.actual_kind}` | `{r.outcome}` | {verdict} | {r.reason or '—'} |"
        )
    lines += ["", "## Totals by category", "", "| category | run | passed | failed |",
              "| --- | --- | --- | --- |"]
    for category in dict.fromkeys(r.category for r in results):
        rows = [r for r in results if r.category == category]
        ok = sum(1 for r in rows if r.passed)
        lines.append(f"| {category} | {len(rows)} | {ok} | {len(rows) - ok} |")
    if skipped:
        ids = ", ".join(str(c["id"]) for c in skipped)
        lines += [
            "",
            "## Skipped",
            "",
            "These cases need a prior case already on file, which a dry run has no way to",
            f"produce: {ids}.",
        ]
    if dropped:
        ids = ", ".join(str(c["id"]) for c in dropped)
        lines += [
            "",
            "## Dropped upstream",
            "",
            "The listener drops these before the trigger runs -- the bot's own signed text --",
            f"so they never reach extraction and are skipped by design: {ids}.",
        ]
    lines.append("")
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text("\n".join(lines), encoding="utf-8")
    return (
        f"{len(results)} run, {passed} passed, {failed} failed, "
        f"{len(skipped)} skipped, {len(dropped)} dropped upstream"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ids", help="comma-separated case ids to run")
    parser.add_argument("--category", help="run one category only")
    parser.add_argument("--limit", type=int, help="stop after this many selected cases")
    parser.add_argument(
        "--rosters",
        action="store_true",
        help="use the league's live Sleeper rosters instead of the synthetic ones",
    )
    parser.add_argument(
        "--dry-run-fakes",
        action="store_true",
        help="answer every case with a fake extraction, to check the harness itself",
    )
    args = parser.parse_args()

    cases = select(load_cases(), args.ids, args.category, args.limit)
    dropped = [c for c in cases if c["expected_status"] == DROPPED_UPSTREAM]
    reachable = [c for c in cases if c["expected_status"] != DROPPED_UPSTREAM]
    runnable = [c for c in reachable if not c["prereq"]]
    skipped = [c for c in reachable if c["prereq"]]

    deps = build_deps()
    conn = deps.conn
    season = SeasonRepository(conn).current() or datetime.now(UTC).year
    members = MemberAliasRepository(conn).all_members()
    players = PlayerRepository(conn).all_active()
    # The synthetic league is the default: the roster cases turn on it, and the
    # pack the model reads has to describe the rosters resolution consults or the
    # two halves of the same answer disagree. `--rosters` swaps in the real
    # league -- both halves of it, index and pack -- which measures the same
    # cases against whatever the rosters happen to be tonight: useful once, not
    # a suite.
    rosters, context = synthetic_league(members, players)
    if args.rosters:
        rosters = build_roster_index(
            SleeperClient(httpx.Client()), conn, deps.settings.sleeper_league_id, season
        )
        context = context_from_snapshot(
            SnapshotRepository(conn).load(), members, TradeRepository(conn).list_recent(TRADE_LIMIT)
        )
    if args.dry_run_fakes and len(members) < 2:
        print("need at least two members in public.members to build fake extractions")
        return 2
    ai = None if args.dry_run_fakes else build_ai(deps)

    started = datetime.now(UTC)
    results = [
        run_case(
            case,
            FakeClient(case, members) if args.dry_run_fakes else ai,
            members,
            players,
            rosters,
            season,
            context,
        )
        for case in runnable
    ]
    print(write_results(results, skipped, dropped, args.dry_run_fakes, started))
    return 1 if any(not r.passed for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
