from ultimate_guillotine.core import hermes_cli


def test_finds_the_cli_in_local_bin_when_it_is_not_on_path(monkeypatch, tmp_path) -> None:
    """launchd's PATH lacks ~/.local/bin, where the Hermes installer puts the CLI."""
    fallback = tmp_path / "hermes"
    fallback.write_text("")
    monkeypatch.setattr(hermes_cli.shutil, "which", lambda _name: None)
    monkeypatch.setattr(hermes_cli, "_FALLBACK", fallback)
    assert hermes_cli.find_hermes_binary() == str(fallback)
    assert hermes_cli.hermes_binary() == str(fallback)


def test_reports_a_missing_cli_and_still_offers_a_bare_name(monkeypatch, tmp_path) -> None:
    """Senders would rather try PATH once more than refuse to start; callers that
    need a real binary check `find_hermes_binary` and get `None`."""
    monkeypatch.setattr(hermes_cli.shutil, "which", lambda _name: None)
    monkeypatch.setattr(hermes_cli, "_FALLBACK", tmp_path / "missing")
    assert hermes_cli.find_hermes_binary() is None
    assert hermes_cli.hermes_binary() == "hermes"


def test_prefers_the_binary_on_path(monkeypatch) -> None:
    monkeypatch.setattr(hermes_cli.shutil, "which", lambda _name: "/usr/local/bin/hermes")
    assert hermes_cli.find_hermes_binary() == "/usr/local/bin/hermes"
