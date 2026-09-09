"""`ug advisor ask`: run the whole Advisor pipeline and print, never send.

The point of this command is that it is *impossible* for it to post. It builds a
:class:`~ultimate_guillotine.advisor.skill.TradeAdvisor` with no delivery
service, no run repository and no database connection, and calls
:meth:`~ultimate_guillotine.advisor.skill.TradeAdvisor.answer`, which reserves
nothing, commits nothing and delivers nothing. A prompt change or a scoring
change can be checked against the real league without the chat ever seeing it,
by construction rather than by discipline.

Three flags shape what it costs. ``--json`` prints the candidate set instead of
the advice, which is the whole of what the model would have been handed and
makes **no model call at all**. ``--fixture`` answers out of
:mod:`ultimate_guillotine.advisor.fixture` -- the closed-form 18-team league the
Advisor is tested against -- so the command runs on a machine with no database,
no Sleeper sync and no league data, which is what a prompt change usually wants
to be tried against first. Together they are free and offline.

The asker is named on the command line rather than matched from a message, so no
contact repository is built and no handle is hashed. ``--as`` matches a display
name or any of the member's aliases; an alias is matched but never printed back,
the same rule ``ug members`` follows.

Ops notes go to stderr, not to Discord. A rejected answer is a thing the
operator running the dry run needs to see and `#guillotine-ops` does not: a note
posted from a dry run is a message this command promised not to send.
"""

import argparse
import dataclasses
import json
import sys

from ultimate_guillotine.advisor.candidates import Candidate
from ultimate_guillotine.advisor.fixture import fixture_snapshot
from ultimate_guillotine.advisor.pricing import PriceRepository
from ultimate_guillotine.advisor.prompt import advisor_client
from ultimate_guillotine.advisor.skill import TradeAdvisor, horizon_weeks
from ultimate_guillotine.advisor.state import SnapshotRepository, SnapshotUnavailable
from ultimate_guillotine.ai.structured import AIInvalidOutput, AIUnavailable
from ultimate_guillotine.cli.deps import build_deps
from ultimate_guillotine.config import Settings, load_settings
from ultimate_guillotine.core.hermes_cli import find_hermes_binary
from ultimate_guillotine.data.repositories import MemberAliasRepository
from ultimate_guillotine.trades.models import MemberRef
from ultimate_guillotine.trades.names import normalize_name

#: What a run that never called a model prints where the model would go. Said
#: outright rather than left blank: "no model" is the interesting half of a
#: refusal, a stand-pat answer and a withheld projection.
NO_MODEL = "none (answered without a model call)"


def register(subparsers) -> None:
    parser = subparsers.add_parser("advisor", help="trade advice commands")
    advisor_sub = parser.add_subparsers(dest="command", required=True)
    ask = advisor_sub.add_parser(
        "ask",
        help="dry-run one advice question; never sends, never writes, records no run",
    )
    ask.add_argument("--text", required=True, help="the question, as it would be asked")
    ask.add_argument("--as", dest="member", required=True, help="member display name or alias")
    ask.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="print the candidate set the model would be handed; makes no model call",
    )
    ask.add_argument(
        "--fixture",
        action="store_true",
        help="answer out of the fixture league instead of the database",
    )
    ask.set_defaults(handler=cmd_ask)


class FixtureLeague:
    """Every read the Advisor makes, answered from the fixture league.

    One object standing in for three repositories, because it is standing in for
    one thing: the league. There is no price history -- the fixture league has
    never traded -- so comparables come back empty and every candidate is priced
    off the league's median budget, which is what
    :mod:`~ultimate_guillotine.advisor.candidates` does with a position nobody
    has ever paid for.
    """

    def __init__(self) -> None:
        self._members = [
            MemberRef(team.member_id, team.member_label, ())
            for team in fixture_snapshot().teams
        ]

    def load(self, horizon_weeks: int = 1):
        return fixture_snapshot(horizon_weeks=horizon_weeks)

    def all_members(self) -> list[MemberRef]:
        return list(self._members)

    def accepted_terms(self, seasons, limit: int = 200) -> list:
        return []


class StderrNotifier:
    """The dry run's ops channel: the terminal it was typed into.

    The reason a rejected answer was rejected names ids and amounts, which is
    why the chat never sees it -- but the operator asking why a prompt change
    stopped working is exactly who it was written for.
    """

    def ops(self, text: str) -> bool:
        print(text, file=sys.stderr)
        return True

    def alerts(self, text: str) -> bool:
        print(text, file=sys.stderr)
        return True


