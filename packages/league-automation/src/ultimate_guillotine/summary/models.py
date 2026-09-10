"""The shapes the EOD summary is built from.

Read shapes, like the Advisor's: a starter here carries his NFL team, his injury
flag, his points so far and where his game stands, none of which the sync's
write shapes know. Points and projections stay ``Decimal`` to the renderer, as
everywhere else in the package; the Monte Carlo converts to ``float`` at its own
boundary and never hands a float back out.

Nothing here reads, writes, or decides. ``lineup.py`` builds the starters,
``phase.py`` the phase, ``survival.py`` the odds, ``snapshot.py`` the whole
snapshot, and ``render.py`` turns a packet into the message.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

#: The league's clock: rule deadlines are written in Central time, and so is the
#: post. Every stored timestamp stays UTC; this is for "today" and for display.
LOCAL_TZ = ZoneInfo("America/Chicago")

#: Where one starter slot stands tonight. ``remaining`` and ``live`` are the two
#: that can still add points; everything else is settled.
StarterStatus = Literal["empty", "out", "bye", "done", "remaining", "live"]

#: The statuses whose player can still score this week.
PENDING_STATUSES: frozenset[str] = frozenset({"remaining", "live"})

#: What kind of week the rules make this one -- the season simulation table in
#: ``docs/rules/ultimate-guillotine-gulag-league-rules.docx``.
PhaseKind = Literal["entry", "gulag", "double", "cut", "final", "over"]

#: Where this week's gulag pairing came from. ``replay`` is provisional; ``events``
#: is the Adjudicator's ruling; ``unknown`` means a replay was needed and a past
#: week's scores are missing; ``none`` means the phase has no gulag at all.
GulagSource = Literal["events", "replay", "unknown", "none"]

#: The bad thing that can happen to a team this week, by the rules phase.
AdverseEvent = Literal["gulag_entry", "gulag_loss", "cut", "title_loss"]

#: What the header says about the week: nothing has kicked off, some games are
#: final and some to come, every game is over, or the schedule could not say.
DayState = Literal["outlook", "midweek", "final", "unknown"]


@dataclass(frozen=True)
class PlayerInfo:
    """The two directory columns a starter line needs beyond the roster."""

    nfl_team: str | None
    injury_status: str | None


@dataclass(frozen=True)
class StarterLine:
    """One starter slot: who is in it, what he has scored, and where his game stands.

    ``sleeper_player_id`` is ``None`` for an empty slot, which is a line of its own
    rather than an absence so the renderer can say the slot is empty. ``points`` is
    what he has scored so far this week, zero when nothing is on the board for him;
    ``projected`` is Sleeper's number for the whole week, ``None`` when there is not
    one -- never zero.
    """

    sleeper_player_id: str | None
    name: str
    position: str | None
    lineup_position: str | None
    nfl_team: str | None
    injury_status: str | None
    projected: Decimal | None
    points: Decimal
    status: StarterStatus

    @property
    def is_pending(self) -> bool:
        return self.status in PENDING_STATUSES


@dataclass(frozen=True)
class TeamLine:
    """One team tonight: its public label, its score, and its lineup slot by slot.

    ``label`` is the league's one public name for the owner --
    ``coalesce(nickname, sleeper_display_name, display_name)`` -- and the join key
    is deliberately not carried, so nothing downstream can print it.
    """

    team_id: int
    member_id: int
    label: str
    team_name: str
    faab_remaining: int
    is_eliminated: bool
    eliminated_week: int | None
    #: The team's total so far, as Sleeper scored it. Zero before kickoff.
    points: Decimal
    starters: tuple[StarterLine, ...]
    scores_synced_at: datetime | None
    #: False when ``team_week_scores`` has no row for this team this week, so the
    #: zero above is an absence rather than a score.
    has_score_row: bool

    def pending(self) -> tuple[StarterLine, ...]:
        return tuple(s for s in self.starters if s.is_pending)

    def unprojected_pending(self) -> tuple[StarterLine, ...]:
        return tuple(s for s in self.pending() if s.projected is None)

    def empty_slots(self) -> int:
        return sum(1 for s in self.starters if s.status == "empty")

    def out_starters(self) -> tuple[StarterLine, ...]:
        return tuple(s for s in self.starters if s.status == "out")


@dataclass(frozen=True)
class Phase:
    """This week's rules phase and gulag pairing."""

    week: int
    kind: PhaseKind
    gulag_team_ids: tuple[int, ...]
    gulag_source: GulagSource


@dataclass(frozen=True)
class TeamOdds:
    """One team's estimate: the event that would end its week, and the chance of it."""

    team_id: int
    adverse_event: AdverseEvent
    probability: Decimal
    projected_final: Decimal
    pending: int
    #: True when a pending starter had no projection and was simulated at his
    #: position's median instead.
    is_estimated: bool


@dataclass(frozen=True)
class SurvivalResult:
    model_version: str
    simulations: int
    seed: int
    input_hash: str
    teams: Mapping[int, TeamOdds]


@dataclass(frozen=True)
class Move:
    """One executed transaction, as the moves line says it."""

    kind: str
    occurred_at: datetime
    team_label: str
    adds: tuple[str, ...]
    drops: tuple[str, ...]
    waiver_bid: int | None


@dataclass(frozen=True)
class EodSnapshot:
    """Everything one summary is built from, read once."""

    season: int
    season_id: int
    week: int
    teams: tuple[TeamLine, ...]
    phase: Phase
    day_state: DayState
    games_final: int
    games_total: int
    schedule_available: bool
    moves: tuple[Move, ...]
    #: The newest stamp across the data layer components the snapshot read.
    data_synced_at: datetime
    #: The newest ``team_week_scores.synced_at`` for the week, or ``None`` with no rows.
    scores_synced_at: datetime | None
    starter_slots: int

    def live_teams(self) -> tuple[TeamLine, ...]:
        return tuple(t for t in self.teams if not t.is_eliminated)

    def team(self, team_id: int) -> TeamLine:
        for team in self.teams:
            if team.team_id == team_id:
                return team
        raise KeyError(team_id)


@dataclass(frozen=True)
class EodPacket:
    """A snapshot plus the odds computed over it, or the reason there are none."""

    snapshot: EodSnapshot
    result: SurvivalResult | None
    coverage_pct: Decimal
    #: Why ``result`` is ``None``, in words the footer can use; ``None`` when it is not.
    no_odds_reason: str | None
