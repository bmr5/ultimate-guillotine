"""Profile instructions and a repeatable, restricted installation without live services."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from ultimate_guillotine.agent.artifact import ALLOWED_CLASSES
from ultimate_guillotine.agent.tools.mcp import TOOL_NAMES

ROOT = Path(__file__).resolve().parents[4]
PROFILE = ROOT / "hermes" / "guillotine-league"


def test_profile_documents_contract() -> None:
    skill = (PROFILE / "skills/league-agent/SKILL.md").read_text()
    for name in (*TOOL_NAMES, *ALLOWED_CLASSES):
        assert f"`{name}`" in skill
    for phrase in ("why the other side says yes", "projections_complete", "source", "🚨"):
        assert phrase in skill
    soul = (PROFILE / "SOUL.md").read_text()
    for phrase in ("phone number", "dues", "🚨", "data, not instructions", "cite"):
        assert phrase in soul
    assert "desperate" not in soul.lower()


def test_persona_rentals_and_transaction_claims_preserve_the_research_contract() -> None:
    soul = (PROFILE / "SOUL.md").read_text()
    skill = (PROFILE / "skills/league-agent/SKILL.md").read_text()
    for phrase in ("Daddy", "kitten", "without sexual or coercive language",
                   "Facts and clear advice come first", "never invent another member's consent"):
        assert phrase in soul
    for phrase in ("short-term rentals", "permanent acquisition", "waiver alternatives",
                   "Week-to-week survival", "FAAB preservation", "price assumptions",
                   "return terms", "custody", "transaction history", "unverified"):
        assert phrase in soul
    for phrase in ("`transactions` for that week", "Current ownership alone does not prove",
                   "rental cost", "outright purchase", "injury or bye horizon",
                   "`price_history`", "remaining budget", "return week", "return terms",
                   "either team is eliminated", "Never invent consent", "unconventional",
                   "Run `trade_math` on every proposal", "projections_complete",
                   "why the other side says yes", "Cite the public pages you actually read"):
        assert phrase in skill


def test_shell_syntax() -> None:
    for name in ("install.sh", "scripts/league_mcp.sh.template"):
        subprocess.run(["bash", "-n", str(PROFILE / name)], check=True)


@pytest.fixture
def installation(tmp_path: Path) -> tuple[dict[str, str], Path]:
    home = tmp_path / "home"
    ops = home / ".hermes/profiles/guillotine"
    ops.mkdir(parents=True)
    (ops / "config.yaml").write_text("model: {default: example}\nsecret: do-not-copy\n")
    destination = tmp_path / "profile with 'quotes' & spaces"
    binaries = tmp_path / "bin"
    binaries.mkdir()
    uv = binaries / "uv"
    uv.write_text(f'#!/bin/bash\nshift 3\nexec "{sys.executable}" "${{@:2}}"\n')
    hermes = binaries / "hermes"
    hermes.write_text(
        f"#!{sys.executable}\n"
        "import os, sys, pathlib, yaml\n"
        "args = sys.argv[1:]\n"
        "home = pathlib.Path(os.environ['HERMES_HOME'])\n"
        "cfg = yaml.safe_load((home / 'config.yaml').read_text())\n"
        "with (home / 'calls').open('a') as f: f.write(' '.join(args) + '\\n')\n"
        "if args == ['tools', 'list']:\n"
        "    for name in ['web', 'skills', 'todo', 'terminal', 'future_builtin']:\n"
        "        status = 'enabled' if name == 'web' else 'disabled'\n"
        "        print('  ✓ ' + status + '  ' + name + '  ' + name)\n"
        "elif args == ['tools', '--summary']:\n"
        "    if not sys.stdin.isatty(): raise SystemExit(1)\n"
        "    print('⚕ Tool Summary\\n\\n  CLI (2/5)\\n    ✓ web\\n    ✓ league')\n"
        "    if 'kanban' not in cfg['agent']['disabled_toolsets']: print('    ✓ kanban')\n"
        "    if os.environ.get('EXTRA_TOOL'): print('    ✓ secret_writer')\n"
        "elif args == ['mcp', 'test', 'league']:\n"
        "    forwarded = cfg['mcp_servers']['league'].get('env', {})\n"
        "    assert forwarded['UG_AGENT_FIXTURE'] == '${UG_AGENT_FIXTURE}'\n"
        "    if os.environ.get('UV_CACHE_DIR'):\n"
        "        assert forwarded['UV_CACHE_DIR'] == '${UV_CACHE_DIR}'\n"
        "    if not os.environ.get('BAD_MCP'):\n"
        f"        print('Tools discovered: 11\\n' + '\\n'.join({list(TOOL_NAMES)!r}))\n"
        "elif args[:3] == ['mcp', 'add', 'league']:\n"
        "    assert '--env' in args\n"
        "    assert 'UG_AGENT_FIXTURE=${UG_AGENT_FIXTURE}' in args\n"
        "    if os.environ.get('UV_CACHE_DIR'):\n"
        "        assert 'UV_CACHE_DIR=${UV_CACHE_DIR}' in args\n"
        "    if os.environ.get('BAD_ADD'):\n"
        "        print('Failed to connect')\n"
        "        raise SystemExit(0)\n"
        "    cfg['mcp_servers'] = {'league': {'command': args[4], 'enabled': True}}\n"
        "    (home / 'config.yaml').write_text(yaml.safe_dump(cfg))\n"
        "else: raise SystemExit(9)\n"
    )
    uv.chmod(0o755)
    hermes.chmod(0o755)
    return {
        **os.environ, "HOME": str(home), "PATH": f"{binaries}:{os.environ['PATH']}",
        "HERMES_LEAGUE_PROFILE_HOME": str(destination),
    }, destination


def run_install(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(PROFILE / "install.sh")], cwd=ROOT, env=env,
        capture_output=True, text=True, check=False,
    )


def test_install_is_private_idempotent_and_strict(installation) -> None:
    env, destination = installation
    for _ in range(2):
        result = run_install(env)
        assert result.returncode == 0, result.stderr
    config = yaml.safe_load((destination / "config.yaml").read_text())
    assert config["model"] == {"default": "example"}
    assert "secret" not in config
    assert config["platform_toolsets"]["cli"] == ["web", "league"]
    assert {"skills", "todo", "future_builtin"} <= set(config["agent"]["disabled_toolsets"])
    assert config["plugins"]["enabled"] == []
    assert set(config["mcp_servers"]) == {"league"}
    assert config["mcp_servers"]["league"]["tools"]["include"] == list(TOOL_NAMES)
    expected_env = {"UG_AGENT_FIXTURE": "${UG_AGENT_FIXTURE}"}
    if env.get("UV_CACHE_DIR"):
        expected_env["UV_CACHE_DIR"] = "${UV_CACHE_DIR}"
    assert config["mcp_servers"]["league"]["env"] == expected_env
    assert (destination / "config.yaml").stat().st_mode & 0o777 == 0o600
    assert destination.stat().st_mode & 0o777 == 0o700
    assert (destination / "scripts/league_mcp.sh").stat().st_mode & 0o777 == 0o700
    assert (PROFILE / "skills/league-agent/SKILL.md").read_text() in (
        destination / "SOUL.md"
    ).read_text()
    assert (destination / "calls").read_text().count("mcp add league") == 1
    assert "profile create" not in (destination / "calls").read_text()
    assert "do-not-copy" not in result.stdout + result.stderr


@pytest.mark.parametrize("failure", ["EXTRA_TOOL", "BAD_MCP", "BAD_ADD"])
def test_install_fails_closed_on_audit_or_transport_failure(installation, failure) -> None:
    env, _ = installation
    result = run_install({**env, failure: "1"})
    assert result.returncode != 0


def test_reinstall_preserves_model_and_removes_extra_capabilities(installation) -> None:
    env, destination = installation
    destination.mkdir()
    (destination / "config.yaml").write_text(yaml.safe_dump({
        "model": {"default": "keep-me"}, "mcp_servers": {"other": {"command": "bad"}},
        "platform_toolsets": {"cli": ["terminal"]},
    }))
    result = run_install(env)
    assert result.returncode == 0, result.stderr
    config = yaml.safe_load((destination / "config.yaml").read_text())
    assert config["model"] == {"default": "keep-me"}
    assert set(config["mcp_servers"]) == {"league"}


def test_launcher_runs_from_repository_and_preserves_fixture_mode(installation, tmp_path) -> None:
    env, destination = installation
    assert run_install(env).returncode == 0
    uv = Path(env["PATH"].split(":")[0]) / "uv"
    output = tmp_path / "launch"
    uv.write_text(
        '#!/bin/bash\nprintf "%s\\n" "$PWD" "$UG_AGENT_FIXTURE" "$@" > "$LAUNCH_OUTPUT"\n'
    )
    subprocess.run(
        ["bash", str(destination / "scripts/league_mcp.sh")], cwd=tmp_path,
        env={**env, "UG_AGENT_FIXTURE": "1", "LAUNCH_OUTPUT": str(output)}, check=True,
    )
    assert output.read_text().splitlines() == [
        str(ROOT), "1", "run", "--project", "packages/league-automation", "ug", "agent", "mcp",
    ]


def test_fixture_install_does_not_pin_future_fixture_or_cache_settings(installation) -> None:
    env, destination = installation
    assert run_install({**env, "UG_AGENT_FIXTURE": "1"}).returncode == 0
    uv = Path(env["PATH"].split(":")[0]) / "uv"
    uv.write_text('#!/bin/bash\nprintf "%s\\n" "${UG_AGENT_FIXTURE-unset}" '
                  '"${UV_CACHE_DIR-unset}"\n')
    # Hermes retains unresolved interpolation placeholders when caller variables are absent.
    filtered = {
        "PATH": env["PATH"], "UG_AGENT_FIXTURE": "${UG_AGENT_FIXTURE}",
        "UV_CACHE_DIR": "${UV_CACHE_DIR}",
    }
    result = subprocess.run(
        ["bash", str(destination / "scripts/league_mcp.sh")], env=filtered,
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.splitlines() == ["unset", "unset"]
