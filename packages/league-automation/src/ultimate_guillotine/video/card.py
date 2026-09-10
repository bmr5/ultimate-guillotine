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
#: Where the caption block is centred, as a share of the footage height.
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
    return round(value / 2) * 2


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


def _fit(
    draw: ImageDraw.ImageDraw, text: str, path: Path, size: int, max_width: float
) -> ImageFont.FreeTypeFont:
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
    block_top = layout.video_top + round(layout.video_height * CAPTION_CENTRE)
    y = block_top - (line_h * len(lines)) // 2
    for line in lines:
        x = (layout.width - draw.textlength(line, font=caption_font)) / 2
        draw.text(
            (x, y),
            line,
            font=caption_font,
            fill=WHITE,
            stroke_width=round(CAPTION_STROKE * scale),
            stroke_fill=BLACK,
        )
        y += line_h

    # The lower third: a red tag over a white bar, across the bottom of the footage.
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
    tag_top = bar_top - tag_h + round(6 * scale)
    draw.rectangle((tag_left, tag_top, tag_left + tag_w, bar_top + round(6 * scale)), fill=RED)
    draw.text((tag_left + pad, tag_top + round(6 * scale)), copy.tag, font=tag_font, fill=WHITE)

    text_width = layout.width - 2 * margin - 2 * pad
    headline_font = _fit(
        draw, copy.headline, fonts.headline, round(HEADLINE_SIZE * scale), text_width
    )
    headline_top = bar_top + round(16 * scale)
    draw.text((margin + pad, headline_top), copy.headline, font=headline_font, fill=INK)
    subline_font = _fit(draw, copy.subline, fonts.subline, round(SUBLINE_SIZE * scale), text_width)
    sub_y = headline_top + round(HEADLINE_SIZE * scale * 1.25)
    draw.text((margin + pad, sub_y), copy.subline, font=subline_font, fill=GREY)

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out
