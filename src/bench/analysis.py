import argparse
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from bench.quality import Quality, clip_stem, measure
from bench.runfile import PHASES, VIDEO, WEBCAM, Frame, LiveFrame, RunFile, Sample, read_phase, read_run

WARMUP_FRAMES = 30
WEBCAM_WARMUP_MS = 5000.0
CAMERA_MIN_FPS = 25.0
NO_STATUS = "failed: no status line"


@dataclass(frozen=True)
class RunSummary:
    variant: str
    clip: str
    repeat: int
    machine: str
    status: str
    frames: int
    kept_frames: int
    fps: float | None
    avg_ms: float | None
    p95_ms: float | None
    peak_rss_mb: int | None
    peak_ram_used_mb: int | None
    avg_cpu_pct: float | None
    max_temp_c: float | None
    min_cpu_mhz: int | None
    pck: float | None
    pck_landmarks: int
    detection_rate: float | None
    false_detection_rate: float | None
    jitter: float | None
    flags: tuple[str, ...]
    frame_ms: tuple[float, ...]
    temps: tuple[tuple[int, float], ...]

    @property
    def has_numbers(self) -> bool:
        return self.fps is not None


@dataclass(frozen=True)
class LiveStats:
    """What the camera delivered and what came back over a measured stretch of a Webcam phase session.

    Adding two pools them: counts and seconds add up and delays are concatenated, so one session and several
    sessions pooled go through the same formulas.
    """

    camera_frames: int
    seconds: float
    delays_ms: tuple[float, ...]
    detected: int

    def __add__(self, other: "LiveStats") -> "LiveStats":
        return LiveStats(
            self.camera_frames + other.camera_frames,
            self.seconds + other.seconds,
            self.delays_ms + other.delays_ms,
            self.detected + other.detected,
        )

    @property
    def processed(self) -> int:
        return len(self.delays_ms)

    @property
    def camera_fps(self) -> float | None:
        return self.camera_frames / self.seconds if self.seconds else None

    @property
    def processed_fps(self) -> float | None:
        return self.processed / self.seconds if self.seconds else None

    @property
    def dropped_pct(self) -> float | None:
        return 100.0 * (self.camera_frames - self.processed) / self.camera_frames if self.camera_frames else None

    @property
    def delay_avg_ms(self) -> float | None:
        return float(np.mean(self.delays_ms)) if self.delays_ms else None

    @property
    def delay_p95_ms(self) -> float | None:
        return float(np.percentile(self.delays_ms, 95)) if self.delays_ms else None

    @property
    def detection_rate(self) -> float | None:
        return 100.0 * self.detected / self.processed if self.processed else None


NO_LIVE = LiveStats(0, 0.0, (), 0)


@dataclass(frozen=True)
class WebcamSummary:
    variant: str
    session: int
    machine: str
    status: str
    frames: int
    stats: LiveStats | None
    peak_rss_mb: int | None
    peak_ram_used_mb: int | None
    avg_cpu_pct: float | None
    max_temp_c: float | None
    min_cpu_mhz: int | None
    flags: tuple[str, ...]
    temps: tuple[tuple[int, float], ...]


def identity_from_name(path: Path) -> tuple[str, str, str, int, str]:
    """(phase, variant, clip, repeat, machine) from a `<phase>__<variant>__<clip>__r<repeat>__<machine>` name."""
    parts = path.stem.split("__")
    if len(parts) == 5 and re.fullmatch(r"r\d+", parts[3]):
        return parts[0], parts[1], parts[2], int(parts[3][1:]), parts[4]
    return "?", "?", path.stem, 0, "?"


def phase_of(path: Path) -> str:
    """The header's phase, or the file name's for a Run that died before writing a header. Video otherwise."""
    named = identity_from_name(path)[0]
    return read_phase(path) or (named if named in PHASES else VIDEO)


def readings(run: RunFile, *fields: str) -> list:
    return [v for s in run.samples for name in fields if (v := getattr(s, name)) is not None]


def _any_reading(run: RunFile, fields: tuple[str, ...], bad: Callable[[float], bool]) -> bool:
    return any(bad(v) for v in readings(run, *fields))


