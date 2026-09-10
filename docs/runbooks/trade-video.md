# Runbook: trade announcement videos

`ug video` turns a logged league trade into a TikTok-style breaking-news clip in the format
of the Denzo TikTok Ben saved (see `docs/references/meme-video-reference.md`): ESPN's Adam
Schefter footage, a centred "pov:" caption, an ESPN-style lower third with the trade, and
"DIEAGAIN (slowed + reverb)" under it. Posting stays manual: download the render and post it
from the TikTok app.

Run everything from the repo root. The inputs live in `data/media/reference/` (tracked in
git); output lands in `data/media/renders/` (git-ignored), the text layer PNGs in
`data/media/work/`, generated footage in `data/media/generated/`.

## Check the setup

```bash
uv run --project packages/league-automation python -m ultimate_guillotine.cli.main video assets
```

Every line should say `ok`. A `MISSING` file is re-downloaded with the recipe in
`data/media/reference/README.md`; a missing tool is a `brew install`.

## Render a logged trade

```bash
uv run --project packages/league-automation python -m ultimate_guillotine.cli.main trades list
uv run --project packages/league-automation python -m ultimate_guillotine.cli.main video render --trade T-2026-003
```

The words come from the stored terms: the headline names the first player who moves and who
gets him, the subline says what each side gets in the chat's wording, the caption defaults to
`pov: the league chat when <A> and <B> pull off a trade nobody saw coming`. Override any of
them with `--caption`, `--headline`, `--subline`. `TEST-` codes work the same way.

## Render without a logged trade

```bash
uv run --project packages/league-automation python -m ultimate_guillotine.cli.main video render \
  --headline "SOURCES: JOSH JACOBS TRADED TO CHARLIE" \
  --subline "Derek gets 450 FAAB · Charlie gets Josh Jacobs · Week 3" \
  --caption "pov: the league chat when Derek and Charlie pull off a trade nobody saw coming"
```

## Flags

| Flag | What it does |
| --- | --- |
| `--aspect 9:16` (default) or `1:1` | 9:16 shows the footage as a centred square with black above and below, which is how TikTok shows the 1:1 reference; 1:1 is the reference's own frame. |
| `--base source` (default) | The archived ESPN clip, cut 2.5 s in like the reference. |
| `--base generated` | Footage from Seedance 2.5 on Higgsfield, generated from the reference video. Costs credits: 52 for an 8 s 720p clip. Check with `ug video cost` first. |
| `--base <path>` | Any clip of your own. |
| `--duration 24` | Seconds; the default matches the reference. A generated clip is only as long as it was generated (`--generate-seconds`, default 8). |
| `--keep-voice` | Keep the footage's own audio under the music (the reference mutes it). |
| `--music-gain -3` | Music level in dB. |
| `--dry-run` | Print the ffmpeg command and encode nothing (not with `--base generated`). |

`ug video card --out card.png …` writes only the text layer, for checking the words before a
render. Renders take about two seconds over the ESPN footage.

## Generated footage

```bash
uv run --project packages/league-automation python -m ultimate_guillotine.cli.main video cost --trade T-2026-003
uv run --project packages/league-automation python -m ultimate_guillotine.cli.main video render --trade T-2026-003 --base generated
```

The prompt (`video/prompt.py`) asks for an NFL insider in a home office delivering breaking
news with no on-screen text; the text layer is ours. The account is the ugc-studio Higgsfield
login (`higgsfield account status`). Do not loop on generation to tune the prompt: each try is
52 credits. The generated clip is kept in `data/media/generated/`, so a re-render with different
words is `--base data/media/generated/<file>.mp4` and costs nothing.

## Not done yet

- On-demand from Discord ("video T-2026-003" in `#guillotine-ops`) needs a Hermes channel prompt
  and a way to post the file back; it gets its own plan once the renders look right.
- The caption font is Arial Bold, the closest system font to the reference's; the headline is
  Arial Black.
