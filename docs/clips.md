# Clips

The five Clips of the Video phase, one per situation. The video files are not committed (`clips/` and `clips-raw/` are git-ignored). This list is the record of where each came from.

## Clip list

Fill in the source URL and license when downloading. Fill in the duration from the `prepare-clips.ps1` table.

| Clip | Situation | Source URL | License | Duration (s) |
| --- | --- | --- | --- | --- |
| `front.mp4` | Front view, mostly still | TBD | TBD | TBD |
| `side.mp4` | Side view | TBD | TBD | TBD |
| `fast.mp4` | Fast movement (jumping jacks, squats) | TBD | TBD | TBD |
| `far.mp4` | Far away or partly hidden | TBD | TBD | TBD |
| `empty.mp4` | Empty room, no person | TBD | TBD | TBD |

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
