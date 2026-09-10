"""Who a name means. Resolved here, in the tools, never guessed by the model.

Exactly one match resolves. None raises :class:`Unknown` with a hint the agent
can relay -- the league's labels, so a misspelt member can be corrected -- and
two or more raises :class:`Ambiguous` listing the candidates, so the agent asks
rather than picks. Every string a member is matched by is normalized with the
same :func:`~ultimate_guillotine.trades.names.normalize_name` the Registrar
uses; every string handed back is a public label.

A player is matched in two tiers. The *exact* tier compares the whole name,
and there a name shared by a rostered player and a free agent resolves to the
rostered one: he is the one the league can act on, and Sleeper's directory
carries namesakes nobody in the league holds. The *partial* tier matches one
whole word of the name -- a surname -- and there more than one candidate is
always ambiguous: "Allen" with Josh Allen rostered and Keenan Allen free is a
question, not a guess. The candidates are listed rostered-first, each with his
holder or "free agent", up to :data:`MAX_CANDIDATES` and a count of the rest.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ultimate_guillotine.agent.tools.snapshot import LeagueSnapshot, LeagueTeamState
from ultimate_guillotine.trades.models import MemberRef
from ultimate_guillotine.trades.names import normalize_name


@dataclass(frozen=True)
class PlayerInfo:
    sleeper_player_id: str
    full_name: str
    position: str | None
    team: str | None
    injury_status: str | None


class Unknown(LookupError):
    def __init__(self, token: str, hint: Sequence[str] = ()) -> None:
        self.token, self.hint = token, list(hint)
        tail = f" Known: {', '.join(self.hint)}." if self.hint else ""
        super().__init__(f"No match for '{token}'.{tail}")


#: How many candidates an :class:`Ambiguous` lists before counting the rest.
MAX_CANDIDATES = 8


class Ambiguous(LookupError):
    def __init__(self, token: str, candidates: Sequence[str], omitted: int = 0) -> None:
        self.token, self.candidates, self.omitted = token, list(candidates), omitted
        listed = ", ".join(self.candidates)
        if omitted:
            listed += f", and {omitted} more"
        super().__init__(f"'{token}' could mean any of: {listed}. Ask which one.")


def member_keys(team: LeagueTeamState, ref: MemberRef | None) -> set[str]:
    keys = {team.member_label, team.display_name, team.team_name}
    if ref is not None:
        keys |= set(ref.aliases)
        keys |= {ref.nickname or "", ref.sleeper_display_name or ""}
    return {normalize_name(key) for key in keys if key}


def resolve_member(
    token: str, snapshot: LeagueSnapshot, members: Sequence[MemberRef]
) -> LeagueTeamState:
    wanted = normalize_name(token)
    labels = sorted(team.member_label for team in snapshot.teams)
    if not wanted:
        raise Unknown(token, labels)
    refs = {ref.member_id: ref for ref in members}
    matches = [t for t in snapshot.teams if wanted in member_keys(t, refs.get(t.member_id))]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise Unknown(token, labels)
    raise Ambiguous(token, sorted({team.member_label for team in matches}))


def player_pool(
    snapshot: LeagueSnapshot, players: Mapping[str, PlayerInfo]
) -> dict[str, PlayerInfo]:
    """Every known player: the directory, plus any rostered player it lacks."""
    pool = dict(players)
    for team in snapshot.teams:
        for holding in team.holdings:
            pool.setdefault(
                holding.sleeper_player_id,
                PlayerInfo(holding.sleeper_player_id, holding.player_name, holding.position,
                           None, None),
            )
    return pool


def _describe(player: PlayerInfo, holder: str | None) -> str:
    where = f"on {holder}'s roster" if holder else "free agent"
    return f"{player.full_name} ({player.position or '?'}, {player.team or 'no team'}, {where})"


def _ambiguous(token: str, found: list[PlayerInfo], holders: Mapping[str, str]) -> Ambiguous:
    """The candidates rostered-first, so a truncated list still shows the likely ones."""

    def rank(player: PlayerInfo) -> tuple[bool, str, str]:
        return (
            player.sleeper_player_id not in holders,
            normalize_name(player.full_name),
            player.sleeper_player_id,
        )

    ordered = sorted(found, key=rank)
    shown = [_describe(p, holders.get(p.sleeper_player_id)) for p in ordered[:MAX_CANDIDATES]]
    return Ambiguous(token, shown, omitted=len(ordered) - len(shown))


def resolve_player(
    token: str, snapshot: LeagueSnapshot, players: Mapping[str, PlayerInfo]
) -> PlayerInfo:
    wanted = normalize_name(token)
    if not wanted:
        raise Unknown(token)
    pool = player_pool(snapshot, players)
    holders = {h.sleeper_player_id: t.member_label for t in snapshot.teams for h in t.holdings}

    exact = [p for p in pool.values() if normalize_name(p.full_name) == wanted]
    if len(exact) > 1:
        # A shared exact name: the rostered namesake is the one the league can act on.
        exact = [p for p in exact if p.sleeper_player_id in holders] or exact
    if len(exact) == 1:
        return exact[0]
    if exact:
        raise _ambiguous(token, exact, holders)
    partial = [p for p in pool.values() if f" {wanted} " in f" {normalize_name(p.full_name)} "]
    if len(partial) == 1:
        return partial[0]
    if not partial:
        raise Unknown(token)
    raise _ambiguous(token, partial, holders)