SYSTEM_IMPLAUSIBLE: list[tuple[str, Callable[[RunFile], bool]]] = [
    ("no samples", lambda run: not run.samples),
    ("temp 0 or out of range", lambda run: _any_reading(run, ("temp_c",), lambda t: t <= 0 or t > 125)),
    ("clock 0", lambda run: _any_reading(run, ("cpu_mhz",), lambda mhz: mhz <= 0)),
    ("ram 0", lambda run: _any_reading(run, ("ram_used_mb", "rss_mb", "rss_peak_mb"), lambda mb: mb <= 0)),
    ("cpu % out of range", lambda run: _any_reading(run, ("cpu_pct",), lambda pct: pct < 0 or pct > 100)),
]
IMPLAUSIBLE = [("no frames", lambda run: not run.frames), *SYSTEM_IMPLAUSIBLE]


def _over[T](fn: Callable[[list[T]], T], values: list[T]) -> T | None:
    return fn(values) if values else None


def avg_cpu_pct(samples: list[Sample]) -> float | None:
    # Each cpu_pct covers the time since the previous sample, and the final one from stop() can cover only a few ms.
    weighted = total_ms = 0
    for prev, s in zip(samples, samples[1:]):
        ms = s.t_ms - prev.t_ms
        if s.cpu_pct is not None and ms > 0:
            weighted += s.cpu_pct * ms
            total_ms += ms
    return weighted / total_ms if total_ms else None


def status_text(run: RunFile) -> str:
    if run.problem is not None:
        return f"failed: {run.problem}"
    return NO_STATUS if run.status is None else run.status


def is_reference(run: RunFile) -> bool:
    return (
        run.header is not None
        and run.header.variant == "heavy"
        and run.header.machine_name == "dev"
        and run.status == "completed"
        and run.problem is None
    )


def reference_frames(runs: list[RunFile]) -> dict[str, list[Frame]]:
    """Reference landmarks per Clip: the lowest-numbered completed Heavy Run on the Dev machine."""
    chosen: dict[str, RunFile] = {}
    for run in runs:
        if is_reference(run):
            clip = clip_stem(run.header.clip)
            if clip not in chosen or run.header.repeat < chosen[clip].header.repeat:
                chosen[clip] = run
    return {clip: run.frames for clip, run in chosen.items()}


def system_measures(run: RunFile) -> dict:
    return {
        # rss_peak_mb is the kernel's exact high-water mark; files written before it existed only have polled rss_mb.
        "peak_rss_mb": _over(max, readings(run, "rss_peak_mb") or readings(run, "rss_mb")),
        "peak_ram_used_mb": _over(max, readings(run, "ram_used_mb")),
        "avg_cpu_pct": avg_cpu_pct(run.samples),
        "max_temp_c": _over(max, readings(run, "temp_c")),
        "min_cpu_mhz": _over(min, readings(run, "cpu_mhz")),
    }


def summarize(run: RunFile, references: dict[str, list[Frame]] | None = None) -> RunSummary:
    kept = run.frames[WARMUP_FRAMES:]
    fps = avg_ms = p95_ms = None
    if kept:
        times = np.array([f.frame_ms for f in kept], dtype=float)
        fps = len(times) / (times.sum() / 1000.0)
        avg_ms = float(times.mean())
        p95_ms = float(np.percentile(times, 95))
    if run.header is None:
        _, variant, clip, repeat, machine = identity_from_name(run.path)
    else:
        variant, clip, repeat, machine = run.header.variant, run.header.clip, run.header.repeat, run.header.machine_name
    quality = Quality(None, None, None, None)
    if run.header is not None:
        size = run.header.clip_info
        reference = (references or {}).get(clip_stem(clip))
        quality = measure(clip, kept, reference, size.get("width"), size.get("height"))
    return RunSummary(
        variant=variant,
        clip=clip,
        repeat=repeat,
        machine=machine,
        status=status_text(run),
        frames=len(run.frames),
        kept_frames=len(kept),
        fps=fps,
        avg_ms=avg_ms,
        p95_ms=p95_ms,
        **system_measures(run),
        pck=quality.pck,
        pck_landmarks=quality.pck_landmarks,
        detection_rate=quality.detection_rate,
        false_detection_rate=quality.false_detection_rate,
        jitter=quality.jitter,
        flags=tuple(name for name, implausible in IMPLAUSIBLE if implausible(run)),
        frame_ms=tuple(f.frame_ms for f in kept),
        temps=tuple((s.t_ms, s.temp_c) for s in run.samples if s.temp_c is not None),
    )


