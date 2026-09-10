# Reference media for the trade announcement video pipeline

Saved 2026-09-10. These files are tracked in git on purpose: they are the inputs the
pipeline (`ug video …`, package `ultimate_guillotine.video`) reproduces, and Ben lost the
link once already. Rendered output goes to `../renders`, `../generated` and `../work`, all
git-ignored.

| File | What it is | Source |
| --- | --- | --- |
| `tiktok-7678787561464073502-denzo61-got-the-whole-league-shaking.mp4` | The TikTok to reproduce. 24 s, 1080x1080, HEVC 60 fps. Caption "pov: you and that one friend who made the first big trade in your fantasy league" over ESPN footage, music over it, footage audio muted. | https://www.tiktok.com/@denzo.61/video/7678787561464073502 (posted 2026-08-27) |
| `tiktok-7678787561464073502-denzo61-mixed-audio.m4a` | That TikTok's audio track as posted: the music only. It cross-correlates at 0.91 with the track below at a 0.07 s lag, so the song starts from the top. | split from the mp4 with ffmpeg |
| `youtube-8_wnIISchzQ-dieagain-slowed-reverb.m4a` | The music: "DIEAGAIN (SLOWED + Reverb)", 229 s, AAC 128 kbps. TikTok credits the sound to Prodby668. | https://www.youtube.com/watch?v=8_wnIISchzQ (audio only, yt-dlp) |
| `source/espn-tMgvUrwtaiw-schefter-parsons-breaking-news.mp4` | The footage Denzo used, without his caption: ESPN's Adam Schefter breaking the Micah Parsons trade, 127 s, 1280x720. Denzo's 24 s start about 2.5 s in (frame correlation, 2026-09-10). | https://www.youtube.com/watch?v=tMgvUrwtaiw ("Adam Schefter breaks down the Cowboys trading Micah Parsons to the Packers", NFL on ESPN) |
| `tiktok-sound-7665372239335918366-original-sound-the-neighborhood-podcast.mp3` | A second sound Ben asked to keep: "original sound - The Neighborhood Podcast", 37 s. Not used by the Denzo video. | https://www.tiktok.com/music/original-sound-The-Neighborhood-Podcast-7665372239335918366 |
| `tiktok-7665372245728021791-neighborhood-podcast-original.mp4` | The video that sound comes from: "NFL Commentator Sus Moments", 37 s, 720x1280. | https://www.tiktok.com/@neighborhood_podcast/video/7665372245728021791 |
| `*.info.json` | yt-dlp metadata for each download (titles, stats, formats). | yt-dlp |

Re-download recipe (yt-dlp 2026.08.19 or newer; the Homebrew build gets a 403 from YouTube):

```bash
uvx --from yt-dlp yt-dlp -f 'bestaudio[ext=m4a]/bestaudio' -x --audio-format m4a \
  -o 'youtube-8_wnIISchzQ-dieagain-slowed-reverb.%(ext)s' 'https://www.youtube.com/watch?v=8_wnIISchzQ'
uvx --from yt-dlp yt-dlp -f 'bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720]' --merge-output-format mp4 \
  -o 'source/espn-tMgvUrwtaiw-schefter-parsons-breaking-news.%(ext)s' 'https://www.youtube.com/watch?v=tMgvUrwtaiw'
yt-dlp -f 'bv*+ba/b' --merge-output-format mp4 \
  -o 'tiktok-7678787561464073502-denzo61-got-the-whole-league-shaking.%(ext)s' 'https://www.tiktok.com/@denzo.61/video/7678787561464073502'
```
