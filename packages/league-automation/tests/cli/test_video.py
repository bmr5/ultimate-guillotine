"""`ug video`: the trade announcement video commands, driven the way the operator runs them."""

import argparse
import subprocess
import sys

import pytest

from ultimate_guillotine.cli import video as video_cli
from ultimate_guillotine.video import ffmpeg as ff
from ultimate_guillotine.video import higgsfield as hf
from ultimate_guillotine.video.assets import Assets

UG = [sys.executable, "-m", "ultimate_guillotine.cli.main"]


def parse(*argv: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    video_cli.register(parser.add_subparsers())
    return parser.parse_args(["video", *argv])


def touch_reference(root) -> Assets:
    a = Assets(root)
    for path in (a.reference_video, a.source_video, a.music):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
    return a


def test_video_help_lists_commands() -> None:
    result = subprocess.run([*UG, "video", "--help"], capture_output=True, text=True, check=False)
    assert result.returncode == 0
    for name in ("assets", "card", "cost", "render"):
        assert name in result.stdout


def test_assets_reports_missing_files_and_exits_1(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("UG_MEDIA_ROOT", str(tmp_path))
    monkeypatch.setattr(video_cli, "find_tool", lambda name: f"/opt/homebrew/bin/{name}")
    args = parse("assets")
    assert args.handler(args) == 1
    out = capsys.readouterr().out
    assert "MISSING" in out and "ffmpeg" in out


def test_assets_is_quiet_and_green_when_everything_is_in_place(
    tmp_path, monkeypatch, capsys
) -> None:
    touch_reference(tmp_path)
    monkeypatch.setenv("UG_MEDIA_ROOT", str(tmp_path))
    monkeypatch.setattr(video_cli, "find_tool", lambda name: f"/opt/homebrew/bin/{name}")
    args = parse("assets")
    assert args.handler(args) == 0
    assert "MISSING" not in capsys.readouterr().out


def test_card_writes_a_png_from_manual_copy(tmp_path) -> None:
    out = tmp_path / "card.png"
    result = subprocess.run(
        [
            *UG,
            *("video", "card"),
            *("--headline", "SOURCES: X TRADED TO Y"),
            *("--subline", "Y gets X"),
            *("--caption", "pov: test"),
            *("--out", str(out)),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert out.exists() and out.stat().st_size > 0
    assert str(out) in result.stdout


def test_card_needs_a_trade_or_a_headline_and_subline() -> None:
    result = subprocess.run(
        [*UG, "video", "card", "--out", "x.png"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 2
    assert "--trade or both --headline and --subline" in result.stderr


def test_aspect_must_be_a_known_one() -> None:
    with pytest.raises(SystemExit):
        parse("card", "--headline", "h", "--subline", "s", "--out", "x.png", "--aspect", "4:3")


def test_cost_prints_the_credits_without_spending_any(monkeypatch, capsys) -> None:
    monkeypatch.setattr(video_cli, "find_tool", lambda name: f"/opt/homebrew/bin/{name}")
    monkeypatch.setattr(hf, "run", lambda cmd: '{"credits": 52}')
    args = parse("cost", "--headline", "h", "--subline", "s")
    assert args.handler(args) == 0
    assert capsys.readouterr().out.strip() == "52 credits for one 8 s 720p 9:16 clip"


def test_render_dry_run_prints_the_ffmpeg_command_and_encodes_nothing(
    tmp_path, monkeypatch, capsys
) -> None:
    a = touch_reference(tmp_path)
    monkeypatch.setenv("UG_MEDIA_ROOT", str(tmp_path))
    monkeypatch.setattr(video_cli, "find_tool", lambda name: f"/opt/homebrew/bin/{name}")
    monkeypatch.setattr(
        ff, "probe", lambda path, ffprobe="ffprobe", run=None: ff.Probe(1280, 720, 127.0)
    )
    args = parse("render", "--headline", "h", "--subline", "s", "--dry-run")
    assert args.handler(args) == 0
    out = capsys.readouterr().out
    assert out.startswith("/opt/homebrew/bin/ffmpeg ") and "-c:v libx264" in out
    assert not list(a.renders.glob("*.mp4"))


def test_render_dry_run_refuses_to_generate() -> None:
    args = parse("render", "--headline", "h", "--subline", "s", "--base", "generated", "--dry-run")
    with pytest.raises(SystemExit):
        args.handler(args)


def test_render_reports_missing_media_as_a_plain_line(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("UG_MEDIA_ROOT", str(tmp_path))
    monkeypatch.setattr(video_cli, "find_tool", lambda name: f"/opt/homebrew/bin/{name}")
    args = parse("render", "--headline", "h", "--subline", "s")
    assert args.handler(args) == 1
    assert "reference media missing" in capsys.readouterr().err
