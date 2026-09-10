"""One `hermes chat` per turn on the league profile, and the session it leaves behind.

The profile decides what the agent can do: its config names the model, the
`web` toolset and the league MCP server, and nothing here overrides any of it
-- no `-t`, no `--ignore-rules`, no budget. The hang guard is the one limit,
and it is an hour: long enough for any honest research, short enough that a
stuck network call cannot hold the queue all night.
"""

import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from tempfile import mkstemp

from ultimate_guillotine.ai.hermes import _profile_model, _session_id
from ultimate_guillotine.ai.structured import AIInvalidOutput, AIUnavailable
from ultimate_guillotine.core.hermes_cli import hermes_binary

FLAGS = ("chat", "-Q", "--oneshot", "--reasoning", "high", "--source", "tool")
HANG_GUARD_SECONDS = 3600.0


@dataclass(frozen=True)
class AgentReply:
    text: str
    session_id: str
    model: str


class HermesAgentClient:
    def __init__(
        self,
        profile_home: str,
        *,
        model: str | None = None,
        runner=subprocess.run,
        binary: str | None = None,
        hang_guard_seconds: float = HANG_GUARD_SECONDS,
        extra_env: Mapping[str, str] | None = None,
    ) -> None:
        self._home = str(Path(profile_home).expanduser())
        self._model = model
        self._runner = runner
        self._binary = binary
        self._hang_guard = hang_guard_seconds
        self._extra_env = dict(extra_env or {})
        self._reported_model = model or _profile_model(self._home)

    def run(self, query: str, *, resume: str | None = None) -> AgentReply:
        """One turn. ``resume`` continues an earlier session by id."""
        handle, path = mkstemp(suffix=".md", prefix="ug-agent-")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as query_file:
                query_file.write(query)
            command = [self._binary or hermes_binary(), *FLAGS]
            if self._model:
                command += ["-m", self._model]
            if resume:
                command += ["--resume", resume]
            command += ["--query-file", path]
            try:
                result = self._runner(
                    command,
                    env={**os.environ, **self._extra_env, "HERMES_HOME": self._home},
                    capture_output=True,
                    text=True,
                    timeout=self._hang_guard,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise AIUnavailable(f"hermes call raised {exc.__class__.__name__}") from exc
        finally:
            Path(path).unlink(missing_ok=True)
        if result.returncode != 0:
            raise AIUnavailable(f"hermes exited with code {result.returncode}")
        text = (result.stdout or "").strip()
        if not text:
            raise AIInvalidOutput("hermes returned no output")
        return AgentReply(text, _session_id(result.stderr or ""), self._reported_model)
