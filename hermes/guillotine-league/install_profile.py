"""Install and audit the dedicated profile using the installed Hermes CLI."""

import os
import re
import shlex
import subprocess
from pathlib import Path

import yaml
from ultimate_guillotine.agent.tools.mcp import TOOL_NAMES

ANSI = re.compile(r"\x1b\[[0-9;]*m")


def hermes(*args: str, input_text: str = "") -> str:
    if args == ("tools", "--summary"):
        # Hermes guards this read-only command with isatty(). Only stdin needs a PTY;
        # output remains captured, and a changed command cannot wait forever for input.
        master, slave = os.openpty()
        try:
            result = subprocess.run(
                ["hermes", *args], stdin=slave, capture_output=True, text=True,
                check=True, timeout=30,
            )
        finally:
            os.close(slave)
            os.close(master)
    else:
        result = subprocess.run(
            ["hermes", *args], input=input_text, capture_output=True, text=True,
            check=True, timeout=120,
        )
    return ANSI.sub("", result.stdout)


def read_config(path: Path) -> dict:
    config = yaml.safe_load(path.read_text()) if path.exists() else {}
    if config is not None and not isinstance(config, dict):
        raise ValueError("profile configuration must be a mapping")
    return config or {}


def main() -> None:
    profile = Path(__file__).resolve().parent
    repo = profile.parents[1]
    destination = Path(os.environ["HERMES_HOME"]).expanduser().resolve()
    ops = Path.home() / ".hermes/profiles/guillotine"
    if destination in (Path.home(), Path.home() / ".hermes", ops.resolve(), repo, profile):
        raise ValueError("destination must be a dedicated league profile directory")
    os.environ["HERMES_HOME"] = str(destination)
    os.umask(0o077)
    destination.mkdir(parents=True, exist_ok=True)
    destination.chmod(0o700)
    target = destination / "config.yaml"
    config = read_config(target)
    if "model" not in config:
        source = read_config(ops / "config.yaml")
        if "model" in source:
            config["model"] = source["model"]
    # Explicit lists prevent defaults and portable plugins from adding capabilities.
    config["plugins"] = {"enabled": []}
    config["platform_toolsets"] = {"cli": ["web", "league"]}
    config["memory"] = {"memory_enabled": False, "user_profile_enabled": False}
    config["platforms"] = {}
    config["agent"] = {"disabled_toolsets": []}
    launcher = destination / "scripts/league_mcp.sh"
    existing = (config.get("mcp_servers") or {}).get("league", {})
    registered = existing.get("command") == str(launcher)
    config["mcp_servers"] = {"league": existing} if registered else {}

    def save() -> None:
        target.write_text(yaml.safe_dump(config, sort_keys=False))
        target.chmod(0o600)

    save()
    for folder in ("skills/league-agent", "scripts"):
        (destination / folder).mkdir(parents=True, exist_ok=True)
        (destination / folder).chmod(0o700)
    playbook = (profile / "skills/league-agent/SKILL.md").read_text()
    (destination / "skills/league-agent/SKILL.md").write_text(playbook)
    (destination / "SOUL.md").write_text((profile / "SOUL.md").read_text() + "\n" + playbook)
    launcher.write_text((profile / "scripts/league_mcp.sh.template").read_text().replace(
        "__REPO_SHELL__", shlex.quote(str(repo)),
    ))
    launcher.chmod(0o700)

    # tools list exposes all configurable builtin/plugin keys, including newly shipped ones.
    listing = hermes("tools", "list")
    rows = re.findall(r"^\s*[✓✗]\s+(?:enabled|disabled)\s+(\S+)\s+(.+)$", listing, re.MULTILINE)
    labels = dict(rows)
    if "web" not in labels:
        raise ValueError("cannot audit this Hermes tools list format")
    # kanban is a native CLI builtin recovered by Hermes even though tools list omits it.
    config["agent"]["disabled_toolsets"] = sorted((set(labels) | {"kanban"}) - {"web"})
    config["known_builtin_toolsets"] = {"cli": sorted(labels)}
    save()
    # Hermes filters child environments. Forward only these non-secret caller settings,
    # resolved per invocation rather than recording a fixture install's current values.
    server_env = {"UG_AGENT_FIXTURE": "${UG_AGENT_FIXTURE}"}
    if os.environ.get("UV_CACHE_DIR"):
        server_env["UV_CACHE_DIR"] = "${UV_CACHE_DIR}"
    if not registered:
        # hermes mcp add league probes before saving; EOF alone can accept a failed probe.
        hermes(
            "mcp", "add", "league", "--command", str(launcher), "--env",
            *(f"{key}={value}" for key, value in server_env.items()), input_text="y\n",
        )
        registered_config = read_config(target).get("mcp_servers", {}).get("league", {})
        if registered_config.get("enabled") is not True:
            raise ValueError("league MCP registration did not succeed")
    config["mcp_servers"] = {"league": {
        "command": str(launcher), "enabled": True,
        "env": server_env,
        "tools": {"include": list(TOOL_NAMES), "prompts": False, "resources": False},
    }}
    save()
    # Unlike tools list, summary includes the resolver's automatic MCP and native toolsets.
    summary = hermes("tools", "--summary")
    sections = re.split(r"(?m)^  \S.*\(\d+/\d+\)\s*$", summary)
    if len(sections) < 2:
        raise ValueError("cannot audit this Hermes tools summary format")
    enabled = re.findall(r"(?m)^\s+✓ (.+)$", sections[1])
    if sorted(enabled) != sorted([labels["web"], "league"]):
        raise ValueError("effective CLI tools must be exactly web and league")
    probe = hermes("mcp", "test", "league")
    count = len(TOOL_NAMES)
    if not re.search(rf"Tools discovered: {count}\b", probe) or any(
        not re.search(rf"(?m)^\s*{re.escape(name)}(?:\s|$)", probe) for name in TOOL_NAMES
    ):
        raise ValueError("league MCP did not report all expected tools")
    print(hermes("tools", "list"))
    print(summary)
    print(f"League MCP verified: {count} read-only tools.")
    print(f"Profile guillotine-league installed at {destination}.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError, yaml.YAMLError):
        # Config and provider errors can contain credentials. Keep installer output private.
        raise SystemExit("League profile installation failed; configuration or tool audit failed.")
