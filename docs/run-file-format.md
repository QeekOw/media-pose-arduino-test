# Run file format

A Run file is JSON Lines: one JSON object per line, each with a `type`. It is the only seam between data collection and Analysis. A crash mid-Run leaves every line written so far readable. Analysis ignores line types it does not know, so later tickets can add types without breaking old Run files.

Version 1. Name files `<phase>__<variant>__<clip>__r<repeat>__<machine>.jsonl`. A Webcam phase session uses the clip slot `live` and its session number as the repeat, as in `webcam__lite__live__r2__board.jsonl`.

## Line order

1. one `header` line (first),
2. any number of `frame` lines (Video phase) or `live_frame` lines (Webcam phase), in frame order, with `sample` lines interleaved between them,
3. one `status` line (last, written on every exit the process can catch).

A Run file with no `status` line counts as failed. On Linux an out-of-memory kill is a SIGKILL the process cannot catch, so a Run started on its own with `bench.run_one` leaves no `status` line and Analysis shows it as `failed: no status line`.

A Campaign (`python -m bench.campaign`) starts every Run as a child process and settles the file afterwards. When the file has no `status` line, the Campaign appends one: `oom` if the child was killed with SIGKILL (exit code -9), otherwise `crashed`. `detail` holds the exit code or signal and the last 500 characters of the child's stderr. A child that outlives `--run-timeout` is killed and recorded as `crashed` with detail `timed out after N s`. A half-written last line is cut before the status line is appended. If the child died before creating its file, the Campaign creates it containing only the `status` line. Analysis then shows the Run as `failed: no header line` with its variant, clip and repeat taken from the file name.

## `header`

```json
{
  "type": "header",
  "format_version": 1,
  "phase": "video",
  "variant": "lite",
  "clip": "smoke.mp4",
  "repeat": 1,
  "started_at": "2026-10-23T12:00:00+00:00",
  "sample_interval_s": 1.0,
  "machine": {
    "name": "board",
    "os": "Debian GNU/Linux 13 (trixie)",
    "kernel": "7.0.0-...",
    "arch": "aarch64",
    "python": "3.12.15",
    "ram_total_mb": 3667,
    "ram_available_mb": 3061,
    "disk_free_mb": 3900
  },
  "software": {"mediapipe": "0.10.18", "numpy": "1.26.4", "opencv": "4.11.0.86", "python": "3.12.15"},
  "model": {"file": "pose_landmarker_lite.task", "size_bytes": 5777746, "sha256": "..."},
  "clip_info": {"width": 1280, "height": 720, "fps": 30.0, "frame_count": 600}
}
```

`variant` is `lite`, `full` or `heavy`. `phase` is `video` or `webcam`; any other value makes line 1 corrupt. `machine.name` is `board` or `dev`. `sample_interval_s` is the `--sample-interval` the Run used; Run files written before it existed lack it.

A Webcam phase header has `clip` `live`, the session number as `repeat`, and two more keys:

```json
{
  "session_s": 60.0,
  "clip_info": {"width": 1280, "height": 720, "fps": 30.0},
  "camera": {
    "device": "/dev/v4l/by-id/usb-046d_Brio_105_2524ZBL03X08-video-index0",
    "fourcc": "MJPG",
    "exposure_dynamic_framerate": 0,
    "capture_clock": "driver"
  }
}
```

`clip_info` is what the camera delivered after the format was checked. `capture_clock` is `driver` when `capture_ms` is the V4L2 buffer timestamp, or `read` when a probe frame at the start showed that timestamp is not on the monotonic clock and the time `read()` returned was used instead.

## `frame`

```json
{"type": "frame", "index": 0, "video_ms": 2.1, "model_ms": 85.3, "landmarks": [[0.51, 0.22, -0.3, 0.99], "...33 entries..."]}
```

- `video_ms` is the time to read and decode the frame and convert it into the form the model takes.
- `model_ms` is the time spent inside the model call.
- `landmarks` is 33 entries of `[x, y, z, visibility]` as MediaPipe returns them (x and y normalised to 0–1 of the frame width and height), or `null` when no person was found.

Frame time is `video_ms + model_ms`.

## `live_frame`

```json
{"type": "live_frame", "index": 41, "capture_ms": 5123456.8, "read_ms": 5123470.1, "result_ms": 5123689.2, "dropped": false, "landmarks": [[0.51, 0.22, -0.3, 0.99], "...33 entries..."]}
{"type": "live_frame", "index": 42, "capture_ms": 5123490.1, "read_ms": 5123503.0, "result_ms": null, "dropped": true, "landmarks": null}
```

