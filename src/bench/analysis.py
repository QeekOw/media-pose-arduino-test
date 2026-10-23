import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from bench.runfile import RunFile, read_run

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

    @property
    def has_numbers(self) -> bool:
        return self.fps is not None


def identity_from_name(path: Path) -> tuple[str, str, int, str]:
    parts = path.stem.split("__")
    if len(parts) == 5 and re.fullmatch(r"r\d+", parts[3]):
        return parts[1], parts[2], int(parts[3][1:]), parts[4]
    return "?", path.stem, 0, "?"


def status_text(run: RunFile) -> str:
    if run.problem is not None:
        return f"failed: {run.problem}"
    return NO_STATUS if run.status is None else run.status


def summarize(run: RunFile) -> RunSummary:
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
    summaries = [summarize(read_run(p)) for p in find_run_files(paths)]
    return sorted(summaries, key=lambda s: (s.variant, s.clip, s.repeat, s.machine))


def format_table(summaries: list[RunSummary]) -> str:
    headers = ["variant", "clip", "repeat", "machine", "status", "frames", "kept", "FPS", "avg ms", "p95 ms"]
    rows = []
    for s in summaries:
        if s.has_numbers:
            numbers = [f"{s.fps:.2f}", f"{s.avg_ms:.1f}", f"{s.p95_ms:.1f}"]
        else:
            numbers = [f"too few frames (need {WARMUP_FRAMES + 1})", "-", "-"]
        rows.append(
            [s.variant, s.clip, str(s.repeat), s.machine, s.status, str(s.frames), str(s.kept_frames), *numbers]
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
