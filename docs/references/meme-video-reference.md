# Meme video reference: the TikTok to reproduce

Saved 2026-09-10 at Ben's request ("please save this, it is very important").
This is the reference video for the automated league meme video pipeline: Ben liked it and
wants to generate videos for the Sovereign Guillotine League based on its format.

| Field | Value |
| --- | --- |
| URL | https://www.tiktok.com/@denzo.61/video/7678787561464073502 |
| Share link as received | https://www.tiktok.com/@denzo.61/video/7678787561464073502?_r=1&_t=ZT-99FOBdPu19i |
| Creator | Denzo (@denzo.61) |
| Caption | got the whole league shaking… \|\| #fantasyfootball #nfl #fyp #nfltiktok #football |
| Video id | 7678787561464073502 |

## What the video is made of (worked out 2026-09-10)

- **Footage:** ESPN's Adam Schefter breaking the Micah Parsons trade (home office, bookshelves,
  "BREAKING NEWS · SOURCES: PARSONS TRADED FROM COWBOYS" lower third). Denzo cropped it square
  and muted it. The clean 127 s ESPN upload is saved as
  `data/media/reference/source/espn-tMgvUrwtaiw-schefter-parsons-breaking-news.mp4`; Denzo's
  24 s start about 2.5 s in.
- **Caption:** centred white bold text with a black outline, added in CapCut:
  "pov: you and that one friend who made the first big trade in your fantasy league".
- **Sound:** "DIEAGAIN (SLOWED + Reverb)" from the top of the track, nothing else. Saved as
  `data/media/reference/youtube-8_wnIISchzQ-dieagain-slowed-reverb.m4a`.
- Ben also asked to keep "original sound - The Neighborhood Podcast" (an NFL commentator
  compilation, unrelated to this video); it and its source video are in the same folder.

Everything is archived under `data/media/reference/` (see its README for provenance and
re-download commands). The build plan is
`docs/superpowers/plans/2026-09-10-trade-announcement-video-pipeline.md`.

## Prior art on Ben's Mac (outside this repo)

- `~/Documents/Monke`: daily meme-explainer video pipeline for the peptide app. Design doc
  `docs/2026-06-21-monke-pipeline-design.md` and `docs/content-pipeline-playbook.md` describe the
  drop-a-link Discord intake, Hermes as conductor, Claude Code doing production, and two human gates.
  That playbook was written as the template for the next content brand.
- `~/Documents/ugc-studio`: script-first UGC pipeline with a judge panel; generate only survivors.
- `~/Documents/ContentFarm`: TikTok and YouTube harvest plus clip production.
- Linear ENG-574 "Remix Studio": viral video, breakdown, close-paraphrase script, teleprompter.

## What Ben wants built

1. Keep the TikTok's music (done) and the podcast sound he liked (done).
2. Find the footage without the caption (done: the ESPN upload above).
3. A pipeline that takes one of our logged trades and renders the same kind of video, on demand,
   either over the ESPN footage or over footage Higgsfield's Seedance 2.5 generates from the
   reference (`ug video render --trade T-2026-003 --base source|generated`).
4. The trade written on the video (a centred caption plus an ESPN-style lower third).
5. The DIEAGAIN track under it so it sounds dramatic.
