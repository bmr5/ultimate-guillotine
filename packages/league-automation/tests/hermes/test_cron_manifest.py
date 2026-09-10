"""`cron.yaml` is what the Mac mini actually runs, and it is only ever read by
`install.sh` and `ug ops sync-expected-runs` -- neither of which runs in CI. These
checks stand in for that: every job names a script template that exists, every
name is unique (`register_cron` keys on it, so a duplicate silently edits the
first job twice), and every job carries the gap budget the run audit reads.
"""

from pathlib import Path

import yaml

MANIFEST = yaml.safe_load(Path("hermes/guillotine/cron.yaml").read_text())
JOBS = MANIFEST["jobs"]
SCRIPTS = Path("hermes/guillotine/scripts")


def test_every_job_points_at_a_script_template_that_exists() -> None:
    for job in JOBS:
        assert (SCRIPTS / f"{job['script']}.template").exists(), job["name"]


def test_job_names_are_unique() -> None:
    names = [job["name"] for job in JOBS]
    assert len(set(names)) == len(names)


def test_every_job_declares_an_agent_a_deliver_target_and_a_gap_budget() -> None:
    for job in JOBS:
        assert job["agent"] and job["deliver"]
        assert int(job["max_gap_minutes"]) > 0


def test_the_projections_jobs_all_record_the_same_agent() -> None:
    """The baseline and the three game-window jobs are one job on four schedules.
    Sharing the agent is what lets the */30 baseline keep the health check green
    on a Tuesday, and what makes an overlapping fire a same-minute duplicate."""
    projections = [j for j in JOBS if j["script"] == "guillotine_sleeper_projections.sh"]
    assert len(projections) == 4
    assert {j["agent"] for j in projections} == {"projections-sync"}


def test_only_the_projections_baseline_delivers_to_the_ops_channel() -> None:
    """The three game-window rows fire every five minutes, and an outage lasts as
    long as it lasts: routing them to Discord posts the same failure twelve times
    an hour. They stay local; the */30 baseline is what speaks in the channel."""
    projections = {
        job["name"]: job["deliver"]
        for job in JOBS
        if job["script"] == "guillotine_sleeper_projections.sh"
    }
    assert projections == {
        "guillotine-sleeper-projections": "discord:#guillotine-ops",
        "guillotine-sleeper-projections-thursday": "local",
        "guillotine-sleeper-projections-sunday": "local",
        "guillotine-sleeper-projections-monday": "local",
    }


def test_the_scheduled_agents_are_the_ones_the_cli_records() -> None:
    assert {job["agent"] for job in JOBS} == {
        "health",
        "gap-fill",
        "sleeper-sync",
        "run-audit",
        "players-sync",
        "nfl-state",
        "projections-sync",
        "scores-sync",
        "transactions-sync",
        "eod-summary",
        "video-jobs",
    }


def test_the_scores_jobs_all_record_the_same_agent() -> None:
    """Same arrangement as the projections rows, and for the same reason: a baseline plus
    three game-window bursts, one agent, so the baseline keeps the health check green on a
    Tuesday and an overlapping fire is a same-minute duplicate rather than a second run."""
    scores = [j for j in JOBS if j["script"] == "guillotine_sleeper_scores.sh"]
    assert len(scores) == 4
    assert {j["agent"] for j in scores} == {"scores-sync"}


def test_the_scores_jobs_fire_every_minute_in_a_game_window() -> None:
    """Ben: "it should always be realtime!". A five-minute score is not that, so the three
    game-window rows carry a bare `*` in the minute field. The windows are the projections'
    own -- Thursday and Monday nights, Sunday afternoon and evening, mini local time."""
    schedules = {
        job["name"]: job["schedule"]
        for job in JOBS
        if job["script"] == "guillotine_sleeper_scores.sh"
    }
    assert schedules == {
        "guillotine-sleeper-scores": "*/5 * * * *",
        "guillotine-sleeper-scores-thursday": "* 19-23 * * 4",
        "guillotine-sleeper-scores-sunday": "* 12-23 * * 0",
        "guillotine-sleeper-scores-monday": "* 19-23 * * 1",
    }
    # The gap budget has to clear the *baseline*, not the burst: outside a game window the
    # */15 row is the only thing firing, and a budget under it would alarm every Tuesday.
    for job in JOBS:
        if job["script"] == "guillotine_sleeper_scores.sh":
            assert int(job["max_gap_minutes"]) > 15


