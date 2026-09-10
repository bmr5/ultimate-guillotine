"""The ffmpeg composite: footage, the text layer, the music.

Kept pure where it can be -- the filter graph and the argv are plain functions
of a ``Composite`` -- so the tests check the graph without encoding anything.
Input seeking (``-ss``/``-t`` before each ``-i``) trims the footage and the
music; the PNG is looped and the overlay stops with the footage.
"""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ultimate_guillotine.video.card import CANVAS


class FfmpegError(RuntimeError):
    """ffmpeg or ffprobe exited non-zero; the message is the tail of its stderr."""


@dataclass(frozen=True)
class Composite:
    footage: Path
    card: Path
    music: Path
    output: Path
    aspect: str = "9:16"
    footage_start: float = 0.0
    duration: float = 24.0
    music_offset: float = 0.0
    music_gain_db: float = 0.0
    keep_voice: bool = False
    voice_gain_db: float = -10.0
    fps: int = 30


@dataclass(frozen=True)
class Probe:
    width: int
    height: int
    duration: float


def _even(value: float) -> int:
    return round(value / 2) * 2


def video_filter(c: Composite, footage_w: int, footage_h: int) -> str:
    """Scale and place the footage on the canvas, the same way ``Layout`` does."""
    width, height = CANVAS[c.aspect]
    if c.aspect == "1:1":
        return f"[0:v]crop=min(iw\\,ih):min(iw\\,ih),scale={width}:{height}[footage]"
    scaled_h = _even(footage_h * width / footage_w)
    if scaled_h > height:
        scaled_w = _even(footage_w * height / footage_h)
        left = (width - scaled_w) // 2
        return f"[0:v]scale={scaled_w}:{height},pad={width}:{height}:{left}:0:black[footage]"
    top = (height - scaled_h) // 2
    return f"[0:v]scale={width}:{scaled_h},pad={width}:{height}:0:{top}:black[footage]"


def filter_graph(c: Composite, footage_w: int, footage_h: int) -> str:
    video = video_filter(c, footage_w, footage_h) + ";[footage][1:v]overlay=0:0:shortest=1[v]"
    if c.keep_voice:
        audio = (
            f"[0:a]volume={float(c.voice_gain_db)}dB[voice];"
            f"[2:a]volume={float(c.music_gain_db)}dB[music];"
            "[voice][music]amix=inputs=2:duration=first:normalize=0[a]"
        )
    else:
        audio = f"[2:a]volume={float(c.music_gain_db)}dB[a]"
    return f"{video};{audio}"


def command(c: Composite, footage_w: int, footage_h: int, ffmpeg: str = "ffmpeg") -> list[str]:
    duration = f"{float(c.duration)}"
    return [
        ffmpeg,
        *("-hide_banner", "-loglevel", "error", "-y"),
        *("-ss", f"{float(c.footage_start)}", "-t", duration, "-i", str(c.footage)),
        *("-loop", "1", "-framerate", str(c.fps), "-i", str(c.card)),
        *("-ss", f"{float(c.music_offset)}", "-t", duration, "-i", str(c.music)),
        *("-filter_complex", filter_graph(c, footage_w, footage_h)),
        *("-map", "[v]", "-map", "[a]", "-t", duration, "-r", str(c.fps)),
        *("-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p"),
        *("-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"),
        str(c.output),
    ]


def probe(path: Path, ffprobe: str = "ffprobe", run=subprocess.run) -> Probe:
    """Width, height and duration of the first video stream."""
    cmd = [
        ffprobe,
        *("-v", "error"),
        *("-show_entries", "stream=codec_type,width,height:format=duration"),
        *("-of", "json"),
        str(path),
    ]
    result = run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise FfmpegError(result.stderr.strip()[-500:] or f"ffprobe failed on {path}")
    doc = json.loads(result.stdout)
    video = next(s for s in doc["streams"] if s.get("codec_type") == "video")
    return Probe(int(video["width"]), int(video["height"]), float(doc["format"]["duration"]))


def run(cmd: list[str], run=subprocess.run) -> None:
    result = run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise FfmpegError(result.stderr.strip()[-800:] or "ffmpeg failed")
