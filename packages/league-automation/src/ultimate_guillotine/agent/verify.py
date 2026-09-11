"""Is the answer true? Every checkable claim, against a fresh snapshot.

Fact-checking, not list-matching. A player is where the answer says; a FAAB
figure is somebody's real balance or fits their real budget; no counterparty
is eliminated; every outside claim has an ``https`` source; and neither text
says a thing the league may never hear. Nothing about the *shape* of a
proposal is judged here -- an option, an insurance clause and a three-team
hold are all the agent's business -- so a creative answer fails only when it
is wrong about something.

Every problem is a sentence the agent can act on, because the retry envelope
hands the list straight back into the session -- and the worker may copy the
list into the ops notes verbatim, so no sentence repeats a token the model
wrote. A player is named by his ``full_name`` and a member by their
``member_label``, the league's one public label; a name that resolves to
neither is described by where it sat ("the holder given for Bench 05-0")
rather than quoted. As a last guard the fact sentences go through
:func:`privacy_problems` themselves, and one that trips it is replaced by
:data:`UNPUBLISHED`.
"""

import re
from collections.abc import Mapping, Sequence

from ultimate_guillotine.agent.answer import FREE_AGENT, LeagueAnswer
from ultimate_guillotine.agent.artifact import ARTIFACT_MAX_BYTES
from ultimate_guillotine.agent.tools.math import holdings_by_id
from ultimate_guillotine.agent.tools.names import (
    Ambiguous,
    PlayerInfo,
    Unknown,
    player_pool,
    resolve_member,
    resolve_player,
)
from ultimate_guillotine.agent.tools.snapshot import LeagueSnapshot, LeagueTeamState
from ultimate_guillotine.trades.models import MemberRef
from ultimate_guillotine.trades.names import normalize_name

_PHONE = re.compile(r"(?<!\d)\+?1?[\s.-]*\(?\d{3}\)?[\s.-]*\d{3}[\s.-]*\d{4}(?!\d)")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_CHAT = re.compile(r"iMessage;[+-];|SMS;[+-];", re.IGNORECASE)
_HASH = re.compile(r"\b[0-9a-f]{64}\b")
_DUES = re.compile(r"\bdues\b", re.IGNORECASE)

#: What replaces a fact sentence that would itself say something unpublished.
UNPUBLISHED = "a check failed on a fact that named something the league does not publish"


def _privacy_name(text: str) -> str:
    # Preserve word boundaries around possessives and URL separators. Apply the
    # same normalization to the text, the private key and its public label.
    return normalize_name(re.sub(r"[^\w\s]", " ", text))

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
    # A phrase match, so a multi-word key is caught whole and a possessive is
    # caught at all. A key that is the member's public label is not a leak:
    # the label is what the league says.
    haystack = f" {_privacy_name(text)} "
    for member in members:
        label = member.nickname or member.sleeper_display_name or member.display_name
        key = _privacy_name(member.display_name)
        public = _privacy_name(label)
        if key and key != public and f" {key} " in haystack:
            problems.append("a member's join key")
            break
    return problems


def _unresolved_member(subject: str, exc: Unknown | Ambiguous) -> str:
    """The sentence for a member name that did not resolve; the name stays unsaid."""
    if isinstance(exc, Ambiguous):
        return f"{subject} could mean more than one member; ask which"
    return f"{subject} matches no member; name members by their league label"


