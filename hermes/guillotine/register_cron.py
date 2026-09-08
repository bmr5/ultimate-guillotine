"""Register cron.yaml jobs with the guillotine Hermes profile. Idempotent by job name."""
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml


def existing_from_state(state: dict) -> dict[str, str]:
    jobs = state.get("jobs", state)
    if isinstance(jobs, dict):
        jobs = list(jobs.values())
    return {
        j["name"]: j["id"]
        for j in jobs
        if isinstance(j, dict) and j.get("name") and j.get("id")
    }


def plan(manifest: dict, existing_jobs: dict[str, str]) -> list[list[str]]:
    commands = []
    for job in manifest["jobs"]:
        tail = ["--script", job["script"], "--no-agent", "--deliver", job["deliver"]]
        if job["name"] in existing_jobs:
            commands.append([
                "hermes", "cron", "edit", existing_jobs[job["name"]],
                "--schedule", job["schedule"], *tail,
            ])
        else:
            commands.append([
                "hermes", "cron", "create", job["schedule"],
                "--name", job["name"], *tail,
            ])
    return commands


def main() -> None:
    profile_home = Path(os.environ["HERMES_HOME"]).expanduser()
    manifest = yaml.safe_load(Path(sys.argv[1]).read_text())
    state_path = profile_home / "cron" / "jobs.json"
    existing = (
        existing_from_state(json.loads(state_path.read_text()))
        if state_path.exists()
        else {}
    )
    for command in plan(manifest, existing):
        print(" ".join(command))
        env = {**os.environ, "HERMES_HOME": str(profile_home)}
        subprocess.run(command, check=True, env=env)


if __name__ == "__main__":
    main()
