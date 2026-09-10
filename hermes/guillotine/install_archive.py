"""Install only the four archive jobs into the existing Hermes profile."""

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from register_cron import existing_from_state, plan

ROOT = Path(__file__).resolve().parents[2]
NAMES = {
    "guillotine-archive-capture",
    "guillotine-archive-retry",
    "guillotine-week-close",
    "guillotine-week-verify",
}


def main():
    # Wall-clock cron fields must match Central in both summer and winter.
    for month in (1, 7):
        local = datetime(2026, month, 15, 12).astimezone()
        if (
            local.utcoffset()
            != datetime(
                2026, month, 15, 12, tzinfo=ZoneInfo("America/Chicago")
            ).utcoffset()
        ):
            raise SystemExit(
                "This manifest requires an America/Chicago scheduler host."
            )
    profile = Path(
        os.environ.get("HERMES_HOME", "~/.hermes/profiles/guillotine")
    ).expanduser()
    if not profile.is_dir():
        raise SystemExit("Install the guillotine Hermes profile first.")
    manifest = yaml.safe_load((ROOT / "hermes/guillotine/cron.yaml").read_text())
    selected = {"jobs": [j for j in manifest["jobs"] if j["name"] in NAMES]}
    if len(selected["jobs"]) != 4:
        raise SystemExit("Archive manifest is incomplete.")
    for script in {j["script"] for j in selected["jobs"]}:
        body = (ROOT / "hermes/guillotine/scripts" / f"{script}.template").read_text()
        target = profile / "scripts" / script
        target.write_text(body.replace("__REPO__", str(ROOT)))
        target.chmod(0o755)
    state_file = profile / "cron/jobs.json"
    state = (
        existing_from_state(json.loads(state_file.read_text()))
        if state_file.exists()
        else {}
    )
    env = {**os.environ, "HERMES_HOME": str(profile)}
    for command in plan(selected, state):
        subprocess.run(command, check=True, env=env)
    # Rebuild expected runs from the complete manifest, including all existing jobs.
    subprocess.run(
        [
            str(ROOT / ".venv/bin/ug"),
            "ops",
            "sync-expected-runs",
            str(ROOT / "hermes/guillotine/cron.yaml"),
        ],
        cwd=ROOT,
        check=True,
    )
    print(
        "Installed archive capture, retry, Monday checkpoint, and Tuesday verification jobs."
    )


if __name__ == "__main__":
    main()
