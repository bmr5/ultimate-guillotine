# Trade Announcement Video Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `ug video render --trade T-2026-003` turns a logged league trade into a TikTok-style
"breaking news" video in the exact format of the Denzo TikTok Ben saved: ESPN breaking-news
footage (or Higgsfield-generated footage in its style), a centred meme caption, an ESPN-style
lower third carrying the trade, and the DIEAGAIN track under it.

**Architecture:** A new `ultimate_guillotine.video` package. Words come from the stored trade
terms (`copy.py`). Pillow draws the whole text layer as one transparent PNG (`card.py`) because
this Mac's ffmpeg has no `drawtext` filter. ffmpeg composites footage + card + music
(`ffmpeg.py`), with the footage either the archived ESPN clip or a clip Seedance 2.5 generates
from the reference video through the `higgsfield` CLI (`higgsfield.py`, `prompt.py`).
`pipeline.py` strings those together and `cli/video.py` exposes them as `ug video` commands.
Every subprocess call goes through an injectable runner so the tests never encode video or
spend credits.

**Tech Stack:** Python 3.12, argparse `ug` CLI (`cli/main.py` registers modules), Pillow
12.3.0 (new dependency), ffmpeg 8.1.2 at `/opt/homebrew/bin` (has `scale`, `pad`, `crop`,
`overlay`, `amix`, `volume`, `libx264`, `aac`; **no** `drawtext`/`subtitles`), Higgsfield CLI
1.1.23 (`higgsfield`, logged in as benray887@gmail.com, model `seedance_2_5`, 52 credits per
8 s 720p clip), pytest 9.1.1, ruff 0.16.6.

**Spec:** `docs/references/meme-video-reference.md` (what the video is made of and Ben's five
requirements) plus `data/media/reference/README.md` (the archived inputs and their provenance).

## Global Constraints

- Python `>=3.12,<3.13`; run everything as `uv run --project packages/league-automation …` from the repo root.
- `ruff` line length 100, target py312; dependencies pinned exactly (`pillow==12.3.0`).
- Tests: `uv run --project packages/league-automation pytest tests/video tests/cli/test_video.py -q`. No network, no database, no Higgsfield credits, no real encode except the one lavfi integration test (skipped when ffmpeg is missing).
- New CLI groups follow `cli/trades.py`: a `register(subparsers)` function, `cmd_*` handlers returning an int, `set_defaults(handler=…)`, registered in `cli/main.py`.
- Media root is `data/media` relative to the working directory (`UG_MEDIA_ROOT` overrides). `data/media/reference/` is tracked in git; `renders/`, `generated/`, `work/` are ignored.
- Never draw text with ffmpeg; the text layer is always the Pillow PNG.
- Commit after every task with a message in the repo's style (`feat(video): …`, `test(video): …`).

---

### Task 1: Reference assets and docs (done 2026-09-10)

**Files:**
- Create: `data/media/reference/README.md`, `data/media/reference/*.{mp4,m4a,mp3,info.json}`, `data/media/reference/source/espn-tMgvUrwtaiw-schefter-parsons-breaking-news.{mp4,info.json}`
- Modify: `docs/references/meme-video-reference.md`, `.gitignore`

- [x] **Step 1: Archive the inputs** — Denzo's TikTok (24 s, 1080x1080), its audio, the DIEAGAIN track from YouTube `8_wnIISchzQ` (229 s m4a), ESPN's Schefter upload YouTube `tMgvUrwtaiw` (127 s, 1280x720), the Neighborhood Podcast sound and its source video.
- [x] **Step 2: Measure what the reference does** — audio cross-correlation: the music starts at 0.0 s of the track (score 0.91), the footage's own audio is absent; frame correlation: Denzo's cut starts ~2.5 s into the ESPN upload.
- [x] **Step 3: Write the provenance README and update the reference doc; ignore `data/media/{renders,generated,work}`.**
- [x] **Step 4: Commit** (d0c9594)

```bash
git add data/media/reference docs/references/meme-video-reference.md .gitignore docs/superpowers/plans/2026-09-10-trade-announcement-video-pipeline.md
git commit -m "docs(video): archive the reference TikTok, its footage and music; plan the trade video pipeline"
```

---

### Task 2: Pillow dependency, `video/assets.py`, `ug video assets`

**Files:**
- Modify: `packages/league-automation/pyproject.toml` (dependency), `packages/league-automation/uv.lock`
- Create: `packages/league-automation/src/ultimate_guillotine/video/__init__.py` (empty)
- Create: `packages/league-automation/src/ultimate_guillotine/video/assets.py`
- Create: `packages/league-automation/src/ultimate_guillotine/cli/video.py`
- Modify: `packages/league-automation/src/ultimate_guillotine/cli/main.py:11-37` (import + register `video`)
- Test: `packages/league-automation/tests/video/__init__.py` (empty), `packages/league-automation/tests/video/test_assets.py`, `packages/league-automation/tests/cli/test_video.py`

**Interfaces:**
- Produces: `Assets` (frozen dataclass with `root`; properties `reference_video`, `source_video`, `music`, `renders`, `generated`, `work`; `missing() -> list[Path]`), `load_assets() -> Assets`, `media_root() -> Path`, `find_tool(name: str) -> str` raising `ToolMissing`, constants `SOURCE_CLIP_START = 2.5`, `MUSIC_OFFSET = 0.0`, `REFERENCE_DURATION = 24.0`, `FONT_CAPTION`, `FONT_HEADLINE`, `FONT_SUBLINE`.

- [ ] **Step 1: Add Pillow**

```bash
uv add --project packages/league-automation "pillow==12.3.0"
uv run --project packages/league-automation python -c "import PIL; print(PIL.__version__)"
```
Expected: `12.3.0`

- [ ] **Step 2: Write the failing tests**

`tests/video/test_assets.py`:
```python
from pathlib import Path

import pytest

from ultimate_guillotine.video import assets as assets_mod
from ultimate_guillotine.video.assets import Assets, ToolMissing, find_tool, load_assets


def test_media_root_defaults_to_data_media_and_honours_the_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UG_MEDIA_ROOT", raising=False)
    assert load_assets().root == Path("data/media")
    monkeypatch.setenv("UG_MEDIA_ROOT", "/tmp/elsewhere")
    assert load_assets().root == Path("/tmp/elsewhere")


def test_paths_hang_off_the_root() -> None:
    a = Assets(Path("/m"))
    assert a.reference_video == Path("/m/reference") / assets_mod.REFERENCE_VIDEO
    assert a.source_video == Path("/m/reference/source/espn-tMgvUrwtaiw-schefter-parsons-breaking-news.mp4")
    assert a.music == Path("/m/reference") / assets_mod.MUSIC
    assert (a.renders, a.generated, a.work) == (Path("/m/renders"), Path("/m/generated"), Path("/m/work"))


def test_missing_lists_only_the_reference_files_that_are_not_on_disk(tmp_path: Path) -> None:
    a = Assets(tmp_path)
    a.music.parent.mkdir(parents=True)
    a.music.write_bytes(b"")
    assert a.missing() == [a.reference_video, a.source_video]


def test_find_tool_raises_a_plain_error_for_an_unknown_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(assets_mod.shutil, "which", lambda *_a, **_k: None)
    with pytest.raises(ToolMissing, match="no-such-tool"):
        find_tool("no-such-tool")


def test_find_tool_returns_the_path_which_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(assets_mod.shutil, "which", lambda name, path=None: f"/opt/homebrew/bin/{name}")
    assert find_tool("ffmpeg") == "/opt/homebrew/bin/ffmpeg"
```

`tests/cli/test_video.py` (first two tests; the file grows in later tasks):
```python
import argparse
import subprocess
import sys

from ultimate_guillotine.cli import video as video_cli

UG = [sys.executable, "-m", "ultimate_guillotine.cli.main"]


def test_video_help_lists_commands() -> None:
    result = subprocess.run([*UG, "video", "--help"], capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert "assets" in result.stdout


def test_assets_reports_missing_files_and_exits_1(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("UG_MEDIA_ROOT", str(tmp_path))
    monkeypatch.setattr(video_cli, "find_tool", lambda name: f"/opt/homebrew/bin/{name}")
    parser = argparse.ArgumentParser()
    video_cli.register(parser.add_subparsers())
    args = parser.parse_args(["video", "assets"])
    assert args.handler(args) == 1
    out = capsys.readouterr().out
    assert "MISSING" in out and "ffmpeg" in out
```

- [ ] **Step 3: Run them to see them fail**

Run: `uv run --project packages/league-automation pytest tests/video/test_assets.py tests/cli/test_video.py -q`
Expected: ImportError on `ultimate_guillotine.video`.

- [ ] **Step 4: Write `video/assets.py`**