def _measured(frames: list[LiveFrame]) -> list[LiveFrame]:
    """The frames captured at least WEBCAM_WARMUP_MS after the first one."""
    start = frames[0].capture_ms + WEBCAM_WARMUP_MS if frames else 0.0
    return [f for f in frames if f.capture_ms >= start]


def live_stats(frames: list[LiveFrame]) -> LiveStats | None:
    """Stats over the measured frames, timed from the end of warm-up. None if no time is left after warm-up."""
    kept = _measured(frames)
    seconds = (kept[-1].capture_ms - frames[0].capture_ms - WEBCAM_WARMUP_MS) / 1000.0 if kept else 0.0
    if seconds <= 0:
        return None
    processed = [f for f in kept if not f.dropped]
    return LiveStats(
        camera_frames=len(kept),
        seconds=seconds,
        delays_ms=tuple(f.delay_ms for f in processed),
        detected=sum(f.landmarks is not None for f in processed),
    )


def summarize_webcam(run: RunFile) -> WebcamSummary:
    if run.header is None:
        _, variant, _, session, machine = identity_from_name(run.path)
    else:
        variant, session, machine = run.header.variant, run.header.repeat, run.header.machine_name
    stats = live_stats(run.live_frames)
    flags = ["no frames"] if not run.live_frames else []
    flags += [name for name, implausible in SYSTEM_IMPLAUSIBLE if implausible(run)]
    # Warm-up frames are left out: frames that sat in the camera's buffers while the model loaded are read late.
    if any(not 0 <= f.read_ms - f.capture_ms <= 1000 for f in _measured(run.live_frames)):
        flags.append("capture clock off")
    if stats is not None and stats.camera_fps < CAMERA_MIN_FPS:
        flags.append(f"camera below {CAMERA_MIN_FPS:g} fps")
    return WebcamSummary(
        variant=variant,
        session=session,
        machine=machine,
        status=status_text(run),
        frames=len(run.live_frames),
        stats=stats,
        **system_measures(run),
        flags=tuple(flags),
        temps=tuple((s.t_ms, s.temp_c) for s in run.samples if s.temp_c is not None),
    )


def find_run_files(paths: list[str | Path]) -> list[Path]:
    files: list[Path] = []
    for p in map(Path, paths):
        if p.is_dir():
            files.extend(sorted(p.glob("*.jsonl")))
        elif p.is_file():
            files.append(p)
        else:
            raise FileNotFoundError(p)
    return files


def run_identity(run: RunFile) -> tuple:
    if run.header is None:
        return ("file", run.path)
    h = run.header
    return (h.variant, h.clip, h.repeat, h.machine_name, h.started_at)


def load_runs(paths: list[str | Path], phase: str) -> list[RunFile]:
    """Every Run file of one phase under paths. Of the other phase's files only the first line is read."""
    # The same Run can arrive twice: overlapping arguments, links, or a copied Campaign directory. Count it once.
    unique: dict[tuple, RunFile] = {}
    for path in find_run_files(paths):
        path = path.resolve()
        if phase_of(path) == phase:
            run = read_run(path)
            unique.setdefault(run_identity(run), run)
    return list(unique.values())


def analyze(paths: list[str | Path]) -> list[RunSummary]:
    """Video phase Runs only, so a Webcam phase session can never reach the Pass criteria."""
    runs = load_runs(paths, VIDEO)
    references = reference_frames(runs)
    summaries = [summarize(run, references) for run in runs]
    return sorted(summaries, key=lambda s: (s.variant, s.clip, s.repeat, s.machine))


def analyze_webcam(paths: list[str | Path]) -> list[WebcamSummary]:
    summaries = [summarize_webcam(run) for run in load_runs(paths, WEBCAM)]
    return sorted(summaries, key=lambda s: (s.variant, s.session, s.machine))


