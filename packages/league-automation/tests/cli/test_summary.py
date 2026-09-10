"""`ug summary eod`: the dry run in a subprocess, the scheduled path with its
dependencies stubbed.

The fixture cases drive the command with no database, no Hermes and no Sleeper in
reach, because that is the claim: `--fixture` renders the whole message while
touching nothing. The scheduled cases call the handler directly with the reads and
the runner replaced, the way `tests/cli/test_sleeper_scores.py` does, so what is
exercised is the command's own flow: the off-season no-op, the week gate, the
agent it records the run under, and what it prints.
"""

import argparse
import json
import os
import subprocess
import sys
from types import SimpleNamespace
from typing import ClassVar

import pytest

from ultimate_guillotine.agent.tools.snapshot import SnapshotUnavailable
from ultimate_guillotine.cli import summary as summary_cli
from ultimate_guillotine.summary.fixture import fixture_eod

UG = [sys.executable, "-m", "ultimate_guillotine.cli.main"]
BARE_ENV = {
    key: value
    for key, value in os.environ.items()
    if key not in ("DATABASE_URL", "TEST_DATABASE_URL", "DELIVERY_MODE")
}


def run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*UG, *args],
        capture_output=True,
        text=True,
        check=False,
        env=BARE_ENV if env is None else env,
        timeout=120,
    )


def no_hermes(tmp_path) -> dict[str, str]:
    return {**BARE_ENV, "PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}


def parse(*args: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="ug")
    subparsers = parser.add_subparsers(dest="group", required=True)
    summary_cli.register(subparsers)
    return parser.parse_args(["summary", "eod", *args])


# -- the fixture dry run, in a subprocess ---------------------------------


def test_summary_help_lists_eod() -> None:
    result = run("summary", "--help")
    assert result.returncode == 0
    assert "eod" in result.stdout


def test_eod_help_documents_the_flags() -> None:
    result = run("summary", "eod", "--help")
    assert result.returncode == 0
    for flag in (
        "--dry-run",
        "--json",
        "--fixture",
        "--no-ai",
        "--seed",
        "--simulations",
        "--force",
        "--quiet",
        "--out",
    ):
        assert flag in result.stdout


def test_a_fixture_run_prints_the_chat_text_writes_the_artifact_and_touches_nothing(
    tmp_path,
) -> None:
    """What the chat gets: the short text, then the file. No model line up top --
    Ben: "Remove the Model line up top"."""
    result = run(
        "summary",
        "eod",
        "--fixture",
        "--no-ai",
        "--simulations",
        "300",
        "--out",
        str(tmp_path),
        env=no_hermes(tmp_path),
    )

    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0] == "🗡️ GUILLOTINE DAILY · Week 6 · Sunday"
    assert "model:" not in result.stdout
    assert "⚔️ THE GULAG · loser is out" in result.stdout
    assert "⚰️ ON THE BLOCK · bottom 2 enter the Week 7 gulag" in result.stdout
    assert "Full board attached" in result.stdout
    assert "📊 THE BOARD" not in result.stdout
    assert "Monte Carlo projections as of" in result.stdout
    artifact = tmp_path / "guillotine-daily-week-6-2026-10-11.html"
    assert lines[-1] == f"artifact: {artifact}"
    html = artifact.read_text()
    assert html.startswith("<!doctype html>")
    for expected in ("The board", "Member01", "Member17", "wk 5", "Roster watch", "Moves since"):
        assert expected in html