def test_every_scores_job_stays_off_the_ops_channel() -> None:
    """A job that fires once a minute cannot route its failures to Discord: an outage would
    post the same line sixty times an hour. The baseline is local too — at */15 it is still
    four an hour — and `run_scheduled_with_notes` posts the one note that matters, on the
    edge, while `ug ops health` is the standing answer in between."""
    assert {job["deliver"] for job in JOBS if job["script"] == "guillotine_sleeper_scores.sh"} == {
        "local"
    }


def test_every_script_template_is_used_by_a_job() -> None:
    used = {job["script"] for job in JOBS}
    on_disk = {path.name.removesuffix(".template") for path in SCRIPTS.glob("*.sh.template")}
    assert on_disk == used


def test_the_players_sync_runs_often_enough_to_track_injuries() -> None:
    """`public.players.injury_status` is the one column on the directory that
    changes mid-week, so a nightly refresh would leave an injured starter reading
    as a coverage hole on the board for most of a day. The gap budget has to clear
    the cadence, or `ug ops audit-runs` alarms on a job running exactly to plan."""
    job = next(j for j in JOBS if j["name"] == "guillotine-players-sync")
    assert job["schedule"] == "0 */4 * * *"
    assert int(job["max_gap_minutes"]) > 4 * 60


def test_the_transactions_job_is_pinned_and_the_draft_has_none() -> None:
    """The transaction log moves any time a manager does, so it runs with the roster sync's
    cadence and speaks in the channel like it. The auction is a fact that changes once a
    year and is synced by hand -- Ben (2026-09-10): "drop the cron it's a waste" -- so no
    job may name `draft-sync`."""
    assert not any(j["agent"] == "draft-sync" for j in JOBS)
    transactions = next(j for j in JOBS if j["name"] == "guillotine-sleeper-transactions")
    assert (transactions["agent"], transactions["schedule"], transactions["deliver"]) == (
        "transactions-sync",
        "every 10m",
        "discord:#guillotine-ops",
    )
    assert int(transactions["max_gap_minutes"]) >= 30


def test_the_summary_posts_on_the_mornings_ben_named() -> None:
    """Ben (2026-09-10): a break on Tuesdays and Fridays; 8:15 AM Wednesday, Sunday
    and Monday; 11:15 AM Thursday and Saturday, after each waiver round -- the Saturday
    round closes 11 AM CST by the rules. Two rows, one agent, like the projections
    jobs: the per-agent run key and the health check both see one job. The gap
    budget clears the Monday-to-Wednesday gap."""
    rows = {j["name"]: j for j in JOBS if j["agent"] == "eod-summary"}
    assert set(rows) == {"guillotine-eod-summary", "guillotine-eod-summary-waivers"}
    assert {j["script"] for j in rows.values()} == {"guillotine_eod_summary.sh"}
    assert {j["deliver"] for j in rows.values()} == {"discord:#guillotine-ops"}
    assert rows["guillotine-eod-summary"]["schedule"] == "15 8 * * 0,1,3"
    assert rows["guillotine-eod-summary-waivers"]["schedule"] == "15 11 * * 4,6"
    assert all(int(j["max_gap_minutes"]) > 48 * 60 for j in rows.values())


def test_the_video_worker_polls_the_queue_and_speaks_in_the_ops_channel() -> None:
    """A request from the chat should be picked up within a couple of minutes, and a
    render that fails (78 credits each) is worth a line in the channel. The gap budget
    clears a render that is still running when the next fire comes round."""
    job = next(j for j in JOBS if j["name"] == "guillotine-video-jobs")
    assert (job["agent"], job["schedule"], job["deliver"]) == (
        "video-jobs",
        "every 2m",
        "discord:#guillotine-ops",
    )
    assert int(job["max_gap_minutes"]) >= 30