```python
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
```

- [ ] **Step 5: Write `cli/video.py` with the `assets` command and register it**

```python
"""`ug video` subcommands: the trade announcement video pipeline.

``assets`` checks the archived reference media and the tools are in place.
Later tasks add ``card`` (the text layer alone), ``cost`` (what Higgsfield
would charge) and ``render`` (the whole video).
"""

import argparse

from ultimate_guillotine.video.assets import ToolMissing, find_tool, load_assets

TOOLS = ("ffmpeg", "ffprobe", "higgsfield")


def register(subparsers) -> None:
    parser = subparsers.add_parser("video", help="trade announcement video pipeline")
    video_sub = parser.add_subparsers(dest="command", required=True)

    assets = video_sub.add_parser("assets", help="check the reference media and tools are in place")
    assets.set_defaults(handler=cmd_assets)


def cmd_assets(args: argparse.Namespace) -> int:
    assets = load_assets()
    missing = assets.missing()
    ok = True
    for path in (assets.reference_video, assets.source_video, assets.music):
        state = "MISSING" if path in missing else "ok"
        print(f"{state:8}{path}")
    for name in TOOLS:
        try:
            print(f"{'ok':8}{name}  {find_tool(name)}")
        except ToolMissing as exc:
            ok = False
            print(f"{'MISSING':8}{name}  {exc}")
    if missing:
        print(f"{len(missing)} reference file(s) missing; see data/media/reference/README.md")
    return 0 if ok and not missing else 1
```

In `cli/main.py` add `video` to the import list and to the `for module in (...)` tuple after `history`.

- [ ] **Step 6: Run the tests**

Run: `uv run --project packages/league-automation pytest tests/video/test_assets.py tests/cli/test_video.py -q`
Expected: 7 passed.

- [ ] **Step 7: Check the real assets**

Run (repo root): `uv run --project packages/league-automation ug video assets` (or `python -m ultimate_guillotine.cli.main video assets`)
Expected: three `ok` lines for the files and three for the tools, exit 0.

- [ ] **Step 8: Commit**

```bash
git add packages/league-automation/pyproject.toml packages/league-automation/uv.lock packages/league-automation/src/ultimate_guillotine/video packages/league-automation/src/ultimate_guillotine/cli/video.py packages/league-automation/src/ultimate_guillotine/cli/main.py packages/league-automation/tests/video packages/league-automation/tests/cli/test_video.py
git commit -m "feat(video): media root, reference assets and ug video assets"
```

---

### Task 3: The words — `trades/format.py` public `party_receives`, `video/copy.py`

**Files:**
- Modify: `packages/league-automation/src/ultimate_guillotine/trades/format.py` (add `party_receives`, export it)
- Create: `packages/league-automation/src/ultimate_guillotine/video/copy.py`
- Test: `packages/league-automation/tests/video/test_copy.py`

**Interfaces:**
- Consumes: `TradeProposal`, `TradeParty`, `TradeAsset` from `trades/models.py`; `Labels` (`dict[int, str]`) from `trades/format.py`.
- Produces: `TradeCopy(caption: str, headline: str, subline: str, tag: str = "BREAKING NEWS")`; `trade_copy(proposal, labels=None, caption=None) -> TradeCopy`; `default_caption(names: list[str]) -> str`; `party_receives(proposal, member_id) -> str` in `trades/format.py`.

- [ ] **Step 1: Write the failing tests**

```python
from ultimate_guillotine.trades.format import party_receives
from ultimate_guillotine.trades.models import TradeAsset, TradeParty, TradeProposal
from ultimate_guillotine.video.copy import TradeCopy, default_caption, trade_copy


def proposal(**overrides) -> TradeProposal:
    fields = {
        "season": 2026,
        "effective_week": 3,
        "kind": "permanent",
        "parties": [TradeParty(1, "Member01"), TradeParty(2, "Member02")],
        "assets": [
            TradeAsset("player", 1, 2, "p1", "Player Alpha", None, None, None),
            TradeAsset("faab", 2, 1, None, None, 450, "faab", None),
        ],
        "source_message_guid": "g",
        "evidence_excerpt": "trade",
        "prompt_version": "t",
        "model": "t",
    }
    fields.update(overrides)
    return TradeProposal(**fields)


def test_party_receives_is_the_chat_wording() -> None:
    assert party_receives(proposal(), 2) == "Player Alpha"
    assert party_receives(proposal(), 1) == "450 FAAB"


def test_headline_names_the_player_and_who_gets_him_in_upper_case() -> None:
    copy = trade_copy(proposal(), labels={1: "Derek", 2: "Charlie"})
    assert copy.headline == "SOURCES: PLAYER ALPHA TRADED TO CHARLIE"


def test_subline_says_what_each_side_gets_and_the_week() -> None:
    copy = trade_copy(proposal(), labels={1: "Derek", 2: "Charlie"})
    assert copy.subline == "Derek gets 450 FAAB · Charlie gets Player Alpha · Week 3"


def test_labels_fall_back_to_the_stored_display_name() -> None:
    copy = trade_copy(proposal())
    assert copy.headline == "SOURCES: PLAYER ALPHA TRADED TO MEMBER02"
    assert copy.subline.startswith("Member01 gets 450 FAAB")


def test_a_trade_without_a_player_gets_the_parties_headline() -> None:
    faab_only = proposal(assets=[TradeAsset("faab", 2, 1, None, None, 450, "faab", None)])
    copy = trade_copy(faab_only, labels={1: "Derek", 2: "Charlie"})
    assert copy.headline == "SOURCES: DEREK AND CHARLIE AGREE TO A TRADE"


def test_caption_defaults_to_the_pov_line_and_can_be_overridden() -> None:
    assert default_caption(["Derek", "Charlie"]) == (
        "pov: the league chat when Derek and Charlie pull off a trade nobody saw coming"
    )
    copy = trade_copy(proposal(), caption="pov: me reading the trade alert at 2am")
    assert copy.caption == "pov: me reading the trade alert at 2am"
    assert copy.tag == "BREAKING NEWS"
    assert isinstance(copy, TradeCopy)


def test_no_week_means_no_week_on_the_subline() -> None:
    copy = trade_copy(proposal(effective_week=None), labels={1: "Derek", 2: "Charlie"})
    assert copy.subline == "Derek gets 450 FAAB · Charlie gets Player Alpha"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run --project packages/league-automation pytest tests/video/test_copy.py -q`
Expected: ImportError (`party_receives`, `ultimate_guillotine.video.copy`).

- [ ] **Step 3: Add `party_receives` to `trades/format.py`**

Add `"party_receives"` to `__all__` and, right after `_receives`:
```python
def party_receives(proposal: TradeProposal, member_id: int) -> str:
    """What one party gets, as chat text: players, then amounts, then other
    terms, or ``nothing``. Public because the trade video's lower third says
    the same thing the chat does."""
    return _receives(proposal, member_id)
```

- [ ] **Step 4: Write `video/copy.py`**

```python
"""The words on the video.

Two layers, both copied from the reference TikTok: a caption in the middle of
the footage ("pov: …", sentence case) and an ESPN-style lower third that
carries the actual trade -- a red tag, an upper-case headline, a subline that
says what each side gets in the chat's own wording.
"""

from dataclasses import dataclass

from ultimate_guillotine.trades.format import Labels, party_receives
from ultimate_guillotine.trades.models import TradeProposal

LEAGUE = "the Sovereign Guillotine League"


@dataclass(frozen=True)
class TradeCopy:
    caption: str
    headline: str
    subline: str
    tag: str = "BREAKING NEWS"


def default_caption(names: list[str]) -> str:
    if len(names) >= 2:
        return f"pov: the league chat when {names[0]} and {names[1]} pull off a trade nobody saw coming"
    if names:
        return f"pov: the league chat when {names[0]} pulls off a trade nobody saw coming"
    return "pov: the league chat when a trade nobody saw coming goes through"


def _names(proposal: TradeProposal, labels: Labels) -> list[str]:
    return [labels.get(party.member_id, party.display_name) for party in proposal.parties]


def _name_of(proposal: TradeProposal, labels: Labels, member_id: int | None) -> str | None:
    for party in proposal.parties:
        if party.member_id == member_id:
            return labels.get(party.member_id, party.display_name)
    return None


def headline(proposal: TradeProposal, labels: Labels) -> str:
    """``SOURCES: PLAYER TRADED TO OWNER`` when a named player moves; otherwise
    the two parties, the way ESPN would put a deal with no marquee name."""
    player = next((a for a in proposal.assets if a.kind == "player" and a.player_name), None)
    if player is not None:
        receiver = _name_of(proposal, labels, player.to_member_id)
        if receiver:
            return f"SOURCES: {player.player_name} TRADED TO {receiver}".upper()
        return f"SOURCES: {player.player_name} ON THE MOVE".upper()
    names = _names(proposal, labels)
    if len(names) >= 2:
        return f"SOURCES: {names[0]} AND {names[1]} AGREE TO A TRADE".upper()
    return f"SOURCES: TRADE AGREED IN {LEAGUE}".upper()


def subline(proposal: TradeProposal, labels: Labels) -> str:
    parts = [
        f"{labels.get(party.member_id, party.display_name)} gets "
        f"{party_receives(proposal, party.member_id)}"
        for party in proposal.parties
    ]
    if proposal.effective_week is not None:
        parts.append(f"Week {proposal.effective_week}")
    return " · ".join(parts)


def trade_copy(
    proposal: TradeProposal, labels: Labels | None = None, caption: str | None = None
) -> TradeCopy:
    labels = labels or {}
    return TradeCopy(
        caption=caption or default_caption(_names(proposal, labels)),
        headline=headline(proposal, labels),
        subline=subline(proposal, labels),
    )
```

