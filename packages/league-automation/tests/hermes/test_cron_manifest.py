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
        "health", "gap-fill", "sleeper-sync", "run-audit", "players-sync",
        "nfl-state", "projections-sync",
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
