# Player intro roster videos

The pilot recreates the format of [CEO of Currency's TikTok](https://www.tiktok.com/@ceoofcurr3ncy/video/7683297150909811981): a persistent roast caption over quick cuts of broadcast player introductions. The export is a square 1080px H.264/AAC MP4, matching the reference's square composition.

## Render the current roster

From the repository root:

```bash
.venv/bin/python scripts/render_player_intros.py --plan
.venv/bin/python scripts/render_player_intros.py
```

The default reads `benray887`'s live roster in the configured 2026 Ultimate Guillotine league. It includes starters followed by bench players, removes duplicates, and skips empty slots. It does not update the roster or send the video anywhere.

The result is `data/media/renders/commish-player-intros.mp4`. The JSON beside it records the selected players, cuts, source URLs, and caption. Source footage and intermediate renders stay under ignored `data/media/work/player-intros/`.

Use `--username` and `--league` for another team, and `--caption` to change the joke. Use `--player-ids` followed by Sleeper IDs to choose an exact lineup and order. `--output` selects a different destination. Pillow and ffmpeg are required; `--font` can select a bold TrueType font when neither Arial nor DejaVu is installed.

To download missing catalog sources, add `--fetch`, which uses `uvx` and yt-dlp. Downloads depend on the source still being available. No paid generation service is involved.

## Pilot coverage

The latest requested edit removes Fairbairn and adds a large red `INJURED` joke stamp throughout Bowers's section. Reproduce that eight-player cut with:

```bash
.venv/bin/python scripts/render_player_intros.py --player-ids 11563 13286 8408 7569 9487 9482 10229 11604 --output data/media/renders/commish-player-intros-v3.mp4
```

The catalog retains Fairbairn's footage for other edits. The optional player `stamp` field adds the tilted overlay.

Verified on September 10, 2026 against actual footage and local transcription:

| Player | Pilot clip |
| --- | --- |
| Bo Nix | NBC self-introduction, Oregon |
| Jordan Mason | NBC self-introduction, Gallatin High School |
| Nico Collins | NBC self-introduction, Michigan |
| Parker Washington | NBC self-introduction, Penn State |
| Michael Mayer | NBC self-introduction, Notre Dame |
| Rashee Rice | NBC self-introduction, SMU |
| Jadarian Price | NBC self-introduction, Notre Dame, from the September 9, 2026 Patriots/Seahawks kickoff game |
| Ka'imi Fairbairn | Game footage with name and school caption |
| Brock Bowers | Official NFL studio self-introduction: name, tight end, University of Georgia |

Fairbairn is the only footage substitute. Bowers's clip is his real self-introduction from [NFL's First Draft feature](https://www.nfl.com/videos/first-draft-brock-bowers), at approximately 23 seconds. It is a pre-draft studio shot rather than an NBC Raiders lineup overlay. Price's real intro appears at approximately 8 seconds in [Kodster Productions' 2026 kickoff-game introductions](https://www.youtube.com/watch?v=Dx_4-P8L7qE). His original draft-reaction substitute is no longer used.

## Extending the clip library

`data/media/reference/player-intros.json` maps Sleeper player IDs to reviewed cuts and source URLs. `start` and `end` are seconds within the local file. `crop_x` runs from 0, the leftmost square crop, to 1, the rightmost crop. Choose it to preserve the talking portrait. Optional `caption_y` moves the roast caption to keep a studio subject's face visible. A source can specify a `section` to download only part of a longer upload; player timestamps then refer to that downloaded section.

Search team introduction compilations as well as individual player names. For example, Parker Washington appears in the 2023 Ravens/Jaguars introductions even though his name is absent from the upload title. Automated transcription helps locate candidates, but it mishears names, so compare the broadcast nameplate before accepting a cut. Preserve what the player actually says; Mason uses his high school.

New players without reviewed catalog entries stop the render with their missing IDs. They are never silently omitted or assigned another player's clip. Roster lookup, clip selection, captions, crops, and assembly are automated. Discovering and verifying new clips still requires review. The pilot does not add a scheduled job or connect to the league message delivery pipeline.
