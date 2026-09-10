"""`ug advisor ask`: run the whole Advisor pipeline and print, never send.

The point of this command is that it is *impossible* for it to post. It builds a
:class:`~ultimate_guillotine.advisor.skill.TradeAdvisor` with no delivery
service, no run repository and no database connection, and calls
:meth:`~ultimate_guillotine.advisor.skill.TradeAdvisor.answer_message`, which
reserves nothing, commits nothing and delivers nothing. A prompt change or a
scoring change can be checked against the real league without the chat ever
seeing it, by construction rather than by discipline.

``answer_message`` is also the listener's own entry point, and this command adds
no check of its own and skips none: a hostile question, a stale snapshot, a
member with no team this season and a question asked after the deadline are
refused here exactly as they are refused in the chat, in the same words. A dry
run that answered something the chat would have refused would be a dry run of a
different skill. That holds on both paths: ``--json`` never reaches
``answer_message``, so it calls
:meth:`~ultimate_guillotine.advisor.skill.TradeAdvisor.gate` -- the guards
``answer_message`` itself runs -- and prints the refusal in place of a board. A
question the chat would refuse never gets a candidate set built for it here.

Two flags shape what it costs. ``--json`` prints the candidate set instead of
the advice, which is the whole of what the model would have been handed and
makes **no model call at all**. ``--fixture`` answers out of
:mod:`ultimate_guillotine.advisor.fixture` -- the closed-form 18-team league the
Advisor is tested against -- so the command runs on a machine with no database,
no Sleeper sync and no league data, which is what a prompt change usually wants
to be tried against first. Together they are free and offline.

The asker is named on the command line rather than matched from a message, so no
contact repository is built and no handle is hashed. ``--as`` matches a display
name or any of the member's aliases; an alias is matched but never printed back,
the same rule ``ug members`` follows. Every match is collected rather than the
first one taken: two members answering to one nickname is a roster problem, and
answering as whichever of them the query happened to sort first would hide it.

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
from ultimate_guillotine.advisor.skill import TradeAdvisor
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
        help=(
            "print the candidate set the model would be handed, or the refusal "
            "the gates gave; makes no model call"
        ),
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
            MemberRef(team.member_id, team.member_label, ()) for team in fixture_snapshot().teams
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


def matching_members(members, wanted: str) -> list[MemberRef]:
    """Every member a display name or an alias matches, the way resolution does.

    Normalized on both sides, so ``member18``, ``Member18`` and ``Member 18``
    are one member and the operator does not have to spell a nickname the way
    the roster stores it. All of them rather than the first: an alias two
    members both answer to makes "as whom?" a question the command cannot
    answer, and picking one would answer it silently and wrongly half the time.
    :func:`~ultimate_guillotine.trades.resolve.resolve_member` breaks the same
    tie from the players a trade names; a dry run has no evidence like that in
    hand, so it says so and stops.
    """
    target = normalize_name(wanted)
    matched = []
    for member in members:
        keys = {normalize_name(member.display_name)}
        keys |= {normalize_name(alias) for alias in member.aliases}
        if target in keys:
            matched.append(member)
    return matched


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


class LazyClient:
    """The Advisor's own client, built by the first question that needs one.

    Built at all rather than through `build_ai` so a dry run and the listener ask
    the same model the same way, with the Advisor's own timeout; a missing CLI is
    a setup problem, and a plain message beats a traceback out of `subprocess`.

    Built *late* because most outcomes never call a model: a refusal, a sender
    with no roster, a stale snapshot, a passed deadline and an empty board are
    each one fixed line, and a dry run of one of those must not need the Hermes
    CLI installed or a configured league to read a profile out of. It is also
    what makes "a hostile ``--text`` never reaches a model" a thing an operator
    can see rather than take on trust: on a machine with no Hermes at all, the
    refusal still prints and the command still exits 0.
    """

    def __init__(self, settings: Settings | None) -> None:
        self._settings = settings
        self._client = None

    def parse(self, system: str, user: str, schema, schema_name: str):
        if self._client is None:
            # The binary first: it is the failure an operator can fix without
            # reading a stack trace, and `--fixture` has no settings to load
            # until something actually wants a profile out of them.
            if find_hermes_binary() is None:
                raise SystemExit("hermes CLI not found")
            settings = self._settings or load_settings()
            self._client = advisor_client(settings.hermes_profile_home, model=settings.hermes_model)
        return self._client.parse(system, user, schema, schema_name)


def _print_answer(outcome: str, model: str | None, text: str) -> None:
    """One answer, printed the one way, whichever flag asked for it.

    A refusal reads the same under ``--json`` as it does without it, because it
    is the same refusal: the outcome, the model that was never called, and the
    words the chat would have sent.
    """
    print(f"outcome: {outcome}")
    print(f"model: {model or NO_MODEL}")
    print()
    print(text)


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

    matched = matching_members(members_repo.all_members(), args.member)
    if not matched:
        print(f"unknown member: {args.member}", file=sys.stderr)
        return 2
    if len(matched) > 1:
        print(f"ambiguous member: {args.member}", file=sys.stderr)
        return 2
    member = matched[0]

    advisor = TradeAdvisor(
        settings,
        # No connection, no delivery service, no contact repository and no run
        # repository: this command cannot send, cannot write and cannot record a
        # run, because it holds nothing that could. `--json` gets no client at
        # all, since it never reaches the point of asking one anything.
        None,
        None if args.as_json else LazyClient(settings),
        None,
        StderrNotifier(),
        None,
        members_repo,
        snapshots,
        prices,
        None,
    )

    try:
        if args.as_json:
            # The same guards `answer_message` runs, in the same order, on the
            # path that never calls it: a hostile question, a stale snapshot or
            # a passed deadline is printed as the refusal it is, and no board is
            # built for a question the chat would not have answered.
            refusal, snapshot = advisor.gate(args.text, member)
            if refusal is not None:
                _print_answer(refusal.outcome, None, refusal.text)
                return 0
            candidates = advisor.candidates_for(snapshot, member.member_id, args.text)
            print(json.dumps([candidate_json(c) for c in candidates], indent=2))
            return 0
        answer = advisor.answer_message(args.text, member)
    except SnapshotUnavailable as exc:
        print(f"no snapshot: {exc.reason}", file=sys.stderr)
        return 1
    except (AIUnavailable, AIInvalidOutput) as exc:
        # Only the class name: an invalid-output error chains a validation error
        # whose body quotes the model's answer back.
        print(exc.__class__.__name__, file=sys.stderr)
        return 1
    _print_answer(answer.outcome, answer.model, answer.text)
    return 0
