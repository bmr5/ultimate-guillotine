"""Who a name means. Resolved here, in the tools, never guessed by the model.

Exactly one match resolves. None raises :class:`Unknown` with a hint the agent
can relay -- the league's labels, so a misspelt member can be corrected -- and
two or more raises :class:`Ambiguous` listing the candidates, so the agent asks
rather than picks. Every string a member is matched by is normalized with the
same :func:`~ultimate_guillotine.trades.names.normalize_name` the Registrar
uses; every string handed back is a public label.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ultimate_guillotine.advisor.state import AdvisorTeamState, LeagueSnapshot
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


class Ambiguous(LookupError):
    def __init__(self, token: str, candidates: Sequence[str]) -> None:
        self.token, self.candidates = token, list(candidates)
        super().__init__(
            f"'{token}' could mean any of: {', '.join(self.candidates)}. Ask which one."
        )


def member_keys(team: AdvisorTeamState, ref: MemberRef | None) -> set[str]:
    keys = {team.member_label, team.display_name, team.team_name}
    if ref is not None:
        keys |= set(ref.aliases)
        keys |= {ref.nickname or "", ref.sleeper_display_name or ""}
    return {normalize_name(key) for key in keys if key}


def resolve_member(
    token: str, snapshot: LeagueSnapshot, members: Sequence[MemberRef]
) -> AdvisorTeamState:
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


def _describe(player: PlayerInfo) -> str:
    return f"{player.full_name} ({player.position or '?'}, {player.team or 'no team'})"


def resolve_player(
    token: str, snapshot: LeagueSnapshot, players: Mapping[str, PlayerInfo]
) -> PlayerInfo:
    wanted = normalize_name(token)
    if not wanted:
        raise Unknown(token)
    pool = player_pool(snapshot, players)
    rostered = {h.sleeper_player_id for t in snapshot.teams for h in t.holdings}

    def prefer_rostered(found: list[PlayerInfo]) -> list[PlayerInfo]:
        on_rosters = [p for p in found if p.sleeper_player_id in rostered]
        return on_rosters if len(found) > 1 and on_rosters else found

    exact = prefer_rostered([p for p in pool.values() if normalize_name(p.full_name) == wanted])
    if len(exact) == 1:
        return exact[0]
    if exact:
        raise Ambiguous(token, [_describe(p) for p in exact])
    partial = prefer_rostered([
        p for p in pool.values()
        if f" {wanted} " in f" {normalize_name(p.full_name)} "
    ])
    if len(partial) == 1:
        return partial[0]
    if not partial:
        raise Unknown(token)
    raise Ambiguous(token, [_describe(p) for p in partial[:8]])