def _cell(value, fmt: str = "{}") -> str:
    return "-" if value is None else fmt.format(value)


def format_table(summaries: list[RunSummary]) -> str:
    headers = ["variant", "clip", "repeat", "machine", "status", "frames", "kept", "FPS", "avg ms", "p95 ms"]
    headers += ["peak RSS MB", "peak RAM MB", "avg CPU %", "max temp C", "min MHz"]
    headers += ["PCK@0.2 %", "detect %", "false det %", "jitter", "flags"]
    rows = []
    for s in summaries:
        if s.has_numbers:
            numbers = [f"{s.fps:.2f}", f"{s.avg_ms:.1f}", f"{s.p95_ms:.1f}"]
        else:
            numbers = [f"too few frames (need {WARMUP_FRAMES + 1})", "-", "-"]
        system = [
            _cell(s.peak_rss_mb),
            _cell(s.peak_ram_used_mb),
            _cell(s.avg_cpu_pct, "{:.1f}"),
            _cell(s.max_temp_c, "{:.1f}"),
            _cell(s.min_cpu_mhz),
            _cell(s.pck, "{:.1f}"),
            _cell(s.detection_rate, "{:.1f}"),
            _cell(s.false_detection_rate, "{:.1f}"),
            _cell(s.jitter, "{:.4f}"),
            ", ".join(s.flags) or "-",
        ]
        rows.append(
            [s.variant, s.clip, str(s.repeat), s.machine, s.status, str(s.frames), str(s.kept_frames), *numbers, *system]
        )
    return _aligned(headers, rows)


def _aligned(headers: list[str], rows: list[list[str]]) -> str:
    widths = [max(len(r[i]) for r in [headers, *rows]) for i in range(len(headers))]
    return "\n".join("  ".join(cell.ljust(w) for cell, w in zip(r, widths)).rstrip() for r in [headers, *rows])


def format_webcam_table(summaries: list[WebcamSummary]) -> str:
    headers = ["variant", "session", "machine", "status", "frames", "kept", "camera FPS", "processed FPS"]
    headers += ["dropped %", "delay avg ms", "delay p95 ms", "detect %"]
    headers += ["peak RSS MB", "peak RAM MB", "avg CPU %", "max temp C", "min MHz", "flags"]
    rows = []
    for s in summaries:
        if s.stats is None:
            short = f"too short (needs more than {WEBCAM_WARMUP_MS / 1000:g} s)" if s.frames else "-"
            live = ["0", short, *["-"] * 5]
        else:
            live = [
                str(s.stats.camera_frames),
                f"{s.stats.camera_fps:.2f}",
                f"{s.stats.processed_fps:.2f}",
                _cell(s.stats.dropped_pct, "{:.1f}"),
                _cell(s.stats.delay_avg_ms, "{:.1f}"),
                _cell(s.stats.delay_p95_ms, "{:.1f}"),
                _cell(s.stats.detection_rate, "{:.1f}"),
            ]
        system = [
            _cell(s.peak_rss_mb),
            _cell(s.peak_ram_used_mb),
            _cell(s.avg_cpu_pct, "{:.1f}"),
            _cell(s.max_temp_c, "{:.1f}"),
            _cell(s.min_cpu_mhz),
            ", ".join(s.flags) or "-",
        ]
        rows.append([s.variant, str(s.session), s.machine, s.status, str(s.frames), *live, *system])
    return _aligned(headers, rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bench.analysis", description="Summarise Run files.")
    parser.add_argument("paths", nargs="+", help="Run .jsonl files or directories of them")
    args = parser.parse_args(argv)
    try:
        summaries, sessions = analyze(args.paths), analyze_webcam(args.paths)
    except FileNotFoundError as e:
        parser.error(f"no such file or directory: {e}")
    if not summaries and not sessions:
        parser.error("no Run files found")
    tables = [format_table(summaries)] if summaries else []
    if sessions:
        tables.append("Webcam phase\n" + format_webcam_table(sessions))
    print("\n\n".join(tables))
    return 0


if __name__ == "__main__":
    sys.exit(main())