- [ ] **Step 5: Run the tests**

Run: `uv run --project packages/league-automation pytest tests/video/test_copy.py tests/trades -q`
Expected: all pass (the trades suite proves `format_terms` is untouched).

- [ ] **Step 6: Commit**

```bash
git add packages/league-automation/src/ultimate_guillotine/trades/format.py packages/league-automation/src/ultimate_guillotine/video/copy.py packages/league-automation/tests/video/test_copy.py
git commit -m "feat(video): the caption and lower-third copy for a logged trade"
```

---

### Task 4: The text layer — `video/card.py`, `ug video card`

**Files:**
- Create: `packages/league-automation/src/ultimate_guillotine/video/card.py`
- Modify: `packages/league-automation/src/ultimate_guillotine/cli/video.py` (add `card`, the shared copy flags)
- Test: `packages/league-automation/tests/video/test_card.py`, `packages/league-automation/tests/cli/test_video.py`

**Interfaces:**
- Consumes: `TradeCopy`; fonts from `assets.py`.
- Produces: `Layout(width, height, video_top, video_bottom)` with `Layout.for_footage(footage_w, footage_h, aspect) -> Layout` (`aspect` is `"9:16"` or `"1:1"`); `wrap(text, max_chars) -> list[str]`; `render_card(copy, layout, out, fonts=DEFAULT_FONTS) -> Path`; `Fonts(caption, headline, subline)`; `CANVAS = {"9:16": (1080, 1920), "1:1": (1080, 1080)}`. In the CLI: `add_copy_args(parser)` (`--trade`, `--headline`, `--subline`, `--caption`) and `resolve_copy(args) -> TradeCopy`.

- [ ] **Step 1: Write the failing tests**

`tests/video/test_card.py`:
```python
from pathlib import Path

import pytest
from PIL import Image

from ultimate_guillotine.video.card import CANVAS, Layout, render_card, wrap
from ultimate_guillotine.video.copy import TradeCopy

COPY = TradeCopy(
    caption="pov: the league chat when Derek and Charlie pull off a trade nobody saw coming",
    headline="SOURCES: PLAYER ALPHA TRADED TO CHARLIE",
    subline="Derek gets 450 FAAB · Charlie gets Player Alpha · Week 3",
)


def test_wrap_breaks_on_words_and_never_splits_one() -> None:
    assert wrap("pov: you and that one friend who made the trade", 22) == [
        "pov: you and that one",
        "friend who made the",
        "trade",
    ]
    assert wrap("supercalifragilistic", 5) == ["supercalifragilistic"]


def test_layout_letterboxes_16_9_footage_into_9_16() -> None:
    layout = Layout.for_footage(1280, 720, "9:16")
    assert (layout.width, layout.height) == CANVAS["9:16"]
    assert layout.video_bottom - layout.video_top == 608
    assert layout.video_top == (1920 - 608) // 2


def test_layout_fills_the_square_canvas_for_1_1() -> None:
    layout = Layout.for_footage(1280, 720, "1:1")
    assert (layout.width, layout.height, layout.video_top, layout.video_bottom) == (1080, 1080, 0, 1080)


def test_layout_fills_the_canvas_with_vertical_footage() -> None:
    layout = Layout.for_footage(720, 1280, "9:16")
    assert (layout.video_top, layout.video_bottom) == (0, 1920)


def test_layout_rejects_an_unknown_aspect() -> None:
    with pytest.raises(ValueError, match="4:3"):
        Layout.for_footage(1280, 720, "4:3")


def test_card_is_a_transparent_png_with_the_caption_and_banner_painted(tmp_path: Path) -> None:
    layout = Layout.for_footage(1280, 720, "9:16")
    out = render_card(COPY, layout, tmp_path / "card.png")
    img = Image.open(out)
    assert img.mode == "RGBA" and img.size == (1080, 1920)
    # Letterbox above the footage stays clear.
    assert img.getpixel((540, 100))[3] == 0
    # The white bar of the lower third sits in the bottom quarter of the footage.
    bar_y = layout.video_bottom - 60
    assert img.getpixel((540, bar_y))[:3] == (255, 255, 255)
    # Something is painted where the caption block sits.
    band = img.crop((0, layout.video_top + 200, 1080, layout.video_top + 420))
    assert band.getbbox() is not None
```

Append to `tests/cli/test_video.py`:
```python
def test_card_writes_a_png_from_manual_copy(tmp_path) -> None:
    out = tmp_path / "card.png"
    result = subprocess.run(
        [*UG, "video", "card", "--headline", "SOURCES: X TRADED TO Y", "--subline", "Y gets X",
         "--caption", "pov: test", "--out", str(out)],
        capture_output=True, text=True, check=False,
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
    parser = argparse.ArgumentParser()
    video_cli.register(parser.add_subparsers())
    with pytest.raises(SystemExit):
        parser.parse_args(["video", "card", "--headline", "h", "--subline", "s", "--out", "x.png", "--aspect", "4:3"])
```
(add `import pytest` at the top of the file.)

- [ ] **Step 2: Run to verify they fail**

Run: `uv run --project packages/league-automation pytest tests/video/test_card.py tests/cli/test_video.py -q`
Expected: ImportError / unknown command `card`.

- [ ] **Step 3: Write `video/card.py`**