One line per camera frame the program read, in the Webcam phase. The program reads every frame the camera delivers but lets only one at a time into MediaPipe, in LIVE_STREAM mode: it sends a frame only when the previous one's result has come back. Times are milliseconds on the Board's monotonic clock; only differences mean anything.

- `capture_ms` is when the frame was captured (see `capture_clock` in the header).
- `read_ms` is when `read()` returned it. Analysis flags `capture clock off` when the two are more than 1 s apart, or in the wrong order, after warm-up.
- `result_ms` is when MediaPipe's result callback ran for the frame, or `null` when it has none.
- `dropped` is `true` exactly when `result_ms` is `null`: the frame was read while another was in MediaPipe, so it was never sent, or it was sent and its result had not come back 1 s after the session ended.
- `landmarks` is as in `frame`, and always `null` on a dropped frame.

A line is written once the frame's fate is known. A frame dropped while another is in MediaPipe is written right after that one, to keep frame order, so a crash loses the frame in MediaPipe and those dropped behind it. A line whose `dropped` disagrees with `result_ms`, whose result comes before its capture, or that has landmarks on a dropped frame is a corrupt line.

Delay is `result_ms - capture_ms`: from capture to result, over the frames MediaPipe got. With one frame in MediaPipe at a time, no frame waits there behind another. The program gates frames itself because `mediapipe` 0.10.18 queues LIVE_STREAM frames instead of skipping them: fed every frame, a 10 s Lite session on the Board reached 8.8 s of delay within 2.8 s of capture and slowed the read loop to about 6 frames a second (ADR 0006).

## `sample`

```json
{"type": "sample", "t_ms": 1000, "cpu_pct": 87.0, "ram_used_mb": 1100, "rss_mb": 310, "rss_peak_mb": 450, "temp_c": 62.5, "cpu_mhz": 2016}
```

A background thread reads the system at a fixed interval (`--sample-interval`, default 1 s), plus once at the start and once at the end of the Run. The main thread writes the queued samples right after sampling starts, after each frame and before the `status` line, so it stays the only writer. Samples taken while the model loads have no frame boundary to be written at, so a kill during model load loses them.

- `t_ms` is milliseconds since sampling started.
- `cpu_pct` is system-wide CPU busy percent since the previous sample, from the `cpu` line of `/proc/stat`. It is `null` in the first sample.
- `ram_used_mb` is `MemTotal - MemAvailable` from `/proc/meminfo`.
- `rss_mb` is the Run process's resident memory (`VmRSS` in `/proc/self/status`).
- `rss_peak_mb` is the Run process's resident high-water mark so far (`VmHWM` in `/proc/self/status`). The kernel tracks it exactly, so it catches spikes between samples. Analysis reports peak RSS from it, or from `rss_mb` in Run files written before it existed.
- `temp_c` is the highest `/sys/class/thermal/thermal_zone*/temp` over zones whose `type` starts with `cpu` (on the Board `cpuss0-thermal` and `cpuss1-thermal`), or over all zones when none does.
- `cpu_mhz` is the highest `scaling_cur_freq` across cores. Idle cores clock down on their own, but a thermal throttle caps every core, so the highest one shows the throttle.

Every reading is a number or `null`, and `t_ms` is an integer. Any value the machine cannot provide is `null`. The Dev machine (Windows) has none of these files, so every reading in its samples is `null`.

## `status`

```json
{"type": "status", "status": "completed", "detail": ""}
```

`status` is `completed`, `crashed` or `oom`. `detail` holds the error message for the last two. A Run that reads fewer frames than the header's `clip_info.frame_count` is written as `crashed` with detail `stopped early: read N of M frames`. A Webcam phase session whose camera stops delivering is written as `crashed` with detail `camera stopped after N frames`. A session that cannot find or configure the camera exits before creating its file, as a Run with an unreadable Clip does.

## Unreadable Run files

Analysis never aborts on a bad Run file. An empty file, a missing header, an unparseable line (anywhere but a truncated last line), or a `sample` line with a value of the wrong type, or a `frame` line whose `landmarks` are not `null` or 33 entries of four numbers, makes that Run a failed row, shown as `failed: no header line` or `failed: corrupt line N`. Frames read before the bad line are kept, and a status line after a bad line is ignored. When the header is missing, phase, variant, clip, repeat and machine come from the file name, which is why the name pattern above matters.

