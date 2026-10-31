# Demo videos

Two short MP4s for the mentor deck that show the pose skeleton over real frames, in the order the mentor asked for: first the Video phase, then the webcam. Both go to `report/demo/` with a PNG still from the middle of each. `report/` is gitignored, so the videos, and the tester's face, never reach GitHub. Anyone with the Run files and Demo recording can rebuild them.

## Part 1: Video phase

The Board's landmarks from one Video phase Run, drawn on the same frames of its Clip. The Board processed every frame there, so each frame shows its own result. Nothing new runs on the Board.

```powershell
$env:PYTHONPATH="src"; uv run python -m bench.demo_video video --run runs\board\video-20261031\video__lite__front__r1__board.jsonl --clip clips\front.mp4 --out report\demo\video-phase.mp4
```

It plays at the Clip's 30 fps, faster than the Board ran, so the caption gives the Board's FPS for that Run, computed as Analysis does (after the 30 warm-up frames).

## Part 2: Webcam

1. Make a Demo recording, with no Campaign running (the script checks before it copies anything to the Board):

   ```powershell
   .\scripts\record-demo.ps1
   ```

   It copies the code to the Board and starts `bench.demo_record`. An `ffplay` window on the Dev machine shows every third camera frame: 10 s of preview to get into frame, then the 30 s Demo recording. Move the way you did in the measured Sessions. The Demo recording lands in `runs-demo\<UTC timestamp>\`, which is gitignored. `-NoPreview` skips the window.

2. Draw it, skipping the first 5 s (model loading, as in Session warm-up):

   ```powershell
   $env:PYTHONPATH="src"; uv run python -m bench.demo_video webcam --demo-recording runs-demo\<id> --out report\demo\webcam.mp4 --start 5
   ```

What it shows:

- **Live view:** every camera frame, with the skeleton from the latest result that had arrived when the frame was read. It updates a few times a second and trails the movement by the delay, as someone watching live would see it.
- **Face blur:** placed where the face was when the frame was captured, between the poses found before and after it. That is hindsight only the drawing step has, which is fine because the blur is a privacy filter, not part of what the Board produced. A frame with no pose within 0.5 s is blurred in full, so a missed detection never shows a face. Blurring happens after pose estimation, so it does not change the landmarks.
- **Caption:** "Lite (as-is) on the Board | live from the Brio 105 | skeleton shown as it arrived", with `|` because OpenCV's built-in fonts cannot draw `·`. It has no numbers: a Demo recording is not measured, and the preview adds some work on the Board. The FPS and delay belong on the Webcam results slide, from Analysis.

`--start` and `--length` (default 15 s) pick the window, in seconds from the first frame. Landmarks with visibility below 0.5 are not drawn.

## Demo recording files

A Demo recording is never a Session and never goes to Analysis (see `GLOSSARY.md`). It runs the Webcam phase's camera settings and one-frame-in-flight gate (ADR 0006), but opens the camera raw. Each JPEG the camera sends is saved as is, and only the frames sent to MediaPipe are decoded.

- `frames.mjpeg`: every JPEG the camera sent during the recording, back to back, not re-encoded.
- `demo.jsonl`: JSON Lines.
  - A `header` line: `phase` `demo`, `variant`, `seconds`, `model`, `clip_info` and `camera` as in a Webcam phase header.
  - One `live_frame` line per frame, with the same fields as in a Run file (`docs/run-file-format.md`) plus `offset` and `length`, the frame's bytes in `frames.mjpeg`.
  - A `status` line last.

  A half-written last line is ignored. If anyone hands a `demo.jsonl` to Analysis, phase `demo` makes it a failed row rather than a pooled Session.
