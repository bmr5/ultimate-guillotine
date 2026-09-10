import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "register_cron", Path("hermes/guillotine/register_cron.py")
)
register_cron = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(register_cron)

MANIFEST = {
    "jobs": [
        {
            "name": "guillotine-health",
            "agent": "health",
            "schedule": "every 5m",
            "script": "guillotine_health.sh",
            "deliver": "discord:#guillotine-ops",
            "max_gap_minutes": 15,
        },
    ]
}


def test_plan_creates_missing_job() -> None:
    commands = register_cron.plan(MANIFEST, existing_jobs={})
    assert commands == [
        [
            "hermes",
            "cron",
            "create",
            "every 5m",
            "--name",
            "guillotine-health",
            "--script",
            "guillotine_health.sh",
            "--no-agent",
            "--deliver",
            "discord:#guillotine-ops",
        ]
    ]


def test_plan_edits_existing_job_by_name() -> None:
    commands = register_cron.plan(MANIFEST, existing_jobs={"guillotine-health": "abc123"})
    assert commands == [
        [
            "hermes",
            "cron",
            "edit",
            "abc123",
            "--schedule",
            "every 5m",
            "--script",
            "guillotine_health.sh",
            "--no-agent",
            "--deliver",
            "discord:#guillotine-ops",
        ]
    ]


def test_existing_jobs_from_state_file() -> None:
    state = {
        "jobs": [{"id": "abc123", "name": "guillotine-health"}, {"id": "zzz", "name": "other"}]
    }
    assert register_cron.existing_from_state(state) == {
        "guillotine-health": "abc123",
        "other": "zzz",
    }


def test_existing_from_state_bare_list() -> None:
    state = [{"id": "x1", "name": "a"}]
    assert register_cron.existing_from_state(state) == {"a": "x1"}


def test_existing_from_state_dict_with_dict_jobs() -> None:
    state = {"jobs": {"x1": {"id": "x1", "name": "a"}}}
    assert register_cron.existing_from_state(state) == {"a": "x1"}