```python
"""The text layer, as one transparent PNG the size of the output frame.

Two things sit on it, both copied from the reference: the centred caption in
white with a black outline, and an ESPN-style lower third (red tag, white bar,
upper-case headline, smaller subline) across the bottom of the footage, where
the real ESPN banner sits in the source clip so it is covered. ffmpeg lays the
PNG over the footage; nothing is drawn with ffmpeg because this build has no
``drawtext`` filter.
"""

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ultimate_guillotine.video.assets import FONT_CAPTION, FONT_HEADLINE, FONT_SUBLINE

CANVAS: dict[str, tuple[int, int]] = {"9:16": (1080, 1920), "1:1": (1080, 1080)}

#: Sizes are for a 1080-wide canvas and scale with it.
CAPTION_SIZE = 56
CAPTION_STROKE = 4
CAPTION_MAX_CHARS = 22
CAPTION_MAX_LINES = 4
#: Where the caption block is centred, as a share of the footage height. The
#: reference sits it a touch below the middle.
CAPTION_CENTRE = 0.5
#: The lower third covers the bottom of the footage, where ESPN's own is.
BANNER_TOP_SHARE = 0.75
BANNER_BOTTOM_SHARE = 0.96
TAG_SIZE = 24
HEADLINE_SIZE = 44
SUBLINE_SIZE = 28
MARGIN = 24
PAD = 20
MIN_FONT = 16

WHITE = (255, 255, 255, 255)
BLACK = (0, 0, 0, 255)
INK = (20, 20, 20, 255)
GREY = (70, 70, 70, 255)
RED = (200, 16, 46, 255)
CLEAR = (0, 0, 0, 0)


@dataclass(frozen=True)
class Fonts:
    caption: Path = FONT_CAPTION
    headline: Path = FONT_HEADLINE
    subline: Path = FONT_SUBLINE


DEFAULT_FONTS = Fonts()


@dataclass(frozen=True)
class Layout:
    width: int
    height: int
    video_top: int
    video_bottom: int

    @property
    def video_height(self) -> int:
        return self.video_bottom - self.video_top

    @classmethod
    def for_footage(cls, footage_w: int, footage_h: int, aspect: str) -> "Layout":
        """Where the footage lands on the canvas: a 1:1 canvas is filled by a
        centre-square crop; a 9:16 canvas fits the footage by width and
        letterboxes the rest, so 16:9 footage sits in the middle third."""
        if aspect not in CANVAS:
            raise ValueError(f"unknown aspect {aspect}; use one of {', '.join(CANVAS)}")
        width, height = CANVAS[aspect]
        if aspect == "1:1":
            return cls(width, height, 0, height)
        scaled_h = min(height, _even(footage_h * width / footage_w))
        top = (height - scaled_h) // 2
        return cls(width, height, top, top + scaled_h)


def _even(value: float) -> int:
    return int(round(value / 2)) * 2


def wrap(text: str, max_chars: int) -> list[str]:
    """Greedy word wrap; a word longer than the line stands alone."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > max_chars:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size)


def _fit(draw: ImageDraw.ImageDraw, text: str, path: Path, size: int, max_width: float):
    """The largest font at or under ``size`` that keeps ``text`` on one line."""
    font = _font(path, size)
    while size > MIN_FONT and draw.textlength(text, font=font) > max_width:
        size -= 2
        font = _font(path, size)
    return font


def render_card(copy, layout: Layout, out: Path, fonts: Fonts = DEFAULT_FONTS) -> Path:
    scale = layout.width / 1080
    img = Image.new("RGBA", (layout.width, layout.height), CLEAR)
    draw = ImageDraw.Draw(img)

    # The caption, centred on the footage.
    caption_font = _font(fonts.caption, round(CAPTION_SIZE * scale))
    lines = wrap(copy.caption, CAPTION_MAX_CHARS)[:CAPTION_MAX_LINES]
    line_h = round(CAPTION_SIZE * scale * 1.18)
    y = layout.video_top + round(layout.video_height * CAPTION_CENTRE) - (line_h * len(lines)) // 2
    for line in lines:
        x = (layout.width - draw.textlength(line, font=caption_font)) / 2
        draw.text(
            (x, y), line, font=caption_font, fill=WHITE,
            stroke_width=round(CAPTION_STROKE * scale), stroke_fill=BLACK,
        )
        y += line_h

    # The lower third: red tag over a white bar, across the bottom of the footage.
    margin, pad = round(MARGIN * scale), round(PAD * scale)
    bar_top = layout.video_top + round(layout.video_height * BANNER_TOP_SHARE)
    bar_bottom = layout.video_top + round(layout.video_height * BANNER_BOTTOM_SHARE)
    draw.rounded_rectangle(
        (margin, bar_top, layout.width - margin, bar_bottom), radius=round(8 * scale), fill=WHITE
    )
    tag_font = _font(fonts.headline, round(TAG_SIZE * scale))
    tag_h = round(TAG_SIZE * scale * 1.7)
    tag_w = draw.textlength(copy.tag, font=tag_font) + 2 * pad
    tag_left = (layout.width - tag_w) / 2
    draw.rectangle((tag_left, bar_top - tag_h + round(6 * scale), tag_left + tag_w, bar_top + round(6 * scale)), fill=RED)
    draw.text((tag_left + pad, bar_top - tag_h + round(12 * scale)), copy.tag, font=tag_font, fill=WHITE)

    text_width = layout.width - 2 * margin - 2 * pad
    headline_font = _fit(draw, copy.headline, fonts.headline, round(HEADLINE_SIZE * scale), text_width)
    draw.text((margin + pad, bar_top + round(16 * scale)), copy.headline, font=headline_font, fill=INK)
    subline_font = _fit(draw, copy.subline, fonts.subline, round(SUBLINE_SIZE * scale), text_width)
    sub_y = bar_top + round(16 * scale) + round(HEADLINE_SIZE * scale * 1.25)
    draw.text((margin + pad, sub_y), copy.subline, font=subline_font, fill=GREY)

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out
```

- [ ] **Step 4: Add the `card` command and the shared copy flags to `cli/video.py`**

```python
import argparse
from pathlib import Path

from ultimate_guillotine.cli.deps import build_deps
from ultimate_guillotine.data.repositories import MemberAliasRepository
from ultimate_guillotine.trades.format import party_labels
from ultimate_guillotine.trades.models import TradeProposal
from ultimate_guillotine.trades.repository import TradeRepository
from ultimate_guillotine.video.assets import ToolMissing, find_tool, load_assets
from ultimate_guillotine.video.card import CANVAS, Layout, render_card
from ultimate_guillotine.video.copy import TradeCopy, default_caption, trade_copy

#: The ESPN source clip's frame; the card for manual copy is laid out for it.
SOURCE_FRAME = (1280, 720)


def add_copy_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--trade", metavar="TRADE_CODE", help="a logged trade to announce")
    parser.add_argument("--headline", help="lower-third headline, instead of a logged trade")
    parser.add_argument("--subline", help="lower-third subline, instead of a logged trade")
    parser.add_argument("--caption", help="the centred caption; default is the pov: line")
    parser.add_argument("--aspect", choices=tuple(CANVAS), default="9:16")


def resolve_copy(args: argparse.Namespace) -> TradeCopy:
    """The words, from a logged trade or from the flags."""
    if args.trade:
        deps = build_deps()
        trade = TradeRepository(deps.conn).find_by_code(args.trade)
        if trade is None:
            raise SystemExit(f"no trade {args.trade} on file")
        labels = party_labels(MemberAliasRepository(deps.conn).all_members())
        return trade_copy(TradeProposal(**trade["terms"]), labels, caption=args.caption)
    if not (args.headline and args.subline):
        raise SystemExit("ug video: give --trade or both --headline and --subline")
    return TradeCopy(
        caption=args.caption or default_caption([]), headline=args.headline, subline=args.subline
    )
```
`register` gains:
```python
    card = video_sub.add_parser("card", help="render only the text layer, to check the words")
    add_copy_args(card)
    card.add_argument("--out", required=True, type=Path, help="where to write the PNG")
    card.set_defaults(handler=cmd_card)
```
and the handler:
```python
def cmd_card(args: argparse.Namespace) -> int:
    copy = resolve_copy(args)
    layout = Layout.for_footage(*SOURCE_FRAME, args.aspect)
    print(render_card(copy, layout, args.out))
    return 0
```
`SystemExit(str)` exits 1 with the message on stderr; the test wants 2 for a usage error, so raise it through the parser instead: `resolve_copy` takes the parser too, or simpler, in `cmd_card` catch nothing and let `main` print — **decision:** `resolve_copy(args, parser)` calls `parser.error(...)` for the usage case (exit 2, message on stderr) and keeps `SystemExit` for the missing trade. Store the parser on the args with `card.set_defaults(handler=cmd_card, parser=card)`.

- [ ] **Step 5: Run the tests**

Run: `uv run --project packages/league-automation pytest tests/video tests/cli/test_video.py -q`
Expected: all pass.

- [ ] **Step 6: Look at a card**

Run: `uv run --project packages/league-automation python -m ultimate_guillotine.cli.main video card --headline "SOURCES: JOSH JACOBS TRADED TO CHARLIE" --subline "Derek gets 450 FAAB · Charlie gets Josh Jacobs · Week 3" --out data/media/work/card-check.png`
Open the PNG. The caption should read like the reference (white, outlined, centred), the red tag should sit centred on the top edge of the white bar, the headline must fit on one line.

- [ ] **Step 7: Commit**

```bash
git add packages/league-automation/src/ultimate_guillotine/video/card.py packages/league-automation/src/ultimate_guillotine/cli/video.py packages/league-automation/tests/video/test_card.py packages/league-automation/tests/cli/test_video.py
git commit -m "feat(video): the caption and lower-third text layer, and ug video card"
```

---

### Task 5: The composite — `video/ffmpeg.py`

**Files:**
- Create: `packages/league-automation/src/ultimate_guillotine/video/ffmpeg.py`
- Test: `packages/league-automation/tests/video/test_ffmpeg.py`

**Interfaces:**
- Produces: `Composite` (frozen dataclass: `footage: Path`, `card: Path`, `music: Path`, `output: Path`, `aspect: str = "9:16"`, `footage_start: float = 0.0`, `duration: float = 24.0`, `music_offset: float = 0.0`, `music_gain_db: float = 0.0`, `keep_voice: bool = False`, `voice_gain_db: float = -10.0`, `fps: int = 30`); `video_filter(c, footage_w, footage_h) -> str`; `filter_graph(c, footage_w, footage_h) -> str`; `command(c, footage_w, footage_h, ffmpeg="ffmpeg") -> list[str]`; `probe(path, ffprobe="ffprobe", run=subprocess.run) -> Probe(width, height, duration)`; `run(cmd, run=subprocess.run) -> None` raising `FfmpegError`.

- [ ] **Step 1: Write the failing tests**

