"""Public survival reads follow the migrations and the summary writer's JSON shape."""

from datetime import UTC, datetime
from decimal import Decimal

from ultimate_guillotine.agent.tools.league import survival
from ultimate_guillotine.agent.tools.source import DatabaseSource, FixtureSource, GulagEntry
from ultimate_guillotine.data.repositories import RunRepository


def test_historical_week_has_separate_current_state_and_missing_public_data():
    result = survival(FixtureSource(), week=1)
    assert result["week"] == 1
    assert result["eliminated"] == []
    assert result["current_state"]["week"] == 6
    assert result["current_state"]["alive"] == 17
    assert result["gulag_entries_status"] == "not recorded"
    assert result["latest_summary"] is None
    assert result["summary_status"] == "not recorded"


class Cursor:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, query, args=()):
        self.calls.append((query, args))

    def fetchall(self):
        return self.rows.pop(0)

    def fetchone(self):
        return self.rows.pop(0)


class Connection:
    def __init__(self, rows):
        self.cur = Cursor(rows)

    def cursor(self):
        return self.cur


def test_public_week_scores_use_latest_weekly_result_version():
    conn = Connection([[('Member05', 'Team', 2, Decimal('100.5'), True, 3)]])
    source = DatabaseSource(conn, None, "unused")
    source.snapshot = FixtureSource().snapshot
    scores = source.week_scores(2)
    sql, params = conn.cur.calls[0]
    assert 'public.weekly_results' in sql and 'state_version desc' in sql
    assert 'distinct on' in sql and 'team_week_scores' not in sql
    assert params == (source.snapshot().season_id, 2)
    assert scores[0].is_final and scores[0].state_version == 3


def test_gulag_and_summary_expose_public_labels_and_only_known_fields():
    at = datetime(2026, 10, 8, tzinfo=UTC)
    conn = Connection([
        [('Member05', 2, at)],
        (6, at, 'evening', 'sleeper', 'v1', 1000, [
            {'team_id': 5, 'label': 'private old label', 'points': 80,
             'projected_final': 100, 'pending': 2, 'adverse_event': 'cut',
             'probability': .2, 'is_estimated': False, 'dues': 'private'},
        ]),
        [(5, 'Member05')],
    ])
    source = DatabaseSource(conn, None, 'unused')
    source.snapshot = FixtureSource().snapshot
    entries = source.gulag_entries(2)
    assert entries[0].member_label == 'Member05'
    assert 'gulag_entry' in conn.cur.calls[0][0]
    summary = source.survival_summary()
    assert summary['week'] == 6 and summary['teams'][0]['member'] == 'Member05'
    assert summary['teams'][0]['probability'] == .2
    assert 'private' not in str(summary) and 'team_id' not in str(summary)
    assert 'public.survival_snapshots' in conn.cur.calls[1][0]
    assert 'snapshot_at desc' in conn.cur.calls[1][0]


def test_absent_database_summary_is_explicit():
    source = DatabaseSource(Connection([None]), None, 'unused')
    source.snapshot = FixtureSource().snapshot
    assert source.survival_summary() is None


def test_survival_tool_reports_recorded_gulag_summary_and_cut_for_requested_week():
    source = FixtureSource()
    at = datetime(2026, 10, 8, tzinfo=UTC)
    source.gulag_entries = lambda week: [GulagEntry('Member05', week, at)]
    source.survival_summary = lambda: {'week': 6, 'as_of': at.isoformat(), 'teams': []}
    result = survival(source, week=5)
    assert result['gulag_entries'][0]['member'] == 'Member05'
    assert result['gulag_entries_status'] == result['summary_status'] == 'recorded'
    assert result['latest_summary']['week'] == 6
    assert result['eliminated'] == [
        {'member': 'Member17', 'week': 5, 'source': 'adjudicator'},
    ]
    source.week_scores = lambda week: []
    assert survival(source, week=5)['scores_status'] == 'not recorded'


def test_parent_run_recognition_is_scoped_to_the_agent_in_sql():
    conn = Connection([(1,), None])
    runs = RunRepository(conn)
    assert runs.is_agent_run(7, 'league-agent')
    assert not runs.is_agent_run(8, 'league-agent')
    sql, params = conn.cur.calls[0]
    assert 'private.agent_runs' in sql and 'agent = %s' in sql
    assert params == (7, 'league-agent')