Analysis sorts files by phase from the first line alone: the header's phase, else the file name's, else video. Video phase Runs and Webcam phase sessions are summarised apart, so a session never reaches the Pass criteria.

## Webcam phase measures

Analysis leaves out the frames captured in the first 5 s of each session, timed from its first frame. That covers stale frames left in the camera's buffers while the model loaded and the slow first model call. Over the rest, with seconds counted from the end of warm-up to the last frame captured:

- **Camera FPS** is frames read per second. It is flagged `camera below 25 fps` when the camera or the read loop fell behind the 30 fps the camera was set to.
- **Processed FPS** is frames with a result per second.
- **Dropped %** is the share of frames read that never got a result.
- **Delay** is the average and the 95th percentile of capture to result, over processed frames.
- **Detect %** is the share of processed frames with a pose.
- System measures are the same as in the Video phase.

The report pools a variant's completed sessions by adding up frames, seconds and delays, the way the Video phase verdicts pool frames.

## Quality metrics

Analysis scores the landmarks of every Run on the frames left after the 30 warm-up frames. Distances are taken in pixels (the normalised x and y times the `clip_info` width and height) and divided by torso length, the distance from the midpoint of the shoulders (landmarks 11 and 12) to the midpoint of the hips (23 and 24).

- **Reference landmarks** are the lowest-numbered completed `heavy` Run on `dev` for each Clip. Generate them with `scripts/run-laptop-baseline.ps1`, which writes the whole Laptop baseline to `runs/dev/`. Give Analysis that directory next to the Board's, as in `uv run python -m bench.analysis runs/dev runs/board`.
- **PCK@0.2** is the percentage of landmarks within 0.2 torso lengths of the reference, using the reference's torso, over frames where both the Run and the reference found a pose. It is `-` for a Clip with no reference. Heavy on `dev` scores 100% against itself.
- **Detection rate** is the percentage of frames with a pose, on every Clip except `empty`.
- **False detections** is the same percentage on `empty`, where any pose is wrong. The two are never mixed.
- **Jitter** is the mean landmark movement between consecutive frames, in torso lengths, on `front` only. A frame without a pose breaks the chain, so movement is never measured across it.

## Report

`python -m bench.report <Board Run files> runs/dev --out-dir report` turns the Run files into the answer. It needs `runs/dev` for the Laptop baseline and the Reference landmarks.

- **Verdicts** apply the Pass criteria (ADR 0004) to all of a Model variant's Board Runs on the five Campaign Clips together. Frames are pooled: average FPS is all kept frames over their total time, the slowest-5% frame time is the 95th percentile of all kept frame times, and detection is the share of frames with a pose across every Clip except `empty`. Any Run whose status is not `completed` fails the variant, and so does having fewer than 3 Runs on any of the five Clips. Every failed rule is named with its value. Runs on `smoke` or other Clips, and Runs on `dev`, never count. A variant with no Board Runs is listed as having none, and "no Model variant passed" is only reported once all three have a verdict.
- **Spread** lists, for each Model variant, Clip and machine, the FPS mean and range across completed repeats, the range as a percent of the mean, and the range of slowest-5% frame time.
- **Summary table** shows each Model variant's pooled FPS, slowest-5% frame time, detection and PCK@0.2 (over all compared landmarks, so each Run counts by the landmarks it was scored on) on the Board and the Laptop baseline side by side, with the verdict. It is printed and written as `summary-table.png`.
- **Charts** are `fps.png` (Board vs laptop, with the 10 FPS line), `frame-times.png` (Board, whiskers at the 5th and 95th percentile, with the 150 ms line), `accuracy-vs-speed.png` (PCK@0.2 against FPS) and `temperature.png` (the hottest Board Run of each variant). A chart with no data to show is not written.
- **Webcam phase**: give the report the Webcam Campaign's directory too. The summary table then adds each variant's pooled Webcam FPS (processed), dropped % and delay (average / p95) after the verdict, and the variant reads `Lite (as-is)` when it failed the Pass criteria, or `Lite (no verdict)` when no Video phase Runs were given. The report prints a per-variant Webcam table and writes `webcam-fps.png` (camera FPS split into processed and dropped, with the 10 FPS line) and `webcam-delay.png` (capture to result, whiskers at the 5th and 95th percentile). Only Board sessions count.