def resolve_member(members, wanted: str) -> MemberRef | None:
    """Match a display name or an alias, the way message resolution does.

    Normalized on both sides, so ``member18``, ``Member18`` and ``Member 18``
    are one member and the operator does not have to spell a nickname the way
    the roster stores it.
    """
    target = normalize_name(wanted)
    for member in members:
        keys = {normalize_name(member.display_name)}
        keys |= {normalize_name(alias) for alias in member.aliases}
        if target in keys:
            return member
    return None


def _leg(leg) -> dict:
    return dataclasses.asdict(leg)


def _number(value) -> str | None:
    """A Decimal as the string it was computed as, or ``None`` for unknown.

    Never a float: a point change printed as ``12.299999999999999`` is a figure
    an operator has to squint at, and never a ``0`` standing in for a number
    nobody has.
    """
    return None if value is None else f"{value}"


def candidate_json(candidate: Candidate) -> dict:
    """One candidate, as much of it as an operator checks by eye.

    The counterparty's pressure rank is left out for the same reason the chat
    never sees it: it is a number about how close somebody else is to being cut,
    and a dry run is not a reason to write it down.
    """
    return {
        "counterparty": candidate.counterparty,
        "asker_receives": [_leg(leg) for leg in candidate.asker_receives],
        "asker_sends": [_leg(leg) for leg in candidate.asker_sends],
        "structure": candidate.structure,
        "return_condition": candidate.return_condition,
        "fit_score": _number(candidate.fit_score),
        "asker_delta": _number(candidate.asker_delta),
        "counterparty_delta": _number(candidate.counterparty_delta),
        "comparable_trade_code": candidate.comparable_trade_code,
    }


def _client(settings: Settings):
    """The Advisor's own client, with the Advisor's own timeout.

    Built here rather than through `build_ai` so a dry run and the listener ask
    the same model the same way; a missing CLI is a setup problem, and a plain
    message beats a traceback out of `subprocess`.
    """
    if find_hermes_binary() is None:
        raise SystemExit("hermes CLI not found")
    return advisor_client(settings.hermes_profile_home, model=settings.hermes_model)


def cmd_ask(args: argparse.Namespace) -> int:
    """Answer one question out loud, into the terminal and nowhere else."""
    settings: Settings | None = None
    if args.fixture:
        league = FixtureLeague()
        members_repo, snapshots, prices = league, league, league
    else:
        deps = build_deps()
        settings = deps.settings
        members_repo = MemberAliasRepository(deps.conn)
        snapshots = SnapshotRepository(deps.conn)
        prices = PriceRepository(deps.conn)

    member = resolve_member(members_repo.all_members(), args.member)
    if member is None:
        print(f"unknown member: {args.member}", file=sys.stderr)
        return 2

    try:
        snapshot = snapshots.load(horizon_weeks=horizon_weeks(args.text))
    except SnapshotUnavailable as exc:
        print(f"no snapshot: {exc.reason}", file=sys.stderr)
        return 1

    # Built only where it is needed: `--json` never reaches a model, so it never
    # needs the Hermes CLI installed or the settings that name the profile.
    ai = None
    if not args.as_json:
        settings = settings or load_settings()
        ai = _client(settings)

    advisor = TradeAdvisor(
        settings,
        # No connection, no delivery service, no contact repository and no run
        # repository: this command cannot send, cannot write and cannot record a
        # run, because it holds nothing that could.
        None,
        ai,
        None,
        StderrNotifier(),
        None,
        members_repo,
        snapshots,
        prices,
        None,
    )

    if args.as_json:
        candidates = advisor.candidates_for(snapshot, member.member_id, args.text)
        print(json.dumps([candidate_json(c) for c in candidates], indent=2))
        return 0

    try:
        answer = advisor.answer(snapshot, member.member_id, args.text)
    except (AIUnavailable, AIInvalidOutput) as exc:
        # Only the class name: an invalid-output error chains a validation error
        # whose body quotes the model's answer back.
        print(exc.__class__.__name__, file=sys.stderr)
        return 1
    print(f"outcome: {answer.outcome}")
    print(f"model: {answer.model or NO_MODEL}")
    print()
    print(answer.text)
    return 0
