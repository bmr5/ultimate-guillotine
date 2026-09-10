"""One trade in, one video out.

``prepare`` does everything but the encode: it checks the reference media,
picks the footage (the archived ESPN clip at the measured start, a Seedance
clip generated from the reference, or a file Ben points at), probes it, draws
the text layer for that frame, and builds the ffmpeg command. ``render`` runs
that command. The split is what `--dry-run` and the tests use.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ultimate_guillotine.video import ffmpeg as ff
from ultimate_guillotine.video import higgsfield as hf
from ultimate_guillotine.video.assets import (
    MUSIC_OFFSET,
    REFERENCE_DURATION,
    SOURCE_CLIP_START,
    Assets,
)
from ultimate_guillotine.video.card import Layout, render_card
from ultimate_guillotine.video.copy import TradeCopy
from ultimate_guillotine.video.prompt import footage_prompt

STAMP = "%Y%m%d-%H%M%S"


class RenderError(RuntimeError):
    """The render cannot start: media missing, or the footage cannot be read."""


@dataclass(frozen=True)
class RenderRequest:
    copy: TradeCopy
    base: str = "source"
    aspect: str = "9:16"
    duration: float = REFERENCE_DURATION
    keep_voice: bool = False
    music_gain_db: float = 0.0
    name: str = "trade"
    generate_seconds: int = 8
    resolution: str = "720p"


@dataclass(frozen=True)
class Job:
    card: Path
    footage: Path
    footage_start: float
    duration: float
    composite: ff.Composite
    command: list[str]


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "trade"


def prepare(
    req: RenderRequest,
    assets: Assets,
    *,
    ffmpeg: str,
    ffprobe: str,
    probe=None,
    generate=None,
    now=None,
) -> Job:
    """Everything but the encode. ``probe``, ``generate`` and ``now`` are
    resolved here rather than as defaults so a test (or a monkeypatch of the
    modules) takes effect."""
    probe = probe or ff.probe
    generate = generate or hf.generate_clip
    now = now or datetime.now
    missing = assets.missing()
    if missing:
        raise RenderError("reference media missing: " + ", ".join(str(p) for p in missing))
    stamp = f"{_slug(req.name)}-{now().strftime(STAMP)}"
    for folder in (assets.work, assets.renders):
        folder.mkdir(parents=True, exist_ok=True)

    if req.base == "source":
        footage, start = assets.source_video, SOURCE_CLIP_START
    elif req.base == "generated":
        request = hf.GenerateRequest(
            prompt=footage_prompt(req.copy, req.generate_seconds),
            reference_video=assets.reference_video,
            duration=req.generate_seconds,
            resolution=req.resolution,
            aspect_ratio=req.aspect,
        )
        footage, start = generate(request, assets.generated / f"{stamp}.mp4"), 0.0
    else:
        footage, start = Path(req.base), 0.0
        if not footage.exists():
            raise RenderError(f"footage not found: {footage}")

    info = probe(footage, ffprobe=ffprobe)
    duration = min(float(req.duration), max(0.0, info.duration - start))
    layout = Layout.for_footage(info.width, info.height, req.aspect)
    card = render_card(req.copy, layout, assets.work / f"{stamp}-card.png")
    composite = ff.Composite(
        footage=footage,
        card=card,
        music=assets.music,
        output=assets.renders / f"{stamp}.mp4",
        aspect=req.aspect,
        footage_start=start,
        duration=duration,
        music_offset=MUSIC_OFFSET,
        music_gain_db=req.music_gain_db,
        keep_voice=req.keep_voice,
    )
    cmd = ff.command(composite, info.width, info.height, ffmpeg)
    return Job(card, footage, start, duration, composite, cmd)


def render(req: RenderRequest, assets: Assets, *, run=None, **prepare_kwargs) -> Job:
    run = run or ff.run
    job = prepare(req, assets, **prepare_kwargs)
    run(job.command)
    return job
