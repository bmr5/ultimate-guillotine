"""Starter classification: who has played, who is left, who is out, who is missing.

**The out rule is the board's.** ``apps/web/src/board/derive/availability.ts``
decides who the site calls out: a status in the unavailable set is out whatever
the projection, and any other known flag -- ``Questionable``, ``Doubtful``,
``NA`` -- is out once Sleeper has withdrawn the number behind it. The same two
limbs are restated here so the chat and the site never disagree about who is
playing, and a flag this build has never read never takes anyone out of a lineup,
which is the sync's call too (``KNOWN_INJURY_STATUSES`` in ``sleeper/players.py``).

**Coverage is measured over the players who can still score.** The data layer's
coverage counts every filled slot, out starters included, which is right for the
board and wrong for odds: nobody can project a player who is not playing, and a
game already over needs no projection at all. The 95 percent gate the Game Pulse
spec names is over rostered *unplayed* starters, and that is what
:func:`coverage_pct` measures.
"""

from collections.abc import Iterable, Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal
from statistics import median

from ultimate_guillotine.sleeper.players import KNOWN_INJURY_STATUSES
from ultimate_guillotine.summary.models import PlayerInfo, StarterLine, StarterStatus, TeamLine
from ultimate_guillotine.summary.schedule import Game, game_state

#: The statuses that mean the player is not on the field this week -- the board's
#: ``UNAVAILABLE_STATUSES``, verbatim.
UNAVAILABLE_STATUSES: frozenset[str] = frozenset({"Out", "IR", "PUP", "Sus", "COV", "DNR"})

_CENTS = Decimal("0.01")


def _status(raw: str | None) -> str | None:
    status = (raw or "").strip()
    return status or None


def is_out(injury_status: str | None, projected: Decimal | None) -> bool:
    """Whether this starter is out this week, by either limb of the board's rule."""
    status = _status(injury_status)
    if status is None:
        return False
    if status in UNAVAILABLE_STATUSES:
        return True
    return projected is None and status in KNOWN_INJURY_STATUSES


def classify_starter(
    injury_status: str | None,
    projected: Decimal | None,
    nfl_team: str | None,
    week_games: Mapping[str, Game],
    schedule_available: bool,
) -> StarterStatus:
    """Where one filled starter slot stands.

    Out comes first, whatever his game is doing. Without a schedule nobody can be
    called done, so every fit starter is ``remaining`` and the caller withholds the
    odds. A player the directory has no team for cannot have his game found: with a
    projection he keeps his variance, without one there is nothing to wait for.
    """
    if is_out(injury_status, projected):
        return "out"
    if not schedule_available:
        return "remaining"
    if nfl_team is None:
        return "remaining" if projected is not None else "done"
    game = week_games.get(nfl_team)
    if game is None:
        return "bye"
    return game_state(game)


def _points(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return Decimal(0)
    return Decimal(str(value)).quantize(_CENTS, rounding=ROUND_HALF_UP)


def build_starters(
    holdings: Iterable,
    *,
    players: Mapping[str, PlayerInfo],
    points: Mapping[str, object],
    week_games: Mapping[str, Game],
    schedule_available: bool,
    starter_slots: int,
) -> tuple[StarterLine, ...]:
    """One line per starter slot, in lineup order, empties last.

    ``holdings`` are the snapshot's starter holdings
    (:class:`~ultimate_guillotine.advisor.state.AdvisorHolding`): a player id, a
    name, a position, a lineup slot, and this week's projection. ``players`` is the
    directory's team and flag for each, ``points`` the per-starter map off the
    scores row. A slot the manager left blank is a line of its own so the roster
    watch can say so.
    """
    ordered = sorted(
        holdings, key=lambda h: (h.slot_index if h.slot_index is not None else 10_000)
    )
    lines: list[StarterLine] = []
    for holding in ordered:
        info = players.get(holding.sleeper_player_id, PlayerInfo(None, None))
        projected = holding.projected_now
        lines.append(
            StarterLine(
                sleeper_player_id=holding.sleeper_player_id,
                name=holding.player_name,
                position=holding.position,
                lineup_position=holding.lineup_position,
                nfl_team=info.nfl_team,
                injury_status=_status(info.injury_status),
                projected=projected,
                points=_points(points.get(holding.sleeper_player_id)),
                status=classify_starter(
                    info.injury_status, projected, info.nfl_team, week_games, schedule_available
                ),
            )
        )
    for _ in range(max(starter_slots - len(lines), 0)):
        lines.append(
            StarterLine(
                sleeper_player_id=None,
                name="empty slot",
                position=None,
                lineup_position=None,
                nfl_team=None,
                injury_status=None,
                projected=None,
                points=Decimal(0),
                status="empty",
            )
        )
    return tuple(lines)


def coverage_pct(teams: Sequence[TeamLine]) -> Decimal:
    """Share of pending starters on live teams that carry a projection.

    Nothing pending is full coverage, not zero: on a Tuesday night after the last
    game there is nobody left to project.
    """
    pending = [s for t in teams if not t.is_eliminated for s in t.pending()]
    if not pending:
        return Decimal("100.00")
    projected = sum(1 for s in pending if s.projected is not None)
    share = Decimal(projected) / Decimal(len(pending)) * Decimal(100)
    return share.quantize(_CENTS, rounding=ROUND_HALF_UP)


def position_medians(teams: Sequence[TeamLine]) -> dict[str, Decimal]:
    """The median projection at each position, over every projected starter.

    What a pending starter with no projection is simulated at, so one missing
    number costs one team an estimate mark rather than the league its odds.
    """
    by_position: dict[str, list[Decimal]] = {}
    for team in teams:
        for starter in team.starters:
            if starter.projected is None or starter.position is None:
                continue
            by_position.setdefault(starter.position, []).append(starter.projected)
    return {position: Decimal(median(values)) for position, values in by_position.items()}