```python
import shutil
import subprocess
from pathlib import Path

import pytest

from ultimate_guillotine.video import ffmpeg as ff
from ultimate_guillotine.video.card import Layout, render_card
from ultimate_guillotine.video.copy import TradeCopy


def composite(**overrides) -> ff.Composite:
    fields = dict(footage=Path("f.mp4"), card=Path("c.png"), music=Path("m.m4a"), output=Path("o.mp4"))
    fields.update(overrides)
    return ff.Composite(**fields)


def test_9_16_letterboxes_the_footage_and_overlays_the_card() -> None:
    graph = ff.filter_graph(composite(), 1280, 720)
    assert graph.startswith("[0:v]scale=1080:608,pad=1080:1920:0:656:black[footage];")
    assert "[footage][1:v]overlay=0:0:shortest=1[v]" in graph
    assert graph.endswith("[2:a]volume=0.0dB[a]")


def test_1_1_crops_the_centre_square() -> None:
    graph = ff.filter_graph(composite(aspect="1:1"), 1280, 720)
    assert graph.startswith("[0:v]crop=min(iw\\,ih):min(iw\\,ih),scale=1080:1080[footage];")


def test_keep_voice_mixes_the_footage_audio_under_the_music() -> None:
    graph = ff.filter_graph(composite(keep_voice=True, music_gain_db=-3), 1280, 720)
    assert "[0:a]volume=-10.0dB[voice]" in graph
    assert "[2:a]volume=-3.0dB[music]" in graph
    assert graph.endswith("[voice][music]amix=inputs=2:duration=first:normalize=0[a]")


def test_command_seeks_both_inputs_and_encodes_h264_aac() -> None:
    cmd = ff.command(composite(footage_start=2.5, duration=24, music_offset=1.0), 1280, 720, ffmpeg="/opt/homebrew/bin/ffmpeg")
    assert cmd[0] == "/opt/homebrew/bin/ffmpeg"
    assert cmd[cmd.index("-i") - 4:cmd.index("-i")] == ["-ss", "2.5", "-t", "24.0"]
    assert "-loop" in cmd and cmd[cmd.index("-loop") + 1] == "1"
    music_i = [i for i, a in enumerate(cmd) if a == "-i"][2]
    assert cmd[music_i - 4:music_i] == ["-ss", "1.0", "-t", "24.0"]
    assert cmd[-1] == "o.mp4"
    for flag, value in (("-c:v", "libx264"), ("-c:a", "aac"), ("-pix_fmt", "yuv420p"), ("-r", "30")):
        assert cmd[cmd.index(flag) + 1] == value


def test_probe_reads_the_first_video_stream_and_the_duration() -> None:
    def fake_run(cmd, **_kwargs):
        assert cmd[0] == "ffprobe" and str(cmd[-1]) == "f.mp4"
        return subprocess.CompletedProcess(cmd, 0, stdout='{"streams":[{"codec_type":"audio"},{"codec_type":"video","width":1280,"height":720}],"format":{"duration":"127.22"}}')
    assert ff.probe(Path("f.mp4"), run=fake_run) == ff.Probe(1280, 720, 127.22)


def test_run_turns_a_failed_encode_into_a_plain_error() -> None:
    def fake_run(cmd, **_kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="Unknown encoder 'x'")
    with pytest.raises(ff.FfmpegError, match="Unknown encoder"):
        ff.run(["ffmpeg"], run=fake_run)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_a_real_two_second_composite_encodes(tmp_path: Path) -> None:
    footage, music, card, out = (tmp_path / n for n in ("f.mp4", "m.m4a", "c.png", "o.mp4"))
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=30:duration=3", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(footage)], check=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-c:a", "aac", str(music)], check=True)
    layout = Layout.for_footage(320, 180, "9:16")
    render_card(TradeCopy("pov: test", "SOURCES: TEST", "a gets b"), layout, card)
    c = ff.Composite(footage=footage, card=card, music=music, output=out, footage_start=0.5, duration=1.5)
    ff.run(ff.command(c, 320, 180))
    probe = ff.probe(out)
    assert (probe.width, probe.height) == (1080, 1920)
    assert 1.3 <= probe.duration <= 1.8
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run --project packages/league-automation pytest tests/video/test_ffmpeg.py -q`
Expected: ImportError.

- [ ] **Step 3: Write `video/ffmpeg.py`**

```python
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
    return int(round(value / 2)) * 2


def video_filter(c: Composite, footage_w: int, footage_h: int) -> str:
    width, height = CANVAS[c.aspect]
    if c.aspect == "1:1":
        return f"[0:v]crop=min(iw\\,ih):min(iw\\,ih),scale={width}:{height}[footage]"
    scaled_h = _even(footage_h * width / footage_w)
    if scaled_h > height:
        scaled_w = _even(footage_w * height / footage_h)
        return f"[0:v]scale={scaled_w}:{height},pad={width}:{height}:{(width - scaled_w) // 2}:0:black[footage]"
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
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{float(c.footage_start)}", "-t", duration, "-i", str(c.footage),
        "-loop", "1", "-framerate", str(c.fps), "-i", str(c.card),
        "-ss", f"{float(c.music_offset)}", "-t", duration, "-i", str(c.music),
        "-filter_complex", filter_graph(c, footage_w, footage_h),
        "-map", "[v]", "-map", "[a]", "-t", duration, "-r", str(c.fps),
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
        str(c.output),
    ]


def probe(path: Path, ffprobe: str = "ffprobe", run=subprocess.run) -> Probe:
    cmd = [ffprobe, "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration", "-of", "json", str(path)]
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
```

- [ ] **Step 4: Run the tests**

Run: `uv run --project packages/league-automation pytest tests/video/test_ffmpeg.py -q`
Expected: 7 passed (the lavfi test takes a few seconds).

- [ ] **Step 5: Commit**

```bash
git add packages/league-automation/src/ultimate_guillotine/video/ffmpeg.py packages/league-automation/tests/video/test_ffmpeg.py
git commit -m "feat(video): ffmpeg composite of footage, text layer and music"
```

---

### Task 6: Generated footage — `video/higgsfield.py`, `video/prompt.py`, `ug video cost`

**Files:**
- Create: `packages/league-automation/src/ultimate_guillotine/video/higgsfield.py`, `packages/league-automation/src/ultimate_guillotine/video/prompt.py`
- Modify: `packages/league-automation/src/ultimate_guillotine/cli/video.py` (add `cost`)
- Test: `packages/league-automation/tests/video/test_higgsfield.py`, `packages/league-automation/tests/video/test_prompt.py`, `packages/league-automation/tests/cli/test_video.py`

**Interfaces:**
- Consumes: `TradeCopy`; `Assets.reference_video`.
- Produces: `GenerateRequest(prompt, reference_video: Path | None = None, duration: int = 8, resolution: str = "720p", aspect_ratio: str = "9:16", generate_audio: bool = False)` with property `mode` (`"omni_reference"` with a reference, else `"t2v"`); `create_command(req, binary="higgsfield") -> list[str]`; `cost_command(req, binary="higgsfield") -> list[str]`; `parse_credits(stdout) -> int`; `parse_result_url(stdout) -> str`; `run(cmd, run=subprocess.run) -> str`; `download(url, dest, client=None) -> Path`; `generate_clip(req, dest, binary="higgsfield", runner=run, fetch=download) -> Path`; `HiggsfieldError`; `footage_prompt(copy: TradeCopy, seconds: int) -> str`.

- [ ] **Step 1: Write the failing tests**

`tests/video/test_higgsfield.py`:
```python
import json
import subprocess
from pathlib import Path

import pytest

from ultimate_guillotine.video import higgsfield as hf


def test_a_reference_makes_it_an_omni_reference_job() -> None:
    req = hf.GenerateRequest(prompt="anchor", reference_video=Path("ref.mp4"), duration=8)
    cmd = hf.create_command(req, binary="/opt/homebrew/bin/higgsfield")
    assert cmd[:4] == ["/opt/homebrew/bin/higgsfield", "generate", "create", "seedance_2_5"]
    assert cmd[cmd.index("--mode") + 1] == "omni_reference"
    assert cmd[cmd.index("--video-references") + 1] == "ref.mp4"
    assert cmd[cmd.index("--generate_audio") + 1] == "false"
    assert cmd[-4:] == ["--wait", "--wait-timeout", "20m", "--json"]


def test_no_reference_is_text_to_video() -> None:
    cmd = hf.cost_command(hf.GenerateRequest(prompt="anchor"))
    assert cmd[:4] == ["higgsfield", "generate", "cost", "seedance_2_5"]
    assert cmd[cmd.index("--mode") + 1] == "t2v" and "--video-references" not in cmd
    assert cmd[-1] == "--json"


def test_parse_credits() -> None:
    assert hf.parse_credits('{"credits": 52}\n') == 52


def test_result_url_comes_from_the_job_document() -> None:
    doc = {"id": "j1", "status": "completed", "result_url": "https://cdn/x.mp4", "params": {}}
    assert hf.parse_result_url(json.dumps(doc)) == "https://cdn/x.mp4"


def test_result_url_falls_back_to_any_mp4_url_in_the_output() -> None:
    assert hf.parse_result_url("done: https://cdn/y.mp4\n") == "https://cdn/y.mp4"
    with pytest.raises(hf.HiggsfieldError):
        hf.parse_result_url('{"status": "failed"}')


def test_run_reports_the_cli_error() -> None:
    def fake_run(cmd, **_k):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="Error: Session expired")
    with pytest.raises(hf.HiggsfieldError, match="Session expired"):
        hf.run(["higgsfield"], run=fake_run)


def test_generate_clip_runs_the_job_and_fetches_the_result(tmp_path: Path) -> None:
    seen = {}
    def runner(cmd):
        seen["cmd"] = cmd
        return '{"result_url": "https://cdn/z.mp4"}'
    def fetch(url, dest):
        seen["url"] = url
        dest.write_bytes(b"mp4")
        return dest
    out = hf.generate_clip(hf.GenerateRequest(prompt="p"), tmp_path / "gen.mp4", runner=runner, fetch=fetch)
    assert out.read_bytes() == b"mp4" and seen["url"] == "https://cdn/z.mp4"
    assert seen["cmd"][cmd_index := seen["cmd"].index("--prompt") + 1] == "p" and cmd_index > 0
```

