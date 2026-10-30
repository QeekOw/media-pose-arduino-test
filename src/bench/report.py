"""Turn Run files into the answer: Pass criteria verdicts (ADR 0004), spread across repeats, a summary table and charts."""
import argparse
import operator
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from bench.analysis import RunSummary, analyze
from bench.models import VARIANTS
from bench.quality import clip_stem

BOARD = "board"
LAPTOP = "dev"
CLIPS = ("front", "side", "fast", "far", "empty")
REPEATS = 3
NONE_PASSED = (
    'No Model variant passed the Pass criteria, so the Webcam phase falls back to an "as-is" Lite demo.'
)


def failed_runs(runs: list[RunSummary]) -> int:
    return sum(r.status != "completed" for r in runs)


def fewest_runs_on_a_clip(runs: list[RunSummary]) -> int:
    clips = [clip_stem(r.clip) for r in runs]
    return min(clips.count(clip) for clip in CLIPS)


def pooled_fps(runs: list[RunSummary]) -> float | None:
    times = [ms for r in runs for ms in r.frame_ms]
    return len(times) / (sum(times) / 1000.0) if times else None


def pooled_p95_ms(runs: list[RunSummary]) -> float | None:
    times = [ms for r in runs for ms in r.frame_ms]
    return float(np.percentile(times, 95)) if times else None


def pooled_detection_rate(runs: list[RunSummary]) -> float | None:
    """Percent of frames with a pose, over all frames of Clips with a person."""
    weighted = [(r.detection_rate, r.kept_frames) for r in runs if r.detection_rate is not None]
    frames = sum(n for _, n in weighted)
    return sum(rate * n for rate, n in weighted) / frames if frames else None


def pooled_pck(runs: list[RunSummary]) -> float | None:
    """Percent of all compared landmarks within the PCK threshold, so each Run counts by the landmarks it was scored on."""
    weighted = [(r.pck, r.pck_landmarks) for r in runs if r.pck is not None]
    landmarks = sum(n for _, n in weighted)
    return sum(pck * n for pck, n in weighted) / landmarks if landmarks else None


@dataclass(frozen=True)
class Rule:
    name: str
    measure: Callable[[list[RunSummary]], float | None]
    compare: Callable[[float, float], bool]
    limit: float
    fmt: str


RULES = (
    Rule("average FPS at least 10", pooled_fps, operator.ge, 10.0, "{:.1f} FPS"),
    Rule("slowest-5% frame time at most 150 ms", pooled_p95_ms, operator.le, 150.0, "{:.0f} ms"),
    Rule("detection at least 90% on Clips with a person", pooled_detection_rate, operator.ge, 90.0, "{:.1f}%"),
    Rule("no failed Runs", failed_runs, operator.le, 0, "{} failed"),
    Rule("3 Runs on each of the five Campaign Clips", fewest_runs_on_a_clip, operator.ge, REPEATS, "fewest on one Clip: {}"),
)


@dataclass(frozen=True)
class RuleResult:
    rule: Rule
    value: float | None

    @property
    def passed(self) -> bool:
        return self.value is not None and self.rule.compare(self.value, self.rule.limit)

    def describe(self) -> str:
        shown = "no data" if self.value is None else self.rule.fmt.format(self.value)
        return f"{self.rule.name} ({shown})"


@dataclass(frozen=True)
class Verdict:
    variant: str
    runs: int
    results: tuple[RuleResult, ...]

    @property
    def failed_rules(self) -> list[RuleResult]:
        return [r for r in self.results if not r.passed]

    @property
    def passed(self) -> bool:
        return not self.failed_rules


def campaign_runs(summaries: list[RunSummary], machine: str) -> list[RunSummary]:
    return [s for s in summaries if s.machine == machine and clip_stem(s.clip) in CLIPS]


def by_variant(runs: list[RunSummary]) -> dict[str, list[RunSummary]]:
    grouped = {v: [r for r in runs if r.variant == v] for v in VARIANTS}
    return {v: rs for v, rs in grouped.items() if rs}


def verdicts(summaries: list[RunSummary]) -> list[Verdict]:
    """Apply the Pass criteria to all of each Model variant's Board Runs together."""
    return [
        Verdict(variant, len(runs), tuple(RuleResult(rule, rule.measure(runs)) for rule in RULES))
        for variant, runs in by_variant(campaign_runs(summaries, BOARD)).items()
    ]


def _runs(n: int) -> str:
    return f"{n} Run" if n == 1 else f"{n} Runs"


def format_verdicts(results: list[Verdict]) -> str:
    """Name every failed rule. Only once every Model variant has a verdict can "none passed" be the finding."""
    lines = []
    for v in results:
        if v.passed:
            lines.append(f"{v.variant}: PASS ({_runs(v.runs)})")
        else:
            lines.append(f"{v.variant}: FAIL ({_runs(v.runs)})")
            lines.extend(f"  fails: {r.describe()}" for r in v.failed_rules)
    judged = {v.variant for v in results}
    lines.extend(f"{variant}: no Board Runs on the Campaign Clips yet" for variant in VARIANTS if variant not in judged)
    if judged == set(VARIANTS) and not any(v.passed for v in results):
        lines.append(NONE_PASSED)
    return "\n".join(lines)


