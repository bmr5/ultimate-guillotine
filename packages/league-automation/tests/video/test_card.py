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


def test_wide_footage_shows_as_a_centred_square_on_9_16() -> None:
    layout = Layout.for_footage(1280, 720, "9:16")
    assert (layout.width, layout.height) == CANVAS["9:16"]
    assert layout.video_bottom - layout.video_top == 1080
    assert layout.video_top == (1920 - 1080) // 2


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
    # The white bar of the lower third runs edge to edge, past where any text runs.
    assert img.getpixel((layout.width - 10, layout.video_bottom - 60))[:3] == (255, 255, 255)
    assert img.getpixel((10, layout.video_bottom - 60))[:3] == (255, 255, 255)
    # Something is painted where the caption block sits.
    band = img.crop((0, layout.video_top + 380, 1080, layout.video_top + 700))
    assert band.getbbox() is not None


def test_a_long_caption_stays_clear_of_the_tag(tmp_path: Path) -> None:
    layout = Layout.for_footage(1280, 720, "9:16")
    out = render_card(COPY, layout, tmp_path / "card.png")
    img = Image.open(out)
    bar_top = layout.video_top + round(layout.video_height * 0.75)
    # The rows just above the tag carry no caption pixels.
    gap = img.crop((0, bar_top - 56, 1080, bar_top - 44))
    assert gap.getbbox() is None