`tests/video/test_prompt.py`:
```python
from ultimate_guillotine.video.copy import TradeCopy
from ultimate_guillotine.video.prompt import footage_prompt


def test_prompt_describes_the_anchor_and_bans_on_screen_text() -> None:
    copy = TradeCopy("pov: x", "SOURCES: PLAYER ALPHA TRADED TO CHARLIE", "Derek gets 450 FAAB · Charlie gets Player Alpha")
    prompt = footage_prompt(copy, seconds=8)
    assert "00:00-00:08" in prompt
    assert "no on-screen text" in prompt and "no lower third" in prompt
    assert "Derek gets 450 FAAB" in prompt
    assert "9:16" in prompt
```

Append to `tests/cli/test_video.py`:
```python
def test_cost_prints_the_credits_without_spending_any(monkeypatch, capsys) -> None:
    from ultimate_guillotine.video import higgsfield as hf
    monkeypatch.setattr(video_cli, "find_tool", lambda name: f"/opt/homebrew/bin/{name}")
    monkeypatch.setattr(hf, "run", lambda cmd: '{"credits": 52}')
    parser = argparse.ArgumentParser()
    video_cli.register(parser.add_subparsers())
    args = parser.parse_args(["video", "cost", "--headline", "h", "--subline", "s"])
    assert args.handler(args) == 0
    assert capsys.readouterr().out.strip() == "52 credits for one 8 s 720p 9:16 clip"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run --project packages/league-automation pytest tests/video/test_higgsfield.py tests/video/test_prompt.py tests/cli/test_video.py -q`
Expected: ImportError / unknown command `cost`.

- [ ] **Step 3: Write `video/higgsfield.py`**

```python
"""Footage from Seedance 2.5 on Higgsfield, through the ``higgsfield`` CLI.

The CLI is already installed and logged in (the ugc-studio account). A job is
one ``generate create`` call with ``--wait --json``; the finished job document
carries ``result_url``, which is fetched into the media folder. Every call is
injectable so the tests never spend credits.
"""

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import httpx

MODEL = "seedance_2_5"
WAIT_TIMEOUT = "20m"
_MP4_URL = re.compile(r"https://[^\s\"']+\.mp4")


class HiggsfieldError(RuntimeError):
    """The CLI failed or its output carried no result."""


@dataclass(frozen=True)
class GenerateRequest:
    prompt: str
    reference_video: Path | None = None
    duration: int = 8
    resolution: str = "720p"
    aspect_ratio: str = "9:16"
    generate_audio: bool = False

    @property
    def mode(self) -> str:
        return "omni_reference" if self.reference_video else "t2v"


def _params(req: GenerateRequest) -> list[str]:
    params = [
        "--prompt", req.prompt, "--mode", req.mode, "--duration", str(req.duration),
        "--resolution", req.resolution, "--aspect_ratio", req.aspect_ratio,
        "--generate_audio", "true" if req.generate_audio else "false",
    ]
    if req.reference_video is not None:
        params += ["--video-references", str(req.reference_video)]
    return params


def create_command(req: GenerateRequest, binary: str = "higgsfield") -> list[str]:
    return [binary, "generate", "create", MODEL, *_params(req), "--wait", "--wait-timeout", WAIT_TIMEOUT, "--json"]


def cost_command(req: GenerateRequest, binary: str = "higgsfield") -> list[str]:
    return [binary, "generate", "cost", MODEL, *_params(req), "--json"]


def parse_credits(stdout: str) -> int:
    return int(json.loads(stdout)["credits"])


def _find(obj, key: str):
    if isinstance(obj, dict):
        if key in obj and obj[key]:
            return obj[key]
        for value in obj.values():
            found = _find(value, key)
            if found:
                return found
    if isinstance(obj, list):
        for value in obj:
            found = _find(value, key)
            if found:
                return found
    return None


def parse_result_url(stdout: str) -> str:
    """The finished job's video: ``result_url`` in the job document (the shape
    ``higgsfield generate list --json`` shows), else any .mp4 URL in the output."""
    try:
        doc = json.loads(stdout)
    except json.JSONDecodeError:
        doc = None
    url = _find(doc, "result_url") if doc is not None else None
    if not url:
        match = _MP4_URL.search(stdout)
        if match is None:
            raise HiggsfieldError("higgsfield finished without a result url")
        url = match.group(0)
    return url


def run(cmd: list[str], run=subprocess.run) -> str:
    result = run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise HiggsfieldError((result.stderr or result.stdout).strip()[-500:] or "higgsfield failed")
    return result.stdout


def download(url: str, dest: Path, client: httpx.Client | None = None) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    client = client or httpx.Client(follow_redirects=True, timeout=120)
    with client.stream("GET", url) as response:
        response.raise_for_status()
        with dest.open("wb") as fh:
            for chunk in response.iter_bytes():
                fh.write(chunk)
    return dest


def generate_clip(req: GenerateRequest, dest: Path, binary: str = "higgsfield", runner=run, fetch=download) -> Path:
    return fetch(parse_result_url(runner(create_command(req, binary))), dest)
```

- [ ] **Step 4: Write `video/prompt.py`**

```python
"""The Seedance prompt for generated footage.

Shot-breakdown form, like ugc-studio's ``prompts/seedance.md``. The words of
the trade go in as context only: the text layer is ours, so the model is told
to render no text at all -- generated captions are never right.
"""

from ultimate_guillotine.video.copy import TradeCopy


def footage_prompt(copy: TradeCopy, seconds: int) -> str:
    end = f"00:{seconds:02d}"
    return (
        "subject: a veteran NFL insider in a navy blazer and open collar, reporting from his "
        "home office, floor-to-ceiling bookshelves behind him, a football helmet on a shelf\n"
        "camera: static broadcast framing, chest-up, centred, 9:16 vertical\n"
        "audio: none\n"
        f"00:00-{end}  he delivers breaking news straight to lens with urgency, small emphatic "
        "hand gestures, eyebrows up on the key line, a beat of disbelief near the end\n"
        f"context, not to be shown: he is reporting that {copy.subline.lower()}\n"
        "no on-screen text, no lower third, no captions, no logos, no ticker; "
        "match the framing, lighting and pacing of the reference video; realistic skin, "
        "no beauty filter"
    )
```

- [ ] **Step 5: Add `cost` to `cli/video.py`**

```python
from ultimate_guillotine.video import higgsfield as hf
from ultimate_guillotine.video.prompt import footage_prompt

    cost = video_sub.add_parser("cost", help="what Higgsfield charges for one generated clip")
    add_copy_args(cost)
    cost.add_argument("--duration", type=int, default=8, help="seconds of generated footage")
    cost.add_argument("--resolution", default="720p", choices=("480p", "720p", "1080p"))
    cost.set_defaults(handler=cmd_cost, parser=cost)


def generate_request(copy: TradeCopy, args: argparse.Namespace):
    return hf.GenerateRequest(
        prompt=footage_prompt(copy, args.duration),
        reference_video=load_assets().reference_video,
        duration=args.duration,
        resolution=args.resolution,
        aspect_ratio=args.aspect,
    )


def cmd_cost(args: argparse.Namespace) -> int:
    req = generate_request(resolve_copy(args), args)
    credits = hf.parse_credits(hf.run(hf.cost_command(req, find_tool("higgsfield"))))
    print(f"{credits} credits for one {req.duration} s {req.resolution} {req.aspect_ratio} clip")
    return 0
```

