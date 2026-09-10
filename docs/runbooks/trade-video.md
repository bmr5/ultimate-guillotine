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

## Voiced clips: the insider says the trade

```bash
uv run --project packages/league-automation python -m ultimate_guillotine.cli.main video script --trade T-2026-003 --generate-seconds 12
uv run --project packages/league-automation python -m ultimate_guillotine.cli.main video render --trade T-2026-003 --voiced --generate-seconds 12
```

`script` writes the on-air read through Hermes (the league's model backend) in the cadence of
an ESPN breaking-news hit, as timed beats with delivery directions, and prints it without
spending anything. `render --voiced` writes the read the same way, puts it into the Seedance
prompt as quoted dialogue with `generate_audio` on, and mixes the music at -12 dB under the
voice. The read is printed before the generation starts.

- The read decides the length. Hermes is asked for the shortest read the trade allows (a
  two-side swap in about 20 words, a bigger deal condensed), and the clip is sized to it at
  2.6 words a second plus a second of air, between 4 and 15 s, which is what Seedance renders.
  A really long trade is condensed into 39 words, not stretched past 15 s. `--generate-seconds`
  overrides the length; a read that runs long for its clip desyncs the lips.
- Waiver money is spoken as dollars ("twenty dollars"), never FAAB: the voice model handles it
  better. The lower third on screen still says FAAB.
- `--script "…"` uses your own words verbatim; `--no-ai` uses the template read
  ("Breaking news. Sources tell ESPN: … The whole league is shaking.") with no model call.
- An 8 s 720p voiced clip is 52 credits and generated in about four minutes on 2026-09-10; a 12 s
  one is 78 credits and took over twenty minutes. Keep reads to 8 s (20 words) unless a trade
  really needs more. Check with `video cost --voiced --duration 8`.
- The voice is whatever Seedance gives the character. Nothing here clones Adam Schefter's
  actual voice from the ESPN audio; that would be a different, deliberate step.

## If a generation hangs or the wait dies

`render --voiced` / `--base generated` prints `higgsfield job <id> queued` as soon as the job
exists, then polls `higgsfield generate get <id>` every 15 s for up to 30 minutes, riding out
transient errors. A 12 s clip with audio has taken over 20 minutes. If the command still dies
(laptop asleep, timeout), the credits are not lost: the job keeps running on Higgsfield.

```bash
higgsfield generate get <id> --json          # status and, when done, result_url
curl -L -o data/media/generated/<name>.mp4 "<result_url>"
uv run --project packages/league-automation python -m ultimate_guillotine.cli.main video render \
  --trade T-2026-003 --base data/media/generated/<name>.mp4 --keep-voice --music-gain -12
```

`higgsfield generate list --json` shows recent jobs when the id was not caught.

## Why the reference has no text on it

The first request from the chat came back with Denzo's "pov:" caption and ESPN's banner
showing through under our overlay: Seedance had been given the Denzo clip as its reference
and reproduced it, text and all. The generation reference is now
`data/media/reference/source/espn-schefter-clean-1024.mp4`, 12 s of the ESPN footage
cropped to the square above the lower third, so there is nothing written in frame to copy.
The Denzo clip stays as the *style* reference for humans; Seedance never sees it. If text
ever shows through again, the prompt's "nothing written anywhere in frame" line and this
crop are the two knobs.

## What the one generated clip looked like (2026-09-10)

Seedance 2.5 in `omni_reference` mode with the Denzo clip as the reference produced an 8 s
vertical clip that is, to the eye, Adam Schefter in his home office delivering news: same face,
blazer, bookshelves and helmet, no text, animated speech. It composites cleanly
(`data/media/renders/manual-20260910-050648.mp4`). That is a real person's likeness generated
from his footage, so whether generated clips are ever posted is Ben's call; the ESPN footage
path uses the real segment the reference used.

## The whole flow in the self-test chat (production mode)

The league chat is live, and the self-test chat is the rehearsal room: an alert posted there
is logged by a second registrar under a `TEST-` code and answered there, and a video asked
for there is delivered there. So the full loop, without the league seeing anything:

1. Post a trade alert in the self-test chat, siren and all:
   `Trade alert 🚨 Derek sends Rhamondre to Charlie for Michael Wilson and 20 FAAB`
2. Wait for `🚨 Trade TEST-2026-001 logged · Derek ↔ Charlie`.
3. Reply to either message with `@daddy create trade video`.
4. Read `🎬 On it — the video for TEST-2026-001 usually takes 5 to 10 minutes.`, then the clip.

`TEST-` trades show up wherever trades are listed until they are rescinded
(`ug trades rescind TEST-2026-001`).

## Asking for one from the chat

Reply to a trade alert (or to the bot's "🚨 Trade T-2026-003 logged" line, or say the code)
with **`@daddy create trade video`**. The listener answers within a second:

> 🎬 On it — the video for T-2026-003 usually takes 5 to 10 minutes.

and queues a row in `private.video_jobs`. The `guillotine-video-jobs` cron job (every 2 min)
runs `ug video jobs run`, which claims the oldest queued job, writes the read, generates the
voiced clip (as long as the read needs), composites it, and delivers the mp4 through the delivery
service to the chat that asked: a request in the self-test chat is answered there in every mode,
a request in the league chat is answered in the league chat once the mode is production. One
open job per trade: asking twice gets "already in the works". A rescinded trade gets no video.
Failures are recorded on the job and posted to `#guillotine-ops`; nothing retries by itself
because every attempt costs credits (52 for 8 s).

```bash
uv run --project packages/league-automation python -m ultimate_guillotine.cli.main video jobs list
uv run --project packages/league-automation python -m ultimate_guillotine.cli.main video jobs add T-2026-003
uv run --project packages/league-automation python -m ultimate_guillotine.cli.main video jobs run --verbose
uv run --project packages/league-automation python -m ultimate_guillotine.cli.main video jobs watch
```

The worker has to run where the media tools are. On the mini that means, once: `brew install
ffmpeg`, the Higgsfield CLI logged in (`higgsfield auth login`), `uv sync` for Pillow, a
`git pull` for `data/media/reference`, and `hermes/guillotine/install.sh` to register the cron
job. `ug video assets` says whether it is all there.

## Not done yet

- The mini's one-time setup above, and a first request in the self-test chat to prove the
  whole path end to end (queued → rendered → attachment delivered).
- The caption font is Arial Bold, the closest system font to the reference's; the headline is
  Arial Black.