def _unresolved_player(subject: str, exc: Unknown | Ambiguous) -> str:
    if isinstance(exc, Ambiguous):
        return f"{subject} could mean more than one player; ask which"
    return f"{subject} matches no known player; name players by their full name"


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
    # One roster index and one player pool per call; every lookup below is in them.
    holdings = holdings_by_id(snapshot)
    pool = player_pool(snapshot, players)

    def holder_of(player_id: str) -> LeagueTeamState | None:
        held = holdings.get(player_id)
        return None if held is None else held[0]

    def player_of(player_id: str | None, name: str | None, subject: str) -> PlayerInfo | None:
        """Resolve every supplied identity and require them to agree."""
        try:
            by_id = pool.get(player_id) if player_id else None
            if player_id and by_id is None:
                problems.append(f"{subject} has an unknown player id")
                return None
            by_name = resolve_player(name, snapshot, pool) if name else None
            if by_id and by_name and by_id.sleeper_player_id != by_name.sleeper_player_id:
                problems.append(f"{subject} has a player id and name that disagree")
                return None
            return by_id or by_name or resolve_player("", snapshot, pool)
        except (Unknown, Ambiguous) as exc:
            problems.append(_unresolved_player(subject, exc))
            return None

    def member_of(token: str, subject: str) -> LeagueTeamState | None:
        try:
            return resolve_member(token, snapshot, members)
        except (Unknown, Ambiguous) as exc:
            problems.append(_unresolved_member(subject, exc))
            return None

    def check_on_roster(info: PlayerInfo, member: str, subject: str) -> None:
        holder = holder_of(info.sleeper_player_id)
        if holder is None:
            problems.append(f"{info.full_name} is not on any roster")
            return
        team = member_of(member, subject)
        if team is not None and team.member_id != holder.member_id:
            problems.append(
                f"{info.full_name} is on {holder.member_label}'s roster, "
                f"not {team.member_label}'s"
            )

    for fact in answer.facts.players:
        info = player_of(fact.player_id, fact.name, "a player in the facts")
        if info is None:
            continue
        if normalize_name(fact.holder) == normalize_name(FREE_AGENT):
            holder = holder_of(info.sleeper_player_id)
            if holder is not None:
                problems.append(
                    f"{info.full_name} is not a free agent: {holder.member_label} holds him"
                )
        else:
            check_on_roster(info, fact.holder, f"the holder given for {info.full_name}")

    for fact in answer.facts.faab:
        team = member_of(fact.member, "the member given for a FAAB figure")
        if team is None:
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
        participants = {}
        names = [*proposal.counterparties,
                 *(name for leg in proposal.legs for name in (leg.from_member, leg.to_member))]
        for name in dict.fromkeys(names):
            team = member_of(name, f'a counterparty in proposal "{proposal.title}"')
            participants[name] = team
            if team is not None and team.is_eliminated:
                problems.append(f"{team.member_label} is eliminated and cannot be a counterparty")
        balances = {t.member_id: t.faab_remaining for t in participants.values() if t}
        for leg in proposal.legs:
            sender, recipient = participants[leg.from_member], participants[leg.to_member]
            if leg.kind == "player":
                info = player_of(leg.player_id, leg.player_name, "a player in the proposal")
                if info is not None and sender is not None:
                    check_on_roster(info, leg.from_member, "the member giving the player")
            elif leg.kind in ("faab", "draft_dollars") and leg.amount is not None:
                amount = leg.amount * 5 if leg.kind == "draft_dollars" else leg.amount
                if sender is not None:
                    balances[sender.member_id] -= amount
                if recipient is not None:
                    balances[recipient.member_id] += amount
        for member_id, balance in balances.items():
            if balance < 0:
                team = snapshot.team_for_member(member_id)
                assert team is not None
                problems.append(f"the proposal is over {team.member_label}'s budget by "
                                f"{-balance} FAAB")

    if answer.report is not None:
        for source in answer.report.sources:
            if not source.url.startswith("https://"):
                problems.append(f"source is not https: {source.url}")
    if artifact_bytes is not None and artifact_bytes > ARTIFACT_MAX_BYTES:
        problems.append(f"the write-up is over {ARTIFACT_MAX_BYTES} bytes")

    # Belt and braces: a fact sentence can carry a title or a URL the model wrote,
    # so one that would itself say something unpublished is replaced. The privacy
    # findings below are exempt -- "mentions dues" is a finding, not dues.
    problems = list(dict.fromkeys(
        UNPUBLISHED if privacy_problems(p, members) else p for p in problems
    ))
    problems.extend(
        f"the chat text mentions {p}" for p in privacy_problems(answer.chat_text, members)
    )
    if artifact_text:
        problems.extend(
            f"the write-up mentions {p}" for p in privacy_problems(artifact_text, members)
        )
    return problems