- [ ] **Step 6: Run the tests**

Run: `uv run --project packages/league-automation pytest tests/video tests/cli/test_video.py -q`
Expected: all pass.

- [ ] **Step 7: Ask Higgsfield for the real price (no credits spent)**

Run: `uv run --project packages/league-automation python -m ultimate_guillotine.cli.main video cost --headline "SOURCES: X TRADED TO Y" --subline "Y gets X"`
Expected: `52 credits for one 8 s 720p 9:16 clip` (the figure measured 2026-09-10).

- [ ] **Step 8: Commit**

```bash
git add packages/league-automation/src/ultimate_guillotine/video packages/league-automation/src/ultimate_guillotine/cli/video.py packages/league-automation/tests/video packages/league-automation/tests/cli/test_video.py
git commit -m "feat(video): Seedance 2.5 footage through the higgsfield CLI, and ug video cost"
```

---

### Task 7: The pipeline — `video/pipeline.py`, `ug video render`

**Files:**
- Create: `packages/league-automation/src/ultimate_guillotine/video/pipeline.py`
- Modify: `packages/league-automation/src/ultimate_guillotine/cli/video.py` (add `render`)
- Test: `packages/league-automation/tests/video/test_pipeline.py`, `packages/league-automation/tests/cli/test_video.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `RenderRequest(copy, base: str = "source", aspect: str = "9:16", duration: float = REFERENCE_DURATION, keep_voice: bool = False, music_gain_db: float = 0.0, name: str = "trade", generate_seconds: int = 8, resolution: str = "720p")`; `Job(card: Path, footage: Path, footage_start: float, duration: float, composite: Composite, command: list[str])`; `prepare(req, assets, *, ffmpeg, ffprobe, probe=ff.probe, generate=hf.generate_clip, now=datetime.now) -> Job`; `render(req, assets, *, run=ff.run, **prepare_kwargs) -> Job`; `RenderError`.

- [ ] **Step 1: Write the failing tests**

`tests/video/test_pipeline.py`:
```python
from datetime import datetime
from pathlib import Path

import pytest

from ultimate_guillotine.video import ffmpeg as ff
from ultimate_guillotine.video.assets import SOURCE_CLIP_START, Assets
from ultimate_guillotine.video.copy import TradeCopy
from ultimate_guillotine.video.pipeline import RenderError, RenderRequest, prepare, render

COPY = TradeCopy("pov: x", "SOURCES: PLAYER ALPHA TRADED TO CHARLIE", "Derek gets 450 FAAB · Charlie gets Player Alpha")
NOW = lambda: datetime(2026, 9, 10, 2, 30, 0)  # noqa: E731


def fake_probe(path, ffprobe="ffprobe", run=None):
    return ff.Probe(1280, 720, 127.2) if "espn" in str(path) else ff.Probe(720, 1280, 8.0)


@pytest.fixture
def assets(tmp_path: Path) -> Assets:
    a = Assets(tmp_path)
    for path in (a.reference_video, a.source_video, a.music):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
    return a


def test_source_base_cuts_the_espn_clip_at_the_measured_start(assets: Assets) -> None:
    job = prepare(RenderRequest(COPY, name="T-2026-001"), assets, ffmpeg="ffmpeg", ffprobe="ffprobe", probe=fake_probe, now=NOW)
    assert job.footage == assets.source_video and job.footage_start == SOURCE_CLIP_START
    assert job.duration == 24.0
    assert job.card == assets.work / "T-2026-001-20260910-023000-card.png" and job.card.exists()
    assert job.composite.output == assets.renders / "T-2026-001-20260910-023000.mp4"
    assert job.command[0] == "ffmpeg" and "scale=1080:608" in " ".join(job.command)


def test_generated_base_asks_higgsfield_with_the_reference_and_clamps_the_length(assets: Assets) -> None:
    seen = {}
    def fake_generate(req, dest):
        seen["req"], seen["dest"] = req, dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"")
        return dest
    job = prepare(RenderRequest(COPY, base="generated", name="t"), assets, ffmpeg="ffmpeg", ffprobe="ffprobe", probe=fake_probe, generate=fake_generate, now=NOW)
    assert seen["req"].reference_video == assets.reference_video and seen["req"].mode == "omni_reference"
    assert seen["req"].duration == 8 and "no on-screen text" in seen["req"].prompt
    assert job.footage == assets.generated / "t-20260910-023000.mp4" and job.footage_start == 0.0
    assert job.duration == 8.0


def test_a_path_base_is_used_as_is(assets: Assets, tmp_path: Path) -> None:
    clip = tmp_path / "mine.mp4"
    clip.write_bytes(b"")
    job = prepare(RenderRequest(COPY, base=str(clip), duration=5), assets, ffmpeg="ffmpeg", ffprobe="ffprobe", probe=fake_probe, now=NOW)
    assert job.footage == clip and job.duration == 5.0


def test_missing_reference_files_are_reported_before_anything_runs(tmp_path: Path) -> None:
    with pytest.raises(RenderError, match="missing"):
        prepare(RenderRequest(COPY), Assets(tmp_path), ffmpeg="ffmpeg", ffprobe="ffprobe", probe=fake_probe, now=NOW)


def test_render_runs_the_command(assets: Assets) -> None:
    ran = []
    job = render(RenderRequest(COPY), assets, run=lambda cmd: ran.append(cmd), ffmpeg="ffmpeg", ffprobe="ffprobe", probe=fake_probe, now=NOW)
    assert ran == [job.command]