def test_a_fixture_run_without_hermes_still_prints_when_the_colour_was_asked_for(
    tmp_path,
) -> None:
    """No `--no-ai`, no Hermes: the colour is unavailable, said on stderr, and the
    message goes out anyway -- the same thing the cron job does on a bad night."""
    result = run(
        "summary",
        "eod",
        "--fixture",
        "--simulations",
        "100",
        "--out",
        str(tmp_path),
        env=no_hermes(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    assert "EOD summary colour unavailable" in result.stderr
    assert "🗡️ GUILLOTINE DAILY" in result.stdout


def test_a_fixture_json_run_prints_the_packet_and_makes_no_model_call(tmp_path) -> None:
    result = run(
        "summary", "eod", "--fixture", "--json", "--simulations", "100", env=no_hermes(tmp_path)
    )

    assert result.returncode == 0, result.stderr
    packet = json.loads(result.stdout)
    assert (packet["season"], packet["week"], packet["day_state"]) == (2026, 6, "midweek")
    assert packet["phase"]["kind"] == "gulag"
    assert packet["simulations"] == 100
    assert len(packet["teams"]) == 18
    live = [t for t in packet["teams"] if not t["is_eliminated"]]
    assert len(live) == 17
    assert all(t["probability"] is not None for t in live)
    assert result.stderr == ""


def test_the_fixture_output_carries_nothing_private(tmp_path) -> None:
    result = run(
        "summary", "eod", "--fixture", "--json", "--simulations", "50", env=no_hermes(tmp_path)
    )
    body = result.stdout.lower()
    for forbidden in (
        "chat_guid",
        "sender_hash",
        "handle",
        "dues",
        "imessage;",
        "+1555",
        "display_name",
    ):
        assert forbidden not in body


def test_a_seed_makes_two_fixture_runs_identical(tmp_path) -> None:
    first = run(
        "summary",
        "eod",
        "--fixture",
        "--no-ai",
        "--seed",
        "3",
        "--simulations",
        "100",
        "--out",
        str(tmp_path),
        env=no_hermes(tmp_path),
    )
    second = run(
        "summary",
        "eod",
        "--fixture",
        "--no-ai",
        "--seed",
        "3",
        "--simulations",
        "100",
        "--out",
        str(tmp_path),
        env=no_hermes(tmp_path),
    )
    assert first.stdout == second.stdout


# -- the scheduled path, with the reads stubbed --------------------------


class FakeAgent:
    instances: ClassVar[list["FakeAgent"]] = []

    def __init__(self, settings, conn, ai, delivery, notifier, repo) -> None:
        self.args = (settings, conn, ai, delivery, notifier, repo)
        self.runs: list[dict] = []
        FakeAgent.instances.append(self)

    def run(self, snapshot, now, **kwargs):
        self.runs.append({"snapshot": snapshot, "now": now, **kwargs})
        return SimpleNamespace(status="sent", text="the message", model=None, odds=True)


def _wire(
    monkeypatch: pytest.MonkeyPatch,
    *,
    season_type: str = "regular",
    week: int = 6,
    snapshot=None,
    agents: list[str] | None = None,
    hermes: bool = False,
):
    FakeAgent.instances = []
    conn = SimpleNamespace(commit=lambda: None, rollback=lambda: None)
    deps = SimpleNamespace(
        conn=conn,
        notifier=SimpleNamespace(ops=lambda text: True),
        settings=SimpleNamespace(
            sleeper_league_id="league-1",
            hermes_profile_home="/nowhere",
            hermes_model=None,
            delivery_mode="test",
        ),
    )
    monkeypatch.setattr(summary_cli, "build_deps", lambda: deps)
    monkeypatch.setattr(summary_cli, "build_delivery", lambda deps: "delivery")
    monkeypatch.setattr(summary_cli.httpx, "Client", lambda: object())
    monkeypatch.setattr(summary_cli, "SleeperClient", lambda http: object())
    monkeypatch.setattr(
        summary_cli,
        "current_week",
        lambda client, conn, now: SimpleNamespace(season=2026, season_type=season_type, week=week),
    )
    monkeypatch.setattr(summary_cli, "find_hermes_binary", lambda: "/x/hermes" if hermes else None)
    monkeypatch.setattr(summary_cli, "SummaryRepository", lambda conn: "repo")

    def fake_load(conn, client, now):
        if isinstance(snapshot, Exception):
            raise snapshot
        return snapshot or fixture_eod()

    monkeypatch.setattr(summary_cli, "load_snapshot", fake_load)
    monkeypatch.setattr(summary_cli, "EodSummaryAgent", FakeAgent)

    def fake_runner(deps, agent, now, action):
        if agents is not None:
            agents.append(agent)
        return action(1)

    monkeypatch.setattr(summary_cli, "run_scheduled_with_notes", fake_runner)
    return deps


def test_the_scheduled_run_is_recorded_under_the_agent_the_cron_manifest_names(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    agents: list[str] = []
    _wire(monkeypatch, agents=agents)

    assert summary_cli.cmd_eod(parse("--simulations", "50", "--seed", "4")) == 0
    assert agents == ["eod-summary"]
    run_call = FakeAgent.instances[0].runs[0]
    assert run_call["run_id"] == 1
    assert (run_call["use_ai"], run_call["force"], run_call["simulations"], run_call["seed"]) == (
        True,
        False,
        50,
        4,
    )
    assert capsys.readouterr().out == "eod: sent, week 6, odds yes, model none\n"


def test_without_hermes_the_agent_gets_no_model_and_ops_hears_it_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deps = _wire(monkeypatch, hermes=False)
    notes: list[str] = []
    deps.notifier.ops = lambda text: notes.append(text) or True

    summary_cli.cmd_eod(parse("--quiet"))
    _settings, _conn, ai, _delivery, _notifier, _repo = FakeAgent.instances[0].args
    assert ai is None
    assert notes == ["EOD summary colour disabled: hermes CLI not found"]


def test_no_ai_passes_no_client_and_says_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    deps = _wire(monkeypatch, hermes=True)
    notes: list[str] = []
    deps.notifier.ops = lambda text: notes.append(text) or True

    summary_cli.cmd_eod(parse("--no-ai", "--quiet"))
    assert FakeAgent.instances[0].args[2] is None
    assert FakeAgent.instances[0].runs[0]["use_ai"] is False
    assert notes == []


def test_force_reaches_the_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire(monkeypatch)
    summary_cli.cmd_eod(parse("--force", "--quiet"))
    assert FakeAgent.instances[0].runs[0]["force"] is True


def test_a_preseason_run_is_a_clean_no_op(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    _wire(monkeypatch, season_type="pre")
    assert summary_cli.cmd_eod(parse()) == 0
    assert FakeAgent.instances == []
    assert capsys.readouterr().out == "eod: skipped, season_type=pre\n"


def test_a_week_after_the_final_is_a_clean_no_op(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    _wire(monkeypatch, week=18)
    assert summary_cli.cmd_eod(parse()) == 0
    assert FakeAgent.instances == []
    assert capsys.readouterr().out == "eod: skipped, season over\n"


def test_no_snapshot_fails_the_run_and_says_why(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    _wire(monkeypatch, snapshot=SnapshotUnavailable("no public.nfl_state row"))
    assert summary_cli.cmd_eod(parse()) == 1
    assert capsys.readouterr().err == "no snapshot: no public.nfl_state row\n"


def test_quiet_prints_nothing_on_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    _wire(monkeypatch)
    summary_cli.cmd_eod(parse("--quiet"))
    assert capsys.readouterr().out == ""


def test_a_dry_run_against_the_league_composes_and_records_no_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, tmp_path
) -> None:
    """`--dry-run` reads the real league, prints the message, and never reaches the
    runner: no run row, no recap, no send."""
    agents: list[str] = []
    _wire(monkeypatch, agents=agents)

    assert (
        summary_cli.cmd_eod(
            parse("--dry-run", "--no-ai", "--simulations", "50", "--out", str(tmp_path))
        )
        == 0
    )
    assert agents == []
    out = capsys.readouterr().out
    assert out.startswith("🗡️ GUILLOTINE DAILY")
    # A real-league dry run is stamped with tonight's date, whatever the fixture's.
    assert list(tmp_path.glob("guillotine-daily-week-6-*.html"))
