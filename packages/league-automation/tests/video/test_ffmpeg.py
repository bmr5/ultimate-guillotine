import shutil
import subprocess
from pathlib import Path

import pytest

from ultimate_guillotine.video import ffmpeg as ff
from ultimate_guillotine.video.card import Layout, render_card
from ultimate_guillotine.video.copy import TradeCopy


def composite(**overrides) -> ff.Composite:
    fields = {
        "footage": Path("f.mp4"),
        "card": Path("c.png"),
        "music": Path("m.m4a"),
        "output": Path("o.mp4"),
    }
    fields.update(overrides)
    return ff.Composite(**fields)


def test_9_16_centres_the_square_of_wide_footage_and_overlays_the_card() -> None:
    graph = ff.filter_graph(composite(), 1280, 720)
    assert graph.startswith(
        "[0:v]crop=min(iw\\,ih):min(iw\\,ih),scale=1080:1080,pad=1080:1920:0:420:black[footage];"
    )
    assert "[footage][1:v]overlay=0:0:shortest=1[v]" in graph
    assert graph.endswith("[2:a]volume=0.0dB[a]")


def test_1_1_crops_the_centre_square() -> None:
    graph = ff.filter_graph(composite(aspect="1:1"), 1280, 720)
    assert graph.startswith("[0:v]crop=min(iw\\,ih):min(iw\\,ih),scale=1080:1080[footage];")


def test_vertical_footage_fills_the_9_16_canvas() -> None:
    graph = ff.filter_graph(composite(), 720, 1280)
    assert graph.startswith("[0:v]scale=1080:1920,pad=1080:1920:0:0:black[footage];")


def test_keep_voice_mixes_the_footage_audio_under_the_music() -> None:
    graph = ff.filter_graph(composite(keep_voice=True, music_gain_db=-3), 1280, 720)
    assert "[0:a]volume=-10.0dB[voice]" in graph
    assert "[2:a]volume=-3.0dB[music]" in graph
    assert graph.endswith("[voice][music]amix=inputs=2:duration=first:normalize=0[a]")


def test_command_seeks_both_inputs_and_encodes_h264_aac() -> None:
    cmd = ff.command(
        composite(footage_start=2.5, duration=24, music_offset=1.0),
        1280,
        720,
        ffmpeg="/opt/homebrew/bin/ffmpeg",
    )
    assert cmd[0] == "/opt/homebrew/bin/ffmpeg"
    first_input = cmd.index("-i")
    assert cmd[first_input - 4 : first_input] == ["-ss", "2.5", "-t", "24.0"]
    assert "-loop" in cmd and cmd[cmd.index("-loop") + 1] == "1"
    music_input = [i for i, a in enumerate(cmd) if a == "-i"][2]
    assert cmd[music_input - 4 : music_input] == ["-ss", "1.0", "-t", "24.0"]
    assert cmd[-1] == "o.mp4"
    for flag, value in (
        ("-c:v", "libx264"),
        ("-c:a", "aac"),
        ("-pix_fmt", "yuv420p"),
        ("-r", "30"),
    ):
        assert cmd[cmd.index(flag) + 1] == value


def test_probe_reads_the_first_video_stream_and_the_duration() -> None:
    def fake_run(cmd, **_kwargs):
        assert cmd[0] == "ffprobe" and str(cmd[-1]) == "f.mp4"
        stdout = (
            '{"streams":[{"codec_type":"audio"},{"codec_type":"video","width":1280,'
            '"height":720}],"format":{"duration":"127.22"}}'
        )
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout)

    assert ff.probe(Path("f.mp4"), run=fake_run) == ff.Probe(1280, 720, 127.22, has_audio=True)


def test_run_turns_a_failed_encode_into_a_plain_error() -> None:
    def fake_run(cmd, **_kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="Unknown encoder 'x'")

    with pytest.raises(ff.FfmpegError, match="Unknown encoder"):
        ff.run(["ffmpeg"], run=fake_run)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_a_real_two_second_composite_encodes(tmp_path: Path) -> None:
    footage, music, card, out = (tmp_path / n for n in ("f.mp4", "m.m4a", "c.png", "o.mp4"))
    quiet = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    subprocess.run(
        [
            *quiet,
            *("-f", "lavfi", "-i", "testsrc=size=320x180:rate=30:duration=3"),
            *("-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"),
            *("-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac"),
            str(footage),
        ],
        check=True,
    )
    subprocess.run(
        [*quiet, "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-c:a", "aac", str(music)],
        check=True,
    )
    layout = Layout.for_footage(320, 180, "9:16")
    render_card(TradeCopy("pov: test", "SOURCES: TEST", "a gets b"), layout, card)
    c = ff.Composite(
        footage=footage, card=card, music=music, output=out, footage_start=0.5, duration=1.5
    )
    ff.run(ff.command(c, 320, 180))
    probe = ff.probe(out)
    assert (probe.width, probe.height) == (1080, 1920)
    assert 1.3 <= probe.duration <= 1.8