```

Append to `tests/cli/test_video.py`:
```python
def test_render_dry_run_prints_the_ffmpeg_command_and_encodes_nothing(tmp_path, monkeypatch, capsys) -> None:
    from ultimate_guillotine.video import ffmpeg as ff
    from ultimate_guillotine.video.assets import Assets
    a = Assets(tmp_path)
    for path in (a.reference_video, a.source_video, a.music):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
    monkeypatch.setenv("UG_MEDIA_ROOT", str(tmp_path))
    monkeypatch.setattr(video_cli, "find_tool", lambda name: f"/opt/homebrew/bin/{name}")
    monkeypatch.setattr(ff, "probe", lambda path, ffprobe="ffprobe", run=None: ff.Probe(1280, 720, 127.0))
    parser = argparse.ArgumentParser()
    video_cli.register(parser.add_subparsers())
    args = parser.parse_args(["video", "render", "--headline", "h", "--subline", "s", "--dry-run"])
    assert args.handler(args) == 0
    out = capsys.readouterr().out
    assert out.startswith("/opt/homebrew/bin/ffmpeg ") and "-c:v libx264" in out
    assert not list(a.renders.glob("*.mp4")) if a.renders.exists() else True
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run --project packages/league-automation pytest tests/video/test_pipeline.py tests/cli/test_video.py -q`
Expected: ImportError / unknown command `render`.

- [ ] **Step 3: Write `video/pipeline.py`**

```python
"""One trade in, one video out.

``prepare`` does everything but the encode: it checks the reference media,
draws the text layer, picks the footage (the archived ESPN clip at the measured
start, a Seedance clip generated from the reference, or a file Ben points at),
probes it, and builds the ffmpeg command. ``render`` runs that command. The
split is what `--dry-run` and the tests use.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ultimate_guillotine.video import ffmpeg as ff
from ultimate_guillotine.video import higgsfield as hf
from ultimate_guillotine.video.assets import MUSIC_OFFSET, REFERENCE_DURATION, SOURCE_CLIP_START, Assets
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
    req: RenderRequest, assets: Assets, *, ffmpeg: str, ffprobe: str,
    probe=ff.probe, generate=hf.generate_clip, now=datetime.now,
) -> Job:
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
        footage=footage, card=card, music=assets.music, output=assets.renders / f"{stamp}.mp4",
        aspect=req.aspect, footage_start=start, duration=duration, music_offset=MUSIC_OFFSET,
        music_gain_db=req.music_gain_db, keep_voice=req.keep_voice,
    )
    return Job(card, footage, start, duration, composite, ff.command(composite, info.width, info.height, ffmpeg))


def render(req: RenderRequest, assets: Assets, *, run=ff.run, **prepare_kwargs) -> Job:
    job = prepare(req, assets, **prepare_kwargs)
    run(job.command)
    return job
```

- [ ] **Step 4: Add `render` to `cli/video.py`**

```python
import shlex

from ultimate_guillotine.video.assets import REFERENCE_DURATION
from ultimate_guillotine.video.pipeline import RenderError, RenderRequest, prepare, render

    rend = video_sub.add_parser("render", help="render a trade announcement video")
    add_copy_args(rend)
    rend.add_argument("--base", default="source", help="source (the ESPN clip), generated (Seedance 2.5, costs credits), or a path to footage")
    rend.add_argument("--duration", type=float, default=REFERENCE_DURATION, help="seconds; default matches the reference")
    rend.add_argument("--keep-voice", action="store_true", help="keep the footage's own audio under the music")
    rend.add_argument("--music-gain", type=float, default=0.0, help="music level in dB, e.g. -3")
    rend.add_argument("--generate-seconds", type=int, default=8, help="length of a generated clip")
    rend.add_argument("--resolution", default="720p", choices=("480p", "720p", "1080p"))
    rend.add_argument("--dry-run", action="store_true", help="print the ffmpeg command; encode and generate nothing")
    rend.set_defaults(handler=cmd_render, parser=rend)


def cmd_render(args: argparse.Namespace) -> int:
    copy = resolve_copy(args)
    req = RenderRequest(
        copy=copy, base=args.base, aspect=args.aspect, duration=args.duration,
        keep_voice=args.keep_voice, music_gain_db=args.music_gain, name=args.trade or "manual",
        generate_seconds=args.generate_seconds, resolution=args.resolution,
    )
    if args.dry_run and req.base == "generated":
        args.parser.error("--dry-run cannot generate footage; use --base source or a path")
    try:
        ffmpeg, ffprobe = find_tool("ffmpeg"), find_tool("ffprobe")
        if args.dry_run:
            job = prepare(req, load_assets(), ffmpeg=ffmpeg, ffprobe=ffprobe)
            print(" ".join(shlex.quote(part) for part in job.command))
            return 0
        job = render(req, load_assets(), ffmpeg=ffmpeg, ffprobe=ffprobe)
    except (RenderError, ToolMissing) as exc:
        print(f"ug video render: {exc}", file=sys.stderr)
        return 1
    print(job.composite.output)
    return 0
```
(`import sys` at the top.) `cmd_card` and `cmd_cost` catch nothing: `main` prints the class name for anything unexpected.

- [ ] **Step 5: Run the tests**

Run: `uv run --project packages/league-automation pytest tests/video tests/cli/test_video.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add packages/league-automation/src/ultimate_guillotine/video/pipeline.py packages/league-automation/src/ultimate_guillotine/cli/video.py packages/league-automation/tests/video/test_pipeline.py packages/league-automation/tests/cli/test_video.py
git commit -m "feat(video): ug video render, from a logged trade to the finished clip"
```

---

### Task 8: First renders (operator steps, review by Ben)

**Files:**
- Create: `docs/runbooks/trade-video.md`
- Output: `data/media/renders/*.mp4` (git-ignored; copy the keepers somewhere Ben can play them)

- [ ] **Step 1: Render over the ESPN footage with manual copy**

```bash
uv run --project packages/league-automation python -m ultimate_guillotine.cli.main video render \
  --headline "SOURCES: JOSH JACOBS TRADED TO CHARLIE" \
  --subline "Derek gets 450 FAAB · Charlie gets Josh Jacobs · Week 3" \
  --caption "pov: the league chat when Derek and Charlie pull off a trade nobody saw coming"
```
Expected: a path under `data/media/renders/`. Play it: 24 s, DIEAGAIN from the top, Schefter under our banner, caption centred. Check the banner fully covers ESPN's own lower third; if the ticker peeks out below it, raise `BANNER_BOTTOM_SHARE` in `card.py`.

- [ ] **Step 2: Render the square cut, like the reference**

Same command with `--aspect 1:1`. The result should sit next to the Denzo video without looking like a different format.

- [ ] **Step 3: Render from a logged trade**

`uv run --project packages/league-automation python -m ultimate_guillotine.cli.main trades list` then `… video render --trade <code>` (TEST- codes work; the words come from the stored terms).

- [ ] **Step 4: One generated clip (52 credits)**

`… video cost --trade <code>` to confirm the price, then `… video render --trade <code> --base generated`. Judge the footage against the reference; tune `prompt.py` before generating again. Do not loop on this: each try is 52 credits.

- [ ] **Step 5: Write `docs/runbooks/trade-video.md`**

The commands above, the flags, where output lands, the credit cost, and the fact that posting is manual: Ben downloads the render and posts it from the TikTok app (the reference's caption stays native there if he wants the text searchable).

- [ ] **Step 6: Commit**

```bash
git add docs/runbooks/trade-video.md
git commit -m "docs(video): runbook for rendering trade announcement videos"
```

---

### Task 9 (follow-up, not in this plan's scope): on-demand from Discord

When Ben says "video T-2026-003" in `#guillotine-ops`, Hermes should run `ug video render --trade T-2026-003` and hand the file back. That needs a Hermes channel prompt in `hermes/guillotine/` and a way to post a file to Discord from the mini; neither is settled, so it gets its own brainstorm and plan once the renders look right.

---

## Self-review

- **Spec coverage:** (1) music saved — Task 1; (2) footage without the caption — Task 1 (ESPN upload) plus `--base source`; (3) reference-driven Higgsfield generation on demand — Tasks 6 and 7 (`--base generated`, omni_reference with the Denzo clip); (4) trade text overlay — Tasks 3 and 4; (5) the dramatic track under it — Task 5 (`music_offset` 0.0, `keep_voice` off by default like the reference). Posting to TikTok stays manual, as in the Monke pipeline.
- **Placeholders:** none; every step has its command or code.
- **Type consistency:** `Layout.for_footage(w, h, aspect)`, `render_card(copy, layout, out)`, `Composite(...)`, `ff.command(c, w, h, ffmpeg)`, `ff.probe(path, ffprobe=, run=)`, `hf.GenerateRequest(prompt, reference_video, duration, resolution, aspect_ratio)`, `hf.generate_clip(req, dest, binary=, runner=, fetch=)`, `prepare(req, assets, *, ffmpeg, ffprobe, probe=, generate=, now=)`, `render(req, assets, *, run=, **prepare_kwargs)` are used with the same names in every task.

## Execution notes (2026-09-10, the night it was written)

Tasks 2 through 7 were implemented in one pass and committed as `feat(video): ug video render`
(2158454), with the plan's tests plus a few extra ones (`ug video assets` green path, a refused
`--dry-run --base generated`, a missing-footage path, vertical footage on 9:16). Two things
changed on seeing the first real render:

- **9:16 layout.** Fitting 16:9 footage by width left it a thin strip in the middle of the
  canvas. `Layout.for_footage` and `video_filter` now show wide footage as its centre square,
  1080x1080 in the middle of 1080x1920, which is how TikTok shows the 1:1 reference. Vertical
  (generated) footage still fills the canvas.
- **Lower third.** ESPN's own banner peeked out around a bar with side margins and behind a
  narrow tag, and a four-line caption ran into the tag. The bar is now edge to edge, the tag has
  a minimum width, and the caption block is pushed up to stay clear of the tag.

`prepare()` resolves its `probe`/`generate`/`now` collaborators at call time (``None`` defaults)
so monkeypatching the modules in tests takes effect. Task 8's first renders and the single
generated clip are in `data/media/renders/`; the runbook is `docs/runbooks/trade-video.md`.

### Added after the first review (2026-09-10, morning)

Ben asked for an AI-voiced insider and a script generator. Built as `video/script.py`
(`Script`/`Beat` pydantic models, `generate_script` through the repo's `StructuredOutputClient`
on Hermes with a one-shot retry when the read runs over the 2.6 words/second budget,
`template_script` as the no-model fallback, `script_from_text` for a typed read),
`prompt.voiced_prompt` (beats as timed quoted dialogue, audio on), `RenderRequest.voiced`
(Seedance `generate_audio`, the generated voice kept under the music via `keep_voice`, which now
depends on `Probe.has_audio`), and `ug video script` / `render --voiced` / `cost --voiced`.
Commit 9bf15e3, 66 video tests.

### Task 9 done differently (2026-09-10, later that morning)

Ben's trigger is a reply in the chat, not a Discord command: "@bot create trade video" on a
trade alert. Built as `video/trigger.py` (`is_video_request`, `VideoRequests.resolve` reads the
trade off the reply thread via `TradeRepository.find_by_source_guid`, a code in the text, or
the bot's own confirmation via `OutboundRepository.content_for_guid`; `video_trigger` registered
in `listener/run.py` on the alert chats), `video/jobs.py` (`private.video_jobs`, migration
20260910210000, one open job per trade, `claim` with skip-locked, stale-running cleanup),
`video/worker.py` (`Worker.run_once`: read → voiced generation → composite →
`deliver_attachment`, run records, failure to `#guillotine-ops`), `ug video jobs
list|run|watch|add`, and the `guillotine-video-jobs` cron job every 2 min. The voice stays
Seedance's own (Ben: the Schefter sound is the point); a TTS path was tried and dropped.
