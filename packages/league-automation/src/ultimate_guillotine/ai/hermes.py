"""Structured output through the Hermes CLI, on the league's own `guillotine` profile.

Hermes already holds the provider credentials and the model choice in
`~/.hermes/profiles/guillotine/config.yaml`, so the package keeps no model key of
its own: one `hermes chat` per call, JSON on stdout.

The query goes through a file rather than an argument: `--query-file` is not
shell-interpreted, so a chat message full of quotes, backticks, and `$(...)` is
passed through verbatim. The file is owner-only and deleted after the call, and
neither the query nor the answer is ever logged -- both are league chat text.
"""

import os
import subprocess
from json import dumps
from pathlib import Path
from tempfile import mkstemp
from time import monotonic
from typing import TypeVar

import yaml
from pydantic import BaseModel

from ultimate_guillotine.ai.structured import (
    AIInvalidOutput,
    AIUnavailable,
    AIUsage,
    parse_model_text,
    strict_schema,
)
from ultimate_guillotine.core.hermes_cli import hermes_binary

T = TypeVar("T", bound=BaseModel)

# `--ignore-rules` drops the profile's SOUL persona, memories, and preloaded skills
# while `config.yaml` -- and with it the provider and the model -- still loads;
# `--ignore-user-config` would drop that too and silently answer on a different model.
# `--source tool` keeps these calls out of Ben's own session lists.
FLAGS = (
    "chat",
    "-Q",
    "--oneshot",
    "-t",
    "",
    "--reasoning",
    "none",
    "--ignore-rules",
    "--source",
    "tool",
)

_INSTRUCTION = (
    "Respond with ONLY one JSON object that matches this JSON schema named {name}. "
    "No prose, no code fences."
)
_REJECTION = (
    "Your previous answer was rejected: {detail}. Reply again with only the corrected JSON."
)

#: A retry with less than this much of the budget left is not worth starting: the
#: caller is a webhook handler, and a second call that is going to time out anyway
#: only doubles the wait before the same `AIInvalidOutput` is raised.
MIN_RETRY_SECONDS = 5.0


class HermesStructuredClient:
    def __init__(
        self,
        profile_home: str,
        *,
        model: str | None = None,
        runner=subprocess.run,
        binary: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        """`timeout` is the budget for the whole `parse`, retry included -- see
        `parse`. A trade extraction that has not answered in a minute is not going
        to; the listener has a webhook to answer."""
        self._home = str(Path(profile_home).expanduser())
        self._model = model
        self._runner = runner
        self._binary = binary
        self._timeout = timeout
        self._reported_model = model or _profile_model(self._home)

    def parse(
        self,
        system: str,
        user: str,
        schema: type[T],
        schema_name: str,
    ) -> tuple[T, AIUsage]:
        """One call, plus at most one retry, inside a single `timeout` budget.

        The budget is shared rather than per call: the caller waits for `parse`, not
        for a subprocess, and two full-length calls in a row would keep the listener
        waiting for twice the timeout it was configured with. The retry gets whatever
        is left; when that is less than `MIN_RETRY_SECONDS` the first rejection stands.
        """
        deadline = monotonic() + self._timeout
        query = (
            f"{system}\n\n"
            f"{_INSTRUCTION.format(name=schema_name)}\n"
            f"{dumps(strict_schema(schema), indent=2)}\n\n"
            f"{user}"
        )
        text, session_id = self._run(query, self._timeout)
        try:
            return parse_model_text(text, schema), self._usage(session_id)
        except AIInvalidOutput as rejected:
            remaining = deadline - monotonic()
            if remaining < MIN_RETRY_SECONDS:
                raise
            retry = f"{query}\n\n{_REJECTION.format(detail=_detail(rejected))}"
        text, session_id = self._run(retry, remaining)
        return parse_model_text(text, schema), self._usage(session_id)

    def _usage(self, session_id: str) -> AIUsage:
        """Hermes prints no token counts, so the counts stay zero and the session id
        stands in for a response id: it is what `hermes chat --resume` takes."""
        return AIUsage(session_id, 0, 0, self._reported_model)

    def _run(self, query: str, timeout: float) -> tuple[str, str]:
        handle, path = mkstemp(suffix=".txt", prefix="ug-query-")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as query_file:
                query_file.write(query)
            command = [self._binary or hermes_binary(), *FLAGS]
            if self._model:
                command += ["-m", self._model]
            command += ["--query-file", path]
            try:
                result = self._runner(
                    command,
                    env={**os.environ, "HERMES_HOME": self._home},
                    capture_output=True,
                    text=True,
                    timeout=timeout,
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
        return text, _session_id(result.stderr or "")


def _detail(rejected: AIInvalidOutput) -> str:
    """The rejection's class name and first summary line -- pydantic puts the offending
    input on later lines, and that input is the league's chat message."""
    cause = rejected.__cause__
    if cause is None:
        return rejected.__class__.__name__
    first_line = str(cause).splitlines()[0].strip() if str(cause) else ""
    return f"{cause.__class__.__name__}: {first_line}" if first_line else cause.__class__.__name__


def _session_id(stderr: str) -> str:
    for line in stderr.splitlines():
        if line.startswith("session_id:"):
            return line.split(":", 1)[1].strip()
    return ""


def _profile_model(home: str) -> str:
    """The profile's default model, for the usage record only.

    Nothing is overridden from here: without `-m`, Hermes picks the model from this
    same file. Reading it is how a recorded run says which model answered.
    """
    try:
        config = yaml.safe_load(Path(home, "config.yaml").read_text(encoding="utf-8"))
        return str(config["model"]["default"])
    except Exception:  # noqa: BLE001 - an unreadable profile must not stop a call
        return "hermes"
