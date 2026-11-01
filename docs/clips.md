# Clips

The five Clips of the Video phase, one per situation. The video files are not committed (`clips/` and `clips-raw/` are git-ignored). This list is the record of where each came from.

## Clip list

Duration is that of the prepared Clip, as reported by `prepare-clips.ps1`. `side` is a gym treadmill, `fast` is trampoline jumping, `far` is a small figure dancing in a large room, and `empty` is a hallway with no one in it.

| Clip | Situation | Source URL | License | Duration (s) |
| --- | --- | --- | --- | --- |
| `front.mp4` | Front view, mostly still | https://www.pexels.com/video/a-woman-standing-outdoors-while-drinking-a-cup-of-coffee-3044530/ | Pexels License | 26.6 |
| `side.mp4` | Side view | https://www.pexels.com/video/young-man-running-on-treadmill-9777600/ | Pexels License | 23.0 |
| `fast.mp4` | Fast movement (jumping jacks, squats) | https://www.pexels.com/video/a-woman-jumping-on-a-trampoline-6571901/ | Pexels License | 23.7 |
| `far.mp4` | Far away or partly hidden | https://www.pexels.com/video/a-person-dancing-in-the-room-6834861/ | Pexels License | 27.0 |
| `empty.mp4` | Empty room, no person | https://www.pexels.com/video/elegant-empty-hallway-with-classic-architecture-37410272/ | Pexels License | 22.5 |

## Choosing a clip

Use Pexels or Pixabay. Both licenses allow showing the clip on slides without attribution. Copy the license name shown on the clip's page into the list.

For every situation, filter to **landscape** orientation and pick a clip that is **at least 20 s** long, has one person (except `empty`), a fixed camera, and no watermark or text overlay. Download the highest resolution offered; it is scaled down to 1280×720 anyway.

| Situation | Search terms to try |
| --- | --- |
| `front` | `woman standing front view`, `man talking to camera full body`, `yoga standing pose`, `stretching in living room` |
| `side` | `side view walking treadmill`, `profile view exercise`, `man jogging side view`, `side view stretching` |
| `fast` | `jumping jacks`, `squats workout`, `burpees`, `aerobics exercise`, `crossfit workout` |
| `far` | `person far away`, `silhouette in the distance`, `exercise behind furniture`, `dance in large room wide shot` |
| `empty` | `empty room`, `empty living room`, `empty gym`, `empty office interior` |

Full body in frame matters most for `front`, `side` and `fast`. For `far`, the person should be small in the frame or partly hidden behind something.

## Preparing the Clips

1. Download each pick into `clips-raw/` and name it after its situation, keeping the original extension: `front.mp4`, `side.mov`, `fast.mp4`, `far.mp4`, `empty.mp4`.
2. Convert and verify:

   ```powershell
   .\scripts\prepare-clips.ps1
   ```

   It writes `clips/<situation>.mp4` as 1280×720, 30 fps, H.264, no audio, trimmed to at most 30 s, and checks all five with `ffprobe`. A source shorter than 20 s is rejected (pick a longer one). A source that is not 16:9 is scaled to fill and centre-cropped. The script exits with an error if any Clip fails the check.
3. Copy the Clips to the Board:

   ```powershell
   .\scripts\push-to-board.ps1 -Clips
   ```

4. Run Lite once on each Clip, then pull and analyse:

   ```powershell
   foreach ($c in "front", "side", "fast", "far", "empty") { .\scripts\run-on-board.ps1 -Variant lite -Clip "$c.mp4" }
   .\scripts\pull-runs.ps1
   $env:PYTHONPATH="src"; uv run python -m bench.analysis runs\board
   ```

## Workshop videos

`workshop-clips/` holds the first 10 s of two Clips, committed so that a workshop attendee has a video without downloading anything (`WORKSHOP.md`). They are cut from the prepared Clips above, so the sources and licenses are the same. The Pexels License allows this; it only forbids selling unaltered copies or putting them on another stock site.

| Workshop video | Cut from | Source URL | License |
| --- | --- | --- | --- |
| `front.mp4` | `clips/front.mp4`, 0–10 s | https://www.pexels.com/video/a-woman-standing-outdoors-while-drinking-a-cup-of-coffee-3044530/ | Pexels License |
| `fast.mp4` | `clips/fast.mp4`, 0–10 s | https://www.pexels.com/video/a-woman-jumping-on-a-trampoline-6571901/ | Pexels License |

Remake them from the prepared Clips with:

```powershell
foreach ($c in "front", "fast") { ffmpeg -y -v error -i "clips\$c.mp4" -t 10 -an -c:v libx264 -pix_fmt yuv420p -preset slow -crf 23 -movflags +faststart "workshop-clips\$c.mp4" }
```

They are never used in the study's Runs, and Runs on them are never given to Analysis.
