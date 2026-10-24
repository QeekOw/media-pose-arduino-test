# Run file format

A Run file is JSON Lines: one JSON object per line, each with a `type`. It is the only seam between data collection and Analysis. A crash mid-Run leaves every line written so far readable. Analysis ignores line types it does not know, so later tickets can add types without breaking old Run files.

Version 1. Name files `<phase>__<variant>__<clip>__r<repeat>__<machine>.jsonl`.

## Line order

1. one `header` line (first),
2. any number of `frame` lines, in frame order, with `sample` lines interleaved between them,
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

`variant` is `lite`, `full` or `heavy`. `phase` is `video` or `webcam`. `machine.name` is `board` or `dev`. `sample_interval_s` is the `--sample-interval` the Run used; Run files written before it existed lack it.

## `frame`

```json
{"type": "frame", "index": 0, "video_ms": 2.1, "model_ms": 85.3, "landmarks": [[0.51, 0.22, -0.3, 0.99], "...33 entries..."]}
```

- `video_ms` is the time to read and decode the frame and convert it into the form the model takes.
- `model_ms` is the time spent inside the model call.
- `landmarks` is 33 entries of `[x, y, z, visibility]` as MediaPipe returns them (x and y normalised to 0–1 of the frame width and height), or `null` when no person was found.

Frame time is `video_ms + model_ms`.

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

`status` is `completed`, `crashed` or `oom`. `detail` holds the error message for the last two. A Run that reads fewer frames than the header's `clip_info.frame_count` is written as `crashed` with detail `stopped early: read N of M frames`.

## Unreadable Run files

Analysis never aborts on a bad Run file. An empty file, a missing header, an unparseable line (anywhere but a truncated last line), or a `sample` line with a value of the wrong type makes that Run a failed row, shown as `failed: no header line` or `failed: corrupt line N`. Frames read before the bad line are kept, and a status line after a bad line is ignored. When the header is missing, variant, clip, repeat and machine come from the file name, which is why the name pattern above matters.
