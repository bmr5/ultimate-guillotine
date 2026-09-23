#!/usr/bin/env python3
"""Render a roster meme from a reviewed clip catalog. Requires ffmpeg and Pillow."""

import argparse
import json
import subprocess
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]


def get_json(url):
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.load(response)


def roster_ids(league, username):
    base = "https://api.sleeper.app/v1"
    users = get_json(f"{base}/league/{league}/users")
    matches = [u for u in users if u.get("display_name", "").lower() == username.lower()]
    if len(matches) != 1:
        raise ValueError(f"Expected one league member matching {username!r}")
    rosters = get_json(f"{base}/league/{league}/rosters")
    roster = next(r for r in rosters if r["owner_id"] == matches[0]["user_id"])
    return list(dict.fromkeys(p for p in roster["starters"] + roster["players"] if p != "0"))


def run(argv):
    result = subprocess.run(argv, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr[-1500:])


def font_path(override):
    candidates = [override] if override else [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise ValueError("Pass --font with a bold TrueType font file")


def overlay(path, caption, entry, font):
    image = Image.new("RGBA", (1080, 1080))
    draw = ImageDraw.Draw(image)
    face = ImageFont.truetype(font, 55)
    # Keep the joke above the broadcast's player portrait and lower third.
    caption_y = entry.get("caption_y", 220 if entry["kind"] != "intro" else 400)
    draw.multiline_text((540, caption_y), caption, font=face, anchor="mm", align="center",
                        fill="white", stroke_width=4, stroke_fill="black", spacing=3)
    if entry["kind"] != "intro":
        draw.rounded_rectangle((65, 855, 1015, 1005), radius=14, fill=(0, 0, 0, 195))
        draw.text((540, 902), entry["name"], anchor="mm", font=ImageFont.truetype(font, 53),
                  fill="white")
        draw.text((540, 961), entry["fallback_caption"], anchor="mm",
                  font=ImageFont.truetype(font, 33), fill="white")
    if entry.get("stamp"):
        stamp = Image.new("RGBA", (950, 270))
        ink = ImageDraw.Draw(stamp)
        ink.rounded_rectangle((8, 8, 942, 262), radius=12,
                              fill=(20, 0, 0, 115), outline=(255, 35, 35), width=18)
        ink.rectangle((32, 32, 918, 238), outline=(255, 35, 35), width=5)
        ink.text((475, 135), entry["stamp"], anchor="mm",
                 font=ImageFont.truetype(font, 174), fill=(255, 35, 35),
                 stroke_width=3, stroke_fill=(65, 0, 0))
        stamp = stamp.rotate(12, resample=Image.Resampling.BICUBIC, expand=True)
        image.alpha_composite(stamp, ((1080 - stamp.width) // 2, 510 - stamp.height // 2))
    image.save(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=ROOT / "data/media/reference/player-intros.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/media/renders/commish-player-intros.mp4")
    parser.add_argument("--league", default="1389372259260452864")
    parser.add_argument("--username", default="benray887")
    parser.add_argument("--player-ids", nargs="+", help="Override live whole-roster lookup, in playback order")
    parser.add_argument("--caption", default="how ass the Commish's\nteam is in his own\nfantasy league")
    parser.add_argument("--font")
    parser.add_argument("--fetch", action="store_true", help="Download missing catalog source videos with yt-dlp")
    parser.add_argument("--plan", action="store_true", help="Print coverage without downloading or rendering")
    args = parser.parse_args()
    catalog = json.loads(args.catalog.read_text())
    ids = args.player_ids or roster_ids(args.league, args.username)
    missing = [p for p in ids if p not in catalog["players"]]
    if missing:
        raise ValueError(f"No reviewed clip for Sleeper IDs {missing}. Add catalog entries first.")
    entries = [catalog["players"][p] for p in ids]
    plan = [{"player_id":p, "name":e["name"], "kind":e["kind"]} for p,e in zip(ids, entries)]
    print(json.dumps(plan, indent=2), flush=True)
    if args.plan:
        return
    font = font_path(args.font)
    work = ROOT / "data/media/work/player-intros/render"
    work.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for source_key in dict.fromkeys(e["source"] for e in entries):
        source = catalog["sources"][source_key]
        local = ROOT / source["file"]
        if not local.is_file() and args.fetch:
            local.parent.mkdir(parents=True, exist_ok=True)
            cmd = ["uvx", "--from", "yt-dlp", "yt-dlp", "--no-progress", "-f",
                   "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720]",
                   "--merge-output-format", "mp4", "-o", str(local.with_suffix(".%(ext)s"))]
            if source.get("section"):
                cmd += ["--download-sections", source["section"], "--force-keyframes-at-cuts"]
            run(cmd + [source["url"]])
        if not local.is_file():
            raise ValueError(f"Missing source {local}. Use --fetch to download it.")
    # Validate the entire edit before producing any segments.
    for e in entries:
        source = ROOT / catalog["sources"][e["source"]]["file"]
        result = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries",
                  "format=duration:stream=codec_type", "-of", "json", str(source)], text=True)
        info = json.loads(result)
        if not 0 <= e["start"] < e["end"] <= float(info["format"]["duration"]):
            raise ValueError(f"Invalid cut for {e['name']}")
        if not any(s["codec_type"] == "audio" for s in info["streams"]):
            raise ValueError(f"Source has no audio for {e['name']}")
        if not 0 <= e["crop_x"] <= 1:
            raise ValueError(f"Invalid crop for {e['name']}")
    segments = []
    for i, e in enumerate(entries):
        card = work / f"{i:02d}.png"
        clip = work / f"{i:02d}.mp4"
        overlay(card, args.caption, e, font)
        source = ROOT / catalog["sources"][e["source"]]["file"]
        # crop_x is a fraction of the available horizontal crop travel.
        graph = (f"[0:v]crop=min(iw\\,ih):min(iw\\,ih):(iw-ow)*{e['crop_x']}:0,"
                 "scale=1080:1080,setsar=1,fps=30,setpts=PTS-STARTPTS[base];"
                 "[base][1:v]overlay=0:0:shortest=1[v];"
                 "[0:a]aresample=48000,asetpts=PTS-STARTPTS[a]")
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(e["start"]),
             "-i", str(source), "-loop", "1", "-i", str(card), "-t", str(e["end"] - e["start"]),
             "-filter_complex", graph, "-map", "[v]", "-map", "[a]", "-c:v", "libx264",
             "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac",
             "-ar", "48000", "-ac", "2", "-b:a", "192k", str(clip)])
        segments.append(clip)
    concat = work / "concat.txt"
    concat.write_text("".join(f"file '{p.name}'\n" for p in segments))
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
         "-i", str(concat), "-c:v", "copy", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
         "-c:a", "aac", "-ar", "48000", "-b:a", "192k", "-movflags", "+faststart", str(args.output)])
    args.output.with_suffix(".json").write_text(json.dumps({
        "caption":args.caption, "players":plan, "clips":entries,
        "sources":{e["source"]:catalog["sources"][e["source"]] for e in entries},
    }, indent=2) + "\n")
    print(f"Rendered {args.output}", flush=True)


if __name__ == "__main__":
    main()
