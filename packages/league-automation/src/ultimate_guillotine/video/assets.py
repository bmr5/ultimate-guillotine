"""Where the reference media and the media tools live.

Everything the trade video pipeline reads from disk sits under one media root,
``data/media`` in the repo checkout by default (``UG_MEDIA_ROOT`` overrides it).
``reference/`` is tracked in git: the Denzo TikTok this pipeline reproduces, the
ESPN footage it was cut from, and the music. ``renders/``, ``generated/`` and
``work/`` are git-ignored output.
"""

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

#: `ug` is run from the repo root by the operator and the Hermes cron jobs.
DEFAULT_MEDIA_ROOT = Path("data/media")

#: The TikTok Ben wants reproduced: @denzo.61, "got the whole league shaking…",
#: 24 s, 1080x1080, posted 2026-08-27. Its footage is ESPN's Adam Schefter
#: breaking-news segment on the Micah Parsons trade; its sound is DIEAGAIN
#: (slowed + reverb) with the footage's own audio muted.
REFERENCE_VIDEO = "tiktok-7678787561464073502-denzo61-got-the-whole-league-shaking.mp4"
#: ESPN's own upload of that segment (YouTube tMgvUrwtaiw, 1280x720, 127 s):
#: Schefter on camera the whole time under the BREAKING NEWS lower third.
SOURCE_VIDEO = "source/espn-tMgvUrwtaiw-schefter-parsons-breaking-news.mp4"
#: Frame correlation against the reference put Denzo's cut 2.5 s into the ESPN
#: upload (measured 2026-09-10). The scene is static, so any window reads the same.
SOURCE_CLIP_START = 2.5
#: The music: YouTube 8_wnIISchzQ, "DIEAGAIN (SLOWED + Reverb)", 229 s.
MUSIC = "youtube-8_wnIISchzQ-dieagain-slowed-reverb.m4a"
#: Audio cross-correlation of the reference against the track peaks at 0.07 s
#: with a 0.91 score: Denzo starts the song from the top.
MUSIC_OFFSET = 0.0
#: How long the reference runs, and so the default render length.
REFERENCE_DURATION = 24.0

FONT_DIR = Path("/System/Library/Fonts/Supplemental")
#: The reference's caption is a heavy sans; Arial Bold is the closest system font.
FONT_CAPTION = FONT_DIR / "Arial Bold.ttf"
#: ESPN's lower third is a condensed heavy face; Arial Black reads the same at a glance.
FONT_HEADLINE = FONT_DIR / "Arial Black.ttf"
FONT_SUBLINE = FONT_DIR / "Arial Bold.ttf"

#: launchd and Hermes run with a short PATH that misses Homebrew.
_EXTRA_PATH = "/opt/homebrew/bin:/usr/local/bin"


class ToolMissing(RuntimeError):
    """A command-line tool the pipeline shells out to is not installed."""


def find_tool(name: str) -> str:
    """The path to ``name``, checking Homebrew's bin after PATH."""
    found = shutil.which(name) or shutil.which(name, path=_EXTRA_PATH)
    if not found:
        raise ToolMissing(f"{name} is not installed (brew install {name})")
    return found


def media_root() -> Path:
    return Path(os.environ.get("UG_MEDIA_ROOT") or DEFAULT_MEDIA_ROOT)


@dataclass(frozen=True)
class Assets:
    root: Path

    @property
    def reference_video(self) -> Path:
        return self.root / "reference" / REFERENCE_VIDEO

    @property
    def source_video(self) -> Path:
        return self.root / "reference" / SOURCE_VIDEO

    @property
    def music(self) -> Path:
        return self.root / "reference" / MUSIC

    @property
    def renders(self) -> Path:
        return self.root / "renders"

    @property
    def generated(self) -> Path:
        return self.root / "generated"

    @property
    def work(self) -> Path:
        return self.root / "work"

    def missing(self) -> list[Path]:
        """The reference files that are not on disk, so `ug video assets` can
        say which download to redo (the README in the folder has the recipe)."""
        wanted = (self.reference_video, self.source_video, self.music)
        return [path for path in wanted if not path.exists()]


def load_assets() -> Assets:
    return Assets(media_root())
