"""A deterministic 18-team league, the one every Advisor test reasons about.

Team 1 is the strongest and team 18 sits on the cut line, strictly monotone, so
the pressure order is known by construction: pressure rank N is member N
counting up from the bottom. Team 17 is eliminated, which is what the
"never propose a trade with an eliminated team" tests need. Projections and
FAAB come from closed formulas rather than a data file: a reviewer can compute
any expected number by hand from the two functions below.

Below the coverage gate the league goes dark, not fuzzy: every team's total
*and* every holding's points come back ``None``, because the data layer withholds
a projection it cannot stand behind rather than showing a partial one. That is
what makes the counting fallback -- rank a roster by bodies when it has no
numbers -- an exercised path in the tests rather than dead code.
"""

from datetime import UTC, datetime

from ultimate_guillotine.advisor.state import AdvisorHolding, AdvisorTeamState, LeagueSnapshot

FIXTURE_SYNCED_AT = datetime(2026, 10, 8, 15, 0, tzinfo=UTC)
FIXTURE_SEASON = 2026
FIXTURE_SEASON_ID = 1
ASKER_MEMBER_ID = 5
NEAR_CUT_MEMBER_ID = 18
ELIMINATED_MEMBER_ID = 17

#: Eight starter slots, then six bench spots, for all 18 teams.
LINEUP = ("QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX")
FLEX_POSITIONS = ("RB", "WR", "TE")
BENCH = ("RB", "WR", "WR", "TE", "QB", "RB")
#: The position that actually fills each lineup slot; FLEX is filled by a WR.
SLOT_POSITION = ("QB", "RB", "RB", "WR", "WR", "WR", "TE", "WR")


def _starter_points(team: int, slot_index: int) -> float:
    """Strictly decreasing in team number and in slot index."""
    return round(22.0 - 0.6 * team - 1.3 * slot_index, 2)


def _bench_points(team: int, bench_index: int) -> float:
    return round(12.0 - 0.4 * team - 0.9 * bench_index, 2)


def _team(team: int, coverage_pct: float) -> AdvisorTeamState:
    provisional = coverage_pct < 95.0
    holdings: list[AdvisorHolding] = []
    total = 0.0
    for slot_index, lineup_position in enumerate(LINEUP):
        points = _starter_points(team, slot_index)
        total += points
        holdings.append(
            AdvisorHolding(
                sleeper_player_id=f"p{team:02d}s{slot_index}",
                player_name=f"Starter {team:02d}-{slot_index}",
                position=SLOT_POSITION[slot_index],
                slot="starter",
                lineup_position=lineup_position,
                slot_index=slot_index,
                projected_points=None if provisional else points,
            )
        )
    for bench_index, position in enumerate(BENCH):
        holdings.append(
            AdvisorHolding(
                sleeper_player_id=f"p{team:02d}b{bench_index}",
                player_name=f"Bench {team:02d}-{bench_index}",
                position=position,
                slot="bench",
                lineup_position=None,
                slot_index=None,
                projected_points=None if provisional else _bench_points(team, bench_index),
            )
        )
    label = f"Member{team:02d}"
    return AdvisorTeamState(
        team_id=100 + team,
        member_id=team,
        display_name=label,
        member_label=label,
        team_name=f"Team {team:02d}",
        sleeper_roster_id=team,
        faab_remaining=1000 - 40 * team,
        is_eliminated=team == ELIMINATED_MEMBER_ID,
        elimination_source="adjudicator" if team == ELIMINATED_MEMBER_ID else None,
        projected_points=None if provisional else round(total, 2),
        coverage_pct=coverage_pct,
        is_provisional=provisional,
        holdings=tuple(holdings),
    )


def fixture_snapshot(
    week: int = 6,
    *,
    coverage_pct: float = 100.0,
    synced_at: datetime = FIXTURE_SYNCED_AT,
) -> LeagueSnapshot:
    return LeagueSnapshot(
        season=FIXTURE_SEASON,
        season_id=FIXTURE_SEASON_ID,
        week=week,
        synced_at=synced_at,
        teams=tuple(_team(team, coverage_pct) for team in range(1, 19)),
    )
