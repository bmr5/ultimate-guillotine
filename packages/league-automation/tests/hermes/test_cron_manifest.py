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


def test_the_scheduled_agents_are_the_ones_the_cli_records() -> None:
    assert {job["agent"] for job in JOBS} == {
        "health", "gap-fill", "sleeper-sync", "run-audit", "players-sync",
        "nfl-state", "projections-sync",
    }


def test_every_script_template_is_used_by_a_job() -> None:
    used = {job["script"] for job in JOBS}
    on_disk = {path.name.removesuffix(".template") for path in SCRIPTS.glob("*.sh.template")}
    assert on_disk == used
