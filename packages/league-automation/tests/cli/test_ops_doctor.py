"""`ug ops doctor`'s hermes CLI check.

Settings are made to fail, so every check that needs them fails on `need` without
reaching the network: what is left running is the pair this module is about.
"""

import argparse

import pytest

from ultimate_guillotine.cli import ops


def _no_settings():
    raise RuntimeError("no settings")


def test_doctor_fails_when_the_hermes_cli_cannot_be_located(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without the binary the listener starts, says `Trade Registrar disabled` once
    into the ops channel, and then quietly registers nothing. The doctor is where
    that is meant to be visible."""
    monkeypatch.setattr(ops, "load_settings", _no_settings)
    monkeypatch.setattr(ops, "find_hermes_binary", lambda: None)

    exit_code = ops.cmd_doctor(argparse.Namespace())

    assert exit_code == 1
    assert "FAIL hermes_cli: RuntimeError" in capsys.readouterr().out


def test_doctor_passes_the_hermes_cli_check_when_the_binary_is_found(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(ops, "load_settings", _no_settings)
    monkeypatch.setattr(ops, "find_hermes_binary", lambda: "/opt/found/hermes")

    ops.cmd_doctor(argparse.Namespace())

    assert "PASS hermes_cli" in capsys.readouterr().out


def test_the_hermes_cli_check_raises_only_when_nothing_is_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ops, "find_hermes_binary", lambda: "/opt/found/hermes")
    ops.check_hermes_cli()

    monkeypatch.setattr(ops, "find_hermes_binary", lambda: None)
    with pytest.raises(RuntimeError):
        ops.check_hermes_cli()
