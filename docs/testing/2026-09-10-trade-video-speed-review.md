# Trade video speed review

TEST-2026-002, video job 3, completed on September 10, 2026 at 12:33:05 PM Central. Total request-to-delivery time was 9 minutes 28 seconds. The generated clip is 10 seconds long, requested at 720p with audio and lip syncing.

## Measured timing

| Stage | Time | Evidence |
| --- | ---: | --- |
| Queue wait | 2m 33s | Database creation and worker start timestamps |
| Worker preparation, script, and submission | 20s | Worker start to Higgsfield creation timestamp; the individual operations are not separately timed |
| Provider wait and download | About 6m 31s | Higgsfield creation to generated file's final modification time; provider completion time is not exposed in the returned document |
| Composite and delivery | About 4s | Download completion to database job completion; encode alone was about 1.6s by file timestamps |
| Total | 9m 28s | Database request and completion timestamps |

The worker is scheduled every two minutes. The observed queue delay was longer than that interval, so it includes scheduling overhead or another source of delay that these timestamps do not isolate. Higgsfield polling occurs every 15 seconds; reducing that interval can only recover part of that polling delay, not the minutes spent generating.

## Trade wording

The submitted dialogue says:

> Breaking news. The Commish is paying Max two hundred dollars. And Max, yes, Max, takes the Commish's place in the gulag. Week One.

This confirms the script sent to the video generator has the intended directions and on-air name. It does not independently confirm the final synthesized speech matches the script. The user accepts "$200" as the wording for the next tests.

## Local comparison

A 12-second composite over archived source footage with the normal overlay and music took **1.223 seconds** on this machine.

A second comparison used the existing source footage, the completed trade's card, and its generated voice as a separate audio input, plus the music. It took **1.045 seconds**, producing a 10-second, 1080 × 1920 MP4 with audio:

`data/media/renders/TEST-2026-002-default-footage-reused-narration.mp4`

That preview deliberately reuses the finished narration. It demonstrates appearance without lip syncing and measures assembly; it does not include new text-to-speech generation. No new paid video generation or chat delivery was requested.

## Recommended next experiment

Use a reusable clip and separately generated narration as the fast video mode. Keep the current captions, lower third, music, and on-air name. A consistent sports-insider voice can carry the breaking-news delivery. Switching to separate narration also makes the spoken words easier to preview and correct without regenerating footage.

ElevenLabs provides voice design from descriptions and separate text-to-speech models. Compare an expressive model against its fast model using the exact same approved script and voice. Its advertised inference latency is not a promise about the time to create, download, assemble, and deliver a whole clip.

Sources checked September 10, 2026:

- [Text to speech capabilities and voice design](https://elevenlabs.io/docs/overview/capabilities/text-to-speech)
- [What the latency numbers measure](https://elevenlabs.io/docs/eleven-api/concepts/latency)

Implementation would add an optional narration file to the compositor, a text-to-speech adapter, and a fast mode in the worker. The existing compositor can already reuse footage, but its current narration input is the footage's own audio track. The preview supplied a separate input directly to FFmpeg; production code has not been changed.

For prompt pickup, use a continuously running worker or enqueue notification, preserving the existing atomic job claim. Removing the queue wait matters even after video generation is removed. Record timestamps for script generation, provider submission and completion, download, encode, and delivery. Save the final script with each job for correctness review.

Keep 720p or the current output resolution for the first comparison. Lower resolution does not remove the provider generation step, and local compositing is already about a second. A target under one minute from request to delivery is worth testing for the fast mode, but remains unmeasured until a real text-to-speech adapter and prompt job pickup are in place.

Compare the same trade across the original generated clip and the local no-lip-sync preview first. Then benchmark fresh narration with the selected voice. Judge trade direction, pronunciation of Commish and gulag, voice quality, distracting mouth mismatch, total delivery time, and actual per-clip cost.
