import argparse
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from bench.quality import Quality, clip_stem, measure
from bench.runfile import Frame, RunFile, Sample, read_run

WARMUP_FRAMES = 30
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
    detection_rate: float | None
    false_detection_rate: float | None
    jitter: float | None
    flags: tuple[str, ...]

    @property
    def has_numbers(self) -> bool:
        return self.fps is not None


def identity_from_name(path: Path) -> tuple[str, str, int, str]:
    parts = path.stem.split("__")
    if len(parts) == 5 and re.fullmatch(r"r\d+", parts[3]):
        return parts[1], parts[2], int(parts[3][1:]), parts[4]
    return "?", path.stem, 0, "?"


def readings(run: RunFile, *fields: str) -> list:
    return [v for s in run.samples for name in fields if (v := getattr(s, name)) is not None]


def _any_reading(run: RunFile, fields: tuple[str, ...], bad: Callable[[float], bool]) -> bool:
    return any(bad(v) for v in readings(run, *fields))


IMPLAUSIBLE: list[tuple[str, Callable[[RunFile], bool]]] = [
    ("no frames", lambda run: not run.frames),
    ("no samples", lambda run: not run.samples),
    ("temp 0 or out of range", lambda run: _any_reading(run, ("temp_c",), lambda t: t <= 0 or t > 125)),
    ("clock 0", lambda run: _any_reading(run, ("cpu_mhz",), lambda mhz: mhz <= 0)),
    ("ram 0", lambda run: _any_reading(run, ("ram_used_mb", "rss_mb", "rss_peak_mb"), lambda mb: mb <= 0)),
    ("cpu % out of range", lambda run: _any_reading(run, ("cpu_pct",), lambda pct: pct < 0 or pct > 100)),
]


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


def summarize(run: RunFile, references: dict[str, list[Frame]] | None = None) -> RunSummary:
    kept = run.frames[WARMUP_FRAMES:]
    fps = avg_ms = p95_ms = None
    if kept:
        times = np.array([f.frame_ms for f in kept], dtype=float)
        fps = len(times) / (times.sum() / 1000.0)
        avg_ms = float(times.mean())
        p95_ms = float(np.percentile(times, 95))
    if run.header is None:
        variant, clip, repeat, machine = identity_from_name(run.path)
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
        # rss_peak_mb is the kernel's exact high-water mark; files written before it existed only have polled rss_mb.
        peak_rss_mb=_over(max, readings(run, "rss_peak_mb") or readings(run, "rss_mb")),
        peak_ram_used_mb=_over(max, readings(run, "ram_used_mb")),
        avg_cpu_pct=avg_cpu_pct(run.samples),
        max_temp_c=_over(max, readings(run, "temp_c")),
        min_cpu_mhz=_over(min, readings(run, "cpu_mhz")),
        pck=quality.pck,
        detection_rate=quality.detection_rate,
        false_detection_rate=quality.false_detection_rate,
        jitter=quality.jitter,
        flags=tuple(name for name, implausible in IMPLAUSIBLE if implausible(run)),
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


def analyze(paths: list[str | Path]) -> list[RunSummary]:
    runs = [read_run(p) for p in find_run_files(paths)]
    references = reference_frames(runs)
    summaries = [summarize(run, references) for run in runs]
    return sorted(summaries, key=lambda s: (s.variant, s.clip, s.repeat, s.machine))


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
    widths = [max(len(r[i]) for r in [headers, *rows]) for i in range(len(headers))]
    lines = ["  ".join(cell.ljust(w) for cell, w in zip(r, widths)).rstrip() for r in [headers, *rows]]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bench.analysis", description="Summarise Run files.")
    parser.add_argument("paths", nargs="+", help="Run .jsonl files or directories of them")
    args = parser.parse_args(argv)
    try:
        summaries = analyze(args.paths)
    except FileNotFoundError as e:
        parser.error(f"no such file or directory: {e}")
    if not summaries:
        parser.error("no Run files found")
    print(format_table(summaries))
    return 0


if __name__ == "__main__":
    sys.exit(main())
