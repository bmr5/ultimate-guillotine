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
    assert (layout.width, layout.height, layout.video_top, layout.video_bottom) == (
        1080,
        1080,
        0,
        1080,
    )


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
    # The letterbox above the footage stays clear.
    assert img.getpixel((540, 100))[3] == 0
    # The white bar of the lower third reaches the bottom corner of the footage,
    # past where any text runs.
    assert img.getpixel((layout.width - 40, layout.video_bottom - 40))[:3] == (255, 255, 255)
    # Something is painted where the caption block sits.
    band = img.crop((0, layout.video_top + 200, 1080, layout.video_top + 420))
    assert band.getbbox() is not None
