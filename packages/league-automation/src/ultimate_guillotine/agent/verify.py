"""Is the answer true? Every checkable claim, against a fresh snapshot.

Fact-checking, not list-matching. A player is where the answer says; a FAAB
figure is somebody's real balance or fits their real budget; no counterparty
is eliminated; every outside claim has an ``https`` source; and neither text
says a thing the league may never hear. Nothing about the *shape* of a
proposal is judged here -- an option, an insurance clause and a three-team
hold are all the agent's business -- so a creative answer fails only when it
is wrong about something.

Every problem is a sentence the agent can act on, because the retry envelope
hands the list straight back into the session.
"""

import re
from collections.abc import Callable, Mapping, Sequence

from ultimate_guillotine.advisor.state import AdvisorTeamState, LeagueSnapshot
from ultimate_guillotine.agent.answer import FREE_AGENT, LeagueAnswer, ProposalLeg
from ultimate_guillotine.agent.artifact import ARTIFACT_MAX_BYTES
from ultimate_guillotine.agent.tools.math import holdings_by_id
from ultimate_guillotine.agent.tools.names import (
    Ambiguous,
    PlayerInfo,
    Unknown,
    resolve_member,
    resolve_player,
)
from ultimate_guillotine.trades.models import MemberRef
from ultimate_guillotine.trades.names import normalize_name

_PHONE = re.compile(r"(?<!\d)\+?1?[\s.-]*\(?\d{3}\)?[\s.-]*\d{3}[\s.-]*\d{4}(?!\d)")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_CHAT = re.compile(r"iMessage;[+-];|SMS;[+-];", re.IGNORECASE)
_HASH = re.compile(r"\b[0-9a-f]{64}\b")
_DUES = re.compile(r"\bdues\b", re.IGNORECASE)

_PlayerOf = Callable[[str | None, str | None], PlayerInfo | None]
_CheckOnRoster = Callable[[PlayerInfo, str], None]


def privacy_problems(text: str, members: Sequence[MemberRef]) -> list[str]:
    """What in ``text`` may never reach the chat, each named once."""
    problems: list[str] = []
    if _PHONE.search(text):
        problems.append("a phone number")
    if _EMAIL.search(text):
        problems.append("an email address")
    if _CHAT.search(text):
        problems.append("a chat identifier")
    if _HASH.search(text):
        problems.append("a hash")
    if _DUES.search(text):
        problems.append("dues")
    words = set(normalize_name(text).split())
    for member in members:
        label = member.nickname or member.sleeper_display_name or member.display_name
        key = normalize_name(member.display_name)
        if key and key != normalize_name(label) and key in words:
            problems.append("a member's join key")
            break
    return problems


def _same_member(
    snapshot: LeagueSnapshot, members: Sequence[MemberRef], name: str, team: AdvisorTeamState
) -> bool:
    try:
        return resolve_member(name, snapshot, members).member_id == team.member_id
    except (Unknown, Ambiguous):
        return False


def verify(
    answer: LeagueAnswer,
    snapshot: LeagueSnapshot,
    members: Sequence[MemberRef],
    players: Mapping[str, PlayerInfo],
    *,
    artifact_text: str | None = None,
    artifact_bytes: int | None = None,
) -> list[str]:
    """Every problem with the answer, or an empty list."""
    problems: list[str] = []
    # One roster index per call; every "who holds him" below is a lookup in it.
    holdings = holdings_by_id(snapshot)

    def holder_of(player_id: str) -> AdvisorTeamState | None:
        held = holdings.get(player_id)
        return None if held is None else held[0]

    def player_of(name: str | None, player_id: str | None) -> PlayerInfo | None:
        token = player_id or name or ""
        try:
            if player_id and player_id in players:
                return players[player_id]
            return resolve_player(token, snapshot, players)
        except (Unknown, Ambiguous) as exc:
            problems.append(f"{token}: {exc}")
            return None

    def check_on_roster(info: PlayerInfo, member: str) -> None:
        holder = holder_of(info.sleeper_player_id)
        if holder is None:
            problems.append(f"{info.full_name} is not on any roster")
        elif not _same_member(snapshot, members, member, holder):
            problems.append(
                f"{info.full_name} is on {holder.member_label}'s roster, not {member}'s"
            )

    for fact in answer.facts.players:
        info = player_of(fact.name, fact.player_id)
        if info is None:
            continue
        if normalize_name(fact.holder) == normalize_name(FREE_AGENT):
            holder = holder_of(info.sleeper_player_id)
            if holder is not None:
                problems.append(
                    f"{info.full_name} is not a free agent: {holder.member_label} holds him"
                )
        else:
            check_on_roster(info, fact.holder)

    for fact in answer.facts.faab:
        try:
            team = resolve_member(fact.member, snapshot, members)
        except (Unknown, Ambiguous) as exc:
            problems.append(str(exc))
            continue
        if fact.claim == "balance" and fact.amount != team.faab_remaining:
            problems.append(
                f"{team.member_label}'s FAAB is {team.faab_remaining}, not {fact.amount}"
            )
        if fact.claim == "offer" and fact.amount > team.faab_remaining:
            problems.append(
                f"an offer of {fact.amount} FAAB is over {team.member_label}'s budget of "
                f"{team.faab_remaining}"
            )

    for proposal in answer.facts.proposals:
        for name in proposal.counterparties:
            try:
                team = resolve_member(name, snapshot, members)
            except (Unknown, Ambiguous) as exc:
                problems.append(str(exc))
                continue
            if team.is_eliminated:
                problems.append(f"{team.member_label} is eliminated and cannot be a counterparty")
        for leg in proposal.legs:
            _check_leg(leg, snapshot, members, player_of, check_on_roster, problems)

    if answer.report is not None:
        for source in answer.report.sources:
            if not source.url.startswith("https://"):
                problems.append(f"source is not https: {source.url}")
    if artifact_bytes is not None and artifact_bytes > ARTIFACT_MAX_BYTES:
        problems.append(f"the write-up is over {ARTIFACT_MAX_BYTES} bytes")

    problems.extend(
        f"the chat text mentions {p}" for p in privacy_problems(answer.chat_text, members)
    )
    if artifact_text:
        problems.extend(
            f"the write-up mentions {p}" for p in privacy_problems(artifact_text, members)
        )
    return problems


def _check_leg(
    leg: ProposalLeg,
    snapshot: LeagueSnapshot,
    members: Sequence[MemberRef],
    player_of: _PlayerOf,
    check_on_roster: _CheckOnRoster,
    problems: list[str],
) -> None:
    if leg.kind == "player":
        info = player_of(leg.player_name, leg.player_id)
        if info is not None:
            check_on_roster(info, leg.from_member)
    elif leg.kind in ("faab", "draft_dollars") and leg.amount is not None:
        try:
            team = resolve_member(leg.from_member, snapshot, members)
        except (Unknown, Ambiguous) as exc:
            problems.append(str(exc))
            return
        faab = leg.amount * 5 if leg.kind == "draft_dollars" else leg.amount
        if faab > team.faab_remaining:
            problems.append(
                f"an offer of {faab} FAAB is over {team.member_label}'s budget of "
                f"{team.faab_remaining}"
            )