@dataclass(frozen=True)
class Spread:
    variant: str
    clip: str
    machine: str
    repeats: int
    fps_mean: float
    fps_min: float
    fps_max: float
    p95_min: float
    p95_max: float

    @property
    def fps_spread_pct(self) -> float:
        """Range of FPS across repeats as a percent of their mean."""
        return 100.0 * (self.fps_max - self.fps_min) / self.fps_mean


def spread(summaries: list[RunSummary]) -> list[Spread]:
    """How much FPS and slowest-5% frame time vary across the repeats of each Model variant, Clip and machine."""
    cases: dict[tuple[str, str, str], list[RunSummary]] = {}
    for s in summaries:
        if s.has_numbers and s.status == "completed" and clip_stem(s.clip) in CLIPS:
            cases.setdefault((s.variant, clip_stem(s.clip), s.machine), []).append(s)
    out = []
    for (variant, clip, machine), runs in sorted(cases.items()):
        fps = [r.fps for r in runs]
        p95 = [r.p95_ms for r in runs]
        out.append(Spread(variant, clip, machine, len(runs), float(np.mean(fps)), min(fps), max(fps), min(p95), max(p95)))
    return out


def _table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [max(len(r[i]) for r in [headers, *rows]) for i in range(len(headers))]
    return "\n".join("  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip() for r in [headers, *rows])


def format_spread(rows: list[Spread]) -> str:
    headers = ["variant", "clip", "machine", "repeats", "FPS mean", "FPS min-max", "FPS spread %", "p95 ms min-max"]
    return _table(headers, [
        [s.variant, s.clip, s.machine, str(s.repeats), f"{s.fps_mean:.2f}", f"{s.fps_min:.2f}-{s.fps_max:.2f}",
         f"{s.fps_spread_pct:.1f}", f"{s.p95_min:.0f}-{s.p95_max:.0f}"]
        for s in rows
    ])


SUMMARY_COLUMNS: list[tuple[str, Callable[[list[RunSummary]], float | None], str]] = [
    ("FPS", pooled_fps, "{:.1f}"),
    ("p95 ms", pooled_p95_ms, "{:.0f}"),
    ("detect %", pooled_detection_rate, "{:.1f}"),
    ("PCK %", pooled_pck, "{:.1f}"),
]


def summary_table(summaries: list[RunSummary]) -> tuple[list[str], list[list[str]]]:
    """One row per Model variant: Board and Laptop baseline side by side, then the verdict."""
    board, laptop = (by_variant(campaign_runs(summaries, m)) for m in (BOARD, LAPTOP))
    passed = {v.variant: "PASS" if v.passed else "FAIL" for v in verdicts(summaries)}
    headers = ["Variant"]
    for name, _, _ in SUMMARY_COLUMNS:
        headers += [f"{name}\nBoard", f"{name}\nLaptop"]
    headers.append("Verdict")
    rows = []
    for variant in [v for v in VARIANTS if v in board or v in laptop]:
        row = [variant.capitalize()]
        for _, measure, fmt in SUMMARY_COLUMNS:
            for runs in (board.get(variant), laptop.get(variant)):
                value = measure(runs) if runs else None
                row.append("-" if value is None else fmt.format(value))
        row.append(passed.get(variant, "not run"))
        rows.append(row)
    return headers, rows


def write_charts(summaries: list[RunSummary], out_dir: Path) -> list[Path]:
    plt.rcParams.update({"font.size": 16, "axes.titlesize": 20, "axes.spines.top": False, "axes.spines.right": False})
    out_dir.mkdir(parents=True, exist_ok=True)
    board, laptop = (by_variant(campaign_runs(summaries, m)) for m in (BOARD, LAPTOP))
    variants = [v for v in VARIANTS if v in board or v in laptop]
    colors = {BOARD: "#0B5C8A", LAPTOP: "#9AA5B1"}
    written = []

    def save(fig, name: str) -> None:
        path = out_dir / name
        fig.savefig(path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        written.append(path)

    headers, rows = summary_table(summaries)
    fig, ax = plt.subplots(figsize=(13.33, 1.2 + 0.7 * len(rows)))
    ax.axis("off")
    table = ax.table(cellText=rows, colLabels=headers, loc="center", cellLoc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(15)
    table.scale(1, 2.6)
    table.auto_set_column_width(range(len(headers)))
    for (row, _), cell in table.get_celld().items():
        cell.set_edgecolor("#D0D7DE")
        if row == 0:
            cell.set_text_props(weight="bold")
            cell.set_height(cell.get_height() * 1.5)
    for row, cells in enumerate(rows, start=1):
        cell = table[row, len(headers) - 1]
        cell.set_text_props(weight="bold", color={"PASS": "#1A7F37", "FAIL": "#B42318"}.get(cells[-1], "#5B6573"))
    save(fig, "summary-table.png")

    fig, ax = plt.subplots(figsize=(10, 5.6))
    x = np.arange(len(variants))
    for offset, machine, label, grouped in ((-0.2, BOARD, "Board", board), (0.2, LAPTOP, "Laptop", laptop)):
        values = [pooled_fps(grouped[v]) if v in grouped else None for v in variants]
        bars = ax.bar(x + offset, [0 if f is None else f for f in values], 0.4, label=label, color=colors[machine])
        ax.bar_label(bars, ["not run" if f is None else f"{f:.1f}" for f in values], padding=3)
    ax.axhline(10, color="#B42318", linestyle="--", linewidth=1.5, label="pass: 10 FPS")
    ax.set_xticks(x, [v.capitalize() for v in variants])
    ax.set_ylabel("average FPS")
    ax.set_title("FPS per Model variant")
    ax.legend(frameon=False)
    save(fig, "fps.png")

    board_variants = [v for v in variants if v in board and any(r.frame_ms for r in board[v])]
    if board_variants:
        fig, ax = plt.subplots(figsize=(10, 5.6))
        data = [[ms for r in board[v] for ms in r.frame_ms] for v in board_variants]
        ax.boxplot(data, whis=(5, 95), showfliers=False, patch_artist=True,
                   boxprops={"facecolor": "#DCEBF5", "edgecolor": colors[BOARD]},
                   medianprops={"color": colors[BOARD], "linewidth": 2})
        ax.set_xticks(range(1, len(board_variants) + 1), [v.capitalize() for v in board_variants])
        ax.axhline(150, color="#B42318", linestyle="--", linewidth=1.5, label="pass: slowest 5% at most 150 ms")
        ax.legend(frameon=False)
        ax.set_ylabel("frame time (ms)")
        ax.set_title("Frame time on the Board (whiskers: 5th to 95th percentile)")
        save(fig, "frame-times.png")

    points = {
        (machine, label, marker): [(v, pooled_fps(runs), pooled_pck(runs)) for v, runs in grouped.items()]
        for machine, label, grouped, marker in ((BOARD, "Board", board, "o"), (LAPTOP, "Laptop", laptop, "s"))
    }
    points = {k: [p for p in ps if p[1] is not None and p[2] is not None] for k, ps in points.items()}
    if any(points.values()):
        fig, ax = plt.subplots(figsize=(10, 5.6))
        for (machine, label, marker), ps in points.items():
            if not ps:
                continue
            ax.scatter([p[1] for p in ps], [p[2] for p in ps], s=140, marker=marker, color=colors[machine], label=label)
            for v, fps, accuracy in ps:
                ax.annotate(v.capitalize(), (fps, accuracy), textcoords="offset points", xytext=(8, 6))
        ax.set_xlabel("average FPS")
        ax.set_ylabel("PCK@0.2 vs Reference landmarks (%)")
        ax.set_title("Accuracy vs speed")
        ax.legend(frameon=False)
        save(fig, "accuracy-vs-speed.png")

    hottest = {v: max(runs, key=lambda r: max((t for _, t in r.temps), default=0)) for v, runs in board.items()}
    hottest = {v: r for v, r in hottest.items() if r.temps}
    if hottest:
        fig, ax = plt.subplots(figsize=(10, 5.6))
        for v, run in hottest.items():
            t0 = run.temps[0][0]
            ax.plot([(t - t0) / 1000 for t, _ in run.temps], [c for _, c in run.temps], linewidth=2,
                    label=f"{v.capitalize()} ({clip_stem(run.clip)}, repeat {run.repeat})")
        ax.set_xlabel("time into Run (s)")
        ax.set_ylabel("CPU temperature (°C)")
        ax.set_title("Temperature over the hottest Board Run per Model variant")
        ax.legend(frameon=False)
        save(fig, "temperature.png")
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bench.report", description="Verdicts, spread, summary table, charts.")
    parser.add_argument("paths", nargs="+", help="Run .jsonl files or directories of them: the Board's and runs/dev")
    parser.add_argument("--out-dir", type=Path, default=Path("report"), help="where to write the chart images")
    args = parser.parse_args(argv)
    try:
        summaries = analyze(args.paths)
    except FileNotFoundError as e:
        parser.error(f"no such file or directory: {e}")
    if not summaries:
        parser.error("no Run files found")
    print("Pass criteria\n" + format_verdicts(verdicts(summaries)))
    print("\nSpread across repeats\n" + format_spread(spread(summaries)))
    headers, rows = summary_table(summaries)
    print("\nSummary\n" + _table([h.replace("\n", " ") for h in headers], rows))
    print()
    for path in write_charts(summaries, args.out_dir):
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
