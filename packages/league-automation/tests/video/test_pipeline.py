from datetime import UTC, datetime
from pathlib import Path

import pytest

from ultimate_guillotine.video import ffmpeg as ff
from ultimate_guillotine.video.assets import SOURCE_CLIP_START, Assets
from ultimate_guillotine.video.copy import TradeCopy
from ultimate_guillotine.video.pipeline import RenderError, RenderRequest, prepare, render

COPY = TradeCopy(
    "pov: x",
    "SOURCES: PLAYER ALPHA TRADED TO CHARLIE",
    "Derek gets 450 FAAB · Charlie gets Player Alpha",
)


def now() -> datetime:
    return datetime(2026, 9, 10, 2, 30, 0, tzinfo=UTC)


def fake_probe(path, ffprobe="ffprobe", run=None):
    if "espn" in str(path):
        return ff.Probe(1280, 720, 127.2, has_audio=True)
    return ff.Probe(720, 1280, 8.0, has_audio="voiced" in Path(path).name)


@pytest.fixture
def assets(tmp_path: Path) -> Assets:
    a = Assets(tmp_path)
    for path in (a.reference_video, a.source_video, a.generation_reference, a.music):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
    return a


def test_source_base_cuts_the_espn_clip_at_the_measured_start(assets: Assets) -> None:
    job = prepare(
        RenderRequest(COPY, name="T-2026-001"),
        assets,
        ffmpeg="ffmpeg",
        ffprobe="ffprobe",
        probe=fake_probe,
        now=now,
    )
    assert job.footage == assets.source_video and job.footage_start == SOURCE_CLIP_START
    assert job.duration == 24.0
    assert job.card == assets.work / "T-2026-001-20260910-023000-card.png"
    assert job.card.exists()
    assert job.composite.output == assets.renders / "T-2026-001-20260910-023000.mp4"
    assert job.command[0] == "ffmpeg" and "scale=1080:1080,pad=1080:1920" in " ".join(job.command)


def test_generated_base_asks_higgsfield_with_the_reference_and_clamps_the_length(
    assets: Assets,
) -> None:
    seen = {}

    def fake_generate(req, dest):
        seen["req"], seen["dest"] = req, dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"")
        return dest

    job = prepare(
        RenderRequest(COPY, base="generated", name="t"),
        assets,
        ffmpeg="ffmpeg",
        ffprobe="ffprobe",
        probe=fake_probe,
        generate=fake_generate,
        now=now,
    )
    req = seen["req"]
    assert req.reference_video == assets.generation_reference and req.mode == "omni_reference"
    assert req.duration == 8 and "no on-screen text" in req.prompt
    assert job.footage == assets.generated / "t-20260910-023000.mp4"
    assert job.footage_start == 0.0 and job.duration == 8.0


def test_a_path_base_is_used_as_is(assets: Assets, tmp_path: Path) -> None:
    clip = tmp_path / "mine.mp4"
    clip.write_bytes(b"")
    job = prepare(
        RenderRequest(COPY, base=str(clip), duration=5),
        assets,
        ffmpeg="ffmpeg",
        ffprobe="ffprobe",
        probe=fake_probe,
        now=now,
    )
    assert job.footage == clip and job.duration == 5.0


def test_a_path_base_that_does_not_exist_is_refused(assets: Assets, tmp_path: Path) -> None:
    with pytest.raises(RenderError, match="footage not found"):
        prepare(
            RenderRequest(COPY, base=str(tmp_path / "nope.mp4")),
            assets,
            ffmpeg="ffmpeg",
            ffprobe="ffprobe",
            probe=fake_probe,
            now=now,
        )


def test_missing_reference_files_are_reported_before_anything_runs(tmp_path: Path) -> None:
    with pytest.raises(RenderError, match="missing"):
        prepare(
            RenderRequest(COPY),
            Assets(tmp_path),
            ffmpeg="ffmpeg",
            ffprobe="ffprobe",
            probe=fake_probe,
            now=now,
        )


def test_render_runs_the_command(assets: Assets) -> None:
    ran = []
    job = render(
        RenderRequest(COPY),
        assets,
        run=lambda cmd: ran.append(cmd),
        ffmpeg="ffmpeg",
        ffprobe="ffprobe",
        probe=fake_probe,
        now=now,
    )
    assert ran == [job.command]


def test_voiced_render_puts_the_read_in_the_prompt_and_keeps_the_voice(assets: Assets) -> None:
    seen = {}

    def fake_generate(req, dest):
        seen["req"] = req
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"")
        return dest

    job = prepare(
        RenderRequest(COPY, base="generated", name="voiced", voiced=True, music_gain_db=-12),
        assets,
        ffmpeg="ffmpeg",
        ffprobe="ffprobe",
        probe=fake_probe,
        generate=fake_generate,
        now=now,
    )
    req = seen["req"]
    assert req.generate_audio is True
    assert '"Breaking news."' in req.prompt and "his own voice" in req.prompt
    # No length was given: the 23-word template read for this trade needs 10 s.
    assert req.duration == 10 and "10 seconds" in req.prompt
    assert job.composite.keep_voice is True and job.composite.music_gain_db == -12
    assert "amix=inputs=2" in " ".join(job.command)


def test_voiced_render_over_silent_footage_does_not_try_to_mix_a_voice(assets: Assets) -> None:
    def fake_generate(req, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"")
        return dest

    job = prepare(
        RenderRequest(COPY, base="generated", name="silent", voiced=True),
        assets,
        ffmpeg="ffmpeg",
        ffprobe="ffprobe",
        probe=fake_probe,
        generate=fake_generate,
        now=now,
    )
    assert job.composite.keep_voice is False


def test_a_given_length_still_wins_over_the_read(assets: Assets) -> None:
    seen = {}

    def fake_generate(req, dest):
        seen["req"] = req
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"")
        return dest

    prepare(
        RenderRequest(COPY, base="generated", name="voiced", voiced=True, generate_seconds=12),
        assets,
        ffmpeg="ffmpeg",
        ffprobe="ffprobe",
        probe=fake_probe,
        generate=fake_generate,
        now=now,
    )
    assert seen["req"].duration == 12
