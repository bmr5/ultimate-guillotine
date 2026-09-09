"""Locating the Hermes CLI, shared by everything in the package that shells out to it."""

import shutil
from pathlib import Path

_FALLBACK = Path.home() / ".local" / "bin" / "hermes"


def find_hermes_binary() -> str | None:
    """The path to the hermes CLI, or ``None`` when it is not installed.

    The listener runs under launchd, whose PATH does not include ``~/.local/bin``
    where the Hermes installer puts the binary; a bare ``hermes`` there raises
    FileNotFoundError and every Discord mirror is silently dropped.
    """
    found = shutil.which("hermes")
    if found:
        return found
    if _FALLBACK.exists():
        return str(_FALLBACK)
    return None


def hermes_binary() -> str:
    """`find_hermes_binary`, falling back to a bare ``hermes``.

    Callers that only send a message would rather try PATH one more time and log
    the failure than refuse to start; callers that need the binary to exist ask
    `find_hermes_binary` instead.
    """
    return find_hermes_binary() or "hermes"
