"""Run the whole Video phase, or the Webcam phase's sessions, as one unattended Campaign on the Board.

    python -m bench.campaign --clips-dir clips --out-dir campaigns
    python -m bench.campaign --webcam --seconds 60 --variants lite --out-dir campaigns
"""
import argparse
import json
import math
import os
import random
import re
import statistics
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from itertools import product
from pathlib import Path

from bench.envinfo import default_machine_name
from bench.models import VARIANTS
from bench.runfile import LIVE, VIDEO, WEBCAM, run_file_name
from bench.sampler import read_temp_c

STDERR_TAIL_CHARS = 500


@dataclass(frozen=True)
class RunSpec:
    variant: str
    clip: str
    repeat: int


@dataclass(frozen=True)
class Cooldown:
    temp_before_c: float | None
    temp_at_start_c: float | None
    waited_s: float
    timed_out: bool
    skipped: str | None = None


@dataclass(frozen=True)
class ProcessResult:
    returncode: int | None
    stderr: str
    timed_out: bool


@dataclass(frozen=True)
class CampaignConfig:
    campaign_id: str
    seed: int
    variants: tuple[str, ...]
    clips: tuple[str, ...]
    repeats: int
    clips_dir: Path
    out_dir: Path
    machine: str
    cooldown_tolerance_c: float
    cooldown_timeout_s: float
    baseline_seconds: float
    sample_interval_s: float
    run_timeout_s: float
    # None for the Video phase. For the Webcam phase, the length of each session, planned as the one clip "live".
    session_s: float | None = None

    def __post_init__(self) -> None:
        if self.session_s is not None and self.clips != (LIVE,):
            raise ValueError(f"a Webcam phase Campaign plans the clip {LIVE!r} only, got {self.clips}")

    @property
    def phase(self) -> str:
        return VIDEO if self.session_s is None else WEBCAM


@dataclass(frozen=True)
class RunRecord:
    index: int
    variant: str
    clip: str
    repeat: int
    file: str
    cooldown: Cooldown
    started_at: str
    duration_s: float
    returncode: int | None
    status: str
    detail: str


def plan(variants: list[str], clips: list[str], repeats: int, seed: int) -> list[RunSpec]:
    # Sorting first makes the order depend only on the seed, not on how the caller listed the inputs.
    specs = [RunSpec(v, c, r) for v, c, r in product(sorted(set(variants)), sorted(set(clips)), range(1, repeats + 1))]
    random.Random(seed).shuffle(specs)
    return specs


def measure_baseline(
    read_temp: Callable[[], float | None], seconds: float, sleep: Callable[[float], None] = time.sleep
) -> float | None:
    """Median idle temperature, one reading per second. None when the machine has no readable sensor."""
    readings: list[float] = []
    for _ in range(max(1, int(seconds))):
        temp = read_temp()
        if temp is None and not readings:
            return None
        if temp is not None:
            readings.append(temp)
        sleep(1.0)
    return statistics.median(readings)


def wait_until_cool(
    read_temp: Callable[[], float | None],
    target_c: float | None,
    timeout_s: float,
    poll_s: float = 5.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Cooldown:
    first = read_temp()
    if target_c is None or first is None:
        return Cooldown(first, first, 0.0, False, skipped="temperature unavailable")
    start = clock()
    current = first
    # A missing reading mid-wait counts as still hot rather than as permission to start.
    while current is None or current > target_c:
        waited = clock() - start
        if waited >= timeout_s:
            return Cooldown(first, current, round(waited, 1), True)
        sleep(min(poll_s, timeout_s - waited))
        current = read_temp()
    return Cooldown(first, current, round(clock() - start, 1), False)


def run_command(config: CampaignConfig, spec: RunSpec, campaign_dir: Path) -> list[str]:
    """The child process for one Run: bench.run_one over a Clip, or bench.live for one Webcam phase session."""
    common = [
        "--variant", spec.variant,
        "--repeat", str(spec.repeat),
        "--machine", config.machine,
        "--out-dir", str(campaign_dir),
        "--sample-interval", str(config.sample_interval_s),
    ]
    if config.phase == WEBCAM:
        return [sys.executable, "-m", "bench.live", *common, "--seconds", str(config.session_s)]
    return [sys.executable, "-m", "bench.run_one", *common, "--clip", str(config.clips_dir / spec.clip)]


def run_process(cmd: list[str], timeout_s: float) -> ProcessResult:
    try:
        done = subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, errors="replace", timeout=timeout_s
        )
    except subprocess.TimeoutExpired:
        return ProcessResult(None, "", True)
    return ProcessResult(done.returncode, done.stderr, False)


def _failure(result: ProcessResult, run_timeout_s: float) -> tuple[str, str]:
    if result.timed_out:
        return "crashed", f"timed out after {run_timeout_s:g} s"
    code = result.returncode
    if code == -9:
        status, how = "oom", "killed by SIGKILL (exit -9)"
    elif code is not None and code < 0:
        status, how = "crashed", f"killed by signal {-code}"
    else:
        status, how = "crashed", f"exit code {code}"
    tail = result.stderr.strip()[-STDERR_TAIL_CHARS:]
    return status, f"{how}: {tail}" if tail else how


def settle_run_file(path: Path, result: ProcessResult, run_timeout_s: float) -> tuple[str, str]:
    """The Run's final status. A Run that died before writing its own gets one appended, or a file created for it."""
    data = path.read_bytes() if path.exists() else b""
    # A kill can leave a half-written last line; cutting it keeps the status line readable in Analysis.
    complete = data[: data.rfind(b"\n") + 1]
    lines = complete.splitlines()
    if lines:
        try:
            last = json.loads(lines[-1])
        except ValueError:
            last = None
        if isinstance(last, dict) and last.get("type") == "status":
            return last["status"], last.get("detail", "")
    status, detail = _failure(result, run_timeout_s)
    line = json.dumps({"type": "status", "status": status, "detail": detail}) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(complete + line.encode())
    return status, detail


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _announce(text: str) -> None:
    print(text, flush=True)


def _describe_cooldown(c: Cooldown, target_c: float | None) -> str:
    if c.skipped:
        return f"no cool-down ({c.skipped})"
    if c.timed_out:
        return f"cool-down TIMED OUT after {c.waited_s:g} s at {c.temp_at_start_c} C (target {target_c:.1f})"
    return f"cooled {c.temp_before_c:.1f} -> {c.temp_at_start_c:.1f} C in {c.waited_s:g} s (target {target_c:.1f})"


def _write_atomically(path: Path, document: dict) -> None:
    # Pollers read this while the Campaign runs, so they must never see a half-written file.
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(document, indent=2, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def run_campaign(
    config: CampaignConfig,
    *,
    poll_s: float = 5.0,
    read_temp: Callable[[], float | None] = read_temp_c,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    now: Callable[[], str] = _utc_now,
    run_process: Callable[[list[str], float], ProcessResult] = run_process,
    say: Callable[[str], None] = _announce,
) -> dict:
    campaign_dir = config.out_dir / config.campaign_id
    campaign_dir.mkdir(parents=True, exist_ok=False)
    specs = plan(list(config.variants), list(config.clips), config.repeats, config.seed)

    say(f"campaign {config.campaign_id}: {len(specs)} Runs, seed {config.seed}, machine {config.machine}")
    baseline_c = measure_baseline(read_temp, config.baseline_seconds, sleep)
    target_c = None if baseline_c is None else baseline_c + config.cooldown_tolerance_c
    say(
        "baseline: temperature unavailable, Runs start without cooling"
        if baseline_c is None
        else f"baseline {baseline_c:.1f} C, cool target {target_c:.1f} C"
    )

    records: list[RunRecord] = []
    log = {
        "campaign_id": config.campaign_id,
        "started_at": now(),
        "finished_at": None,
        "seed": config.seed,
        "machine": config.machine,
        "parameters": {k: v for k, v in asdict(config).items() if k not in ("campaign_id", "seed", "machine")},
        "baseline_c": baseline_c,
        "target_c": target_c,
        "runs": [],
        "totals": {},
    }

    def save() -> None:
        log["runs"] = [asdict(r) for r in records]
        log["totals"] = {
            "planned": len(specs),
            "done": len(records),
            "total_cooldown_s": round(sum(r.cooldown.waited_s for r in records), 1),
            "cooldown_timeouts": sum(r.cooldown.timed_out for r in records),
            "status_counts": dict(Counter(r.status for r in records)),
        }
        _write_atomically(campaign_dir / "campaign.json", log)

    save()
    for index, spec in enumerate(specs, 1):
        cooldown = wait_until_cool(read_temp, target_c, config.cooldown_timeout_s, poll_s, sleep, clock)
        if config.phase == WEBCAM:
            say(
                f"[{index}/{len(specs)}] starting {spec.variant} {spec.clip} r{spec.repeat}: "
                f"{config.session_s:g} s from the camera, move in front of the camera now"
            )
        started_at, t0 = now(), clock()
        result = run_process(run_command(config, spec, campaign_dir), config.run_timeout_s)
        duration_s = round(clock() - t0, 1)
        file = run_file_name(spec.variant, Path(spec.clip).stem, spec.repeat, config.machine, config.phase)
        status, detail = settle_run_file(campaign_dir / file, result, config.run_timeout_s)
        records.append(
            RunRecord(
                index, spec.variant, spec.clip, spec.repeat, file, cooldown, started_at, duration_s,
                result.returncode, status, detail,
            )
        )
        save()
        say(
            f"[{index}/{len(specs)}] {spec.variant} {spec.clip} r{spec.repeat}: "
            f"{_describe_cooldown(cooldown, target_c)}; {status} in {duration_s:g} s"
        )

    log["finished_at"] = now()
    save()
    totals = log["totals"]
    say(
        f"campaign {config.campaign_id} finished: {totals['status_counts']}, "
        f"{totals['total_cooldown_s']:g} s cooling, {totals['cooldown_timeouts']} cool-down timeouts"
    )
    return log


def _bounded(kind: type, low: float, inclusive: bool = False) -> Callable[[str], float]:
    def parse(text: str):
        try:
            value = kind(text)
        except ValueError:
            raise argparse.ArgumentTypeError(f"not a number: {text}")
        if not (math.isfinite(value) and (value >= low if inclusive else value > low)):
            bound = f"{'at least' if inclusive else 'above'} {low:g}"
            raise argparse.ArgumentTypeError(f"must be finite and {bound}, got {text}")
        return value

    return parse


def _clip_name(text: str) -> str:
    return text if Path(text).suffix else text + ".mp4"


def main() -> int:
    p = argparse.ArgumentParser(description="Run every Model variant on every Clip, shuffled, cooling the Board between Runs.")
    p.add_argument("--webcam", action="store_true", help="Webcam phase: live sessions from the camera instead of Clips")
    p.add_argument("--seconds", type=_bounded(float, 0), default=60.0, help="length of each Webcam phase session")
    p.add_argument("--clips-dir", type=Path, default=Path("clips"))
    p.add_argument("--clips", nargs="+", type=_clip_name, help="Clip names (default: every .mp4 in --clips-dir)")
    p.add_argument("--variants", nargs="+", choices=VARIANTS, default=list(VARIANTS))
    p.add_argument("--repeats", type=_bounded(int, 1, inclusive=True), default=3)
    p.add_argument("--seed", type=int, help="shuffle seed (default: random, and recorded)")
    p.add_argument("--out-dir", type=Path, default=Path("campaigns"))
    p.add_argument("--campaign-id", help="directory name under --out-dir (default: UTC timestamp)")
    p.add_argument("--machine", default=default_machine_name())
    p.add_argument("--cooldown-tolerance", type=_bounded(float, 0, inclusive=True), default=2.0, help="degrees C above baseline")
    p.add_argument("--cooldown-timeout", type=_bounded(float, 0), default=600.0, help="seconds to wait before a Run")
    p.add_argument("--baseline-seconds", type=_bounded(float, 0), default=30.0)
    p.add_argument("--sample-interval", type=_bounded(float, 0), default=1.0, help="seconds between system samples")
    p.add_argument(
        "--run-timeout", type=_bounded(float, 0),
        help="seconds before a hung Run is killed (default: 1800, or the session length + 300 with --webcam)",
    )
    p.add_argument("--print-plan", action="store_true", help="print the Run order for these inputs and seed, run nothing")
    a = p.parse_args()

    if a.webcam:
        if a.clips is not None:
            p.error("--clips does not apply to --webcam")
        clips = [LIVE]
    else:
        clips = a.clips if a.clips is not None else sorted(f.name for f in a.clips_dir.glob("*.mp4"))
    if not clips:
        p.error(f"no .mp4 Clips in {a.clips_dir}")
    campaign_id = a.campaign_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", campaign_id):
        p.error(f"campaign id may only use letters, digits, - and _, got {campaign_id!r}")
    seed = a.seed if a.seed is not None else random.SystemRandom().randrange(2**32)

    if a.print_plan:
        print(f"seed {seed}")
        for i, s in enumerate(plan(a.variants, clips, a.repeats, seed), 1):
            print(f"{i} {s.variant} {s.clip} r{s.repeat}")
        return 0

    missing = [] if a.webcam else [c for c in clips if not (a.clips_dir / c).is_file()]
    if missing:
        p.error(f"Clips not found in {a.clips_dir}: {', '.join(missing)}")
    if (a.out_dir / campaign_id).exists():
        p.error(f"{a.out_dir / campaign_id} already exists")

    run_campaign(
        CampaignConfig(
            campaign_id=campaign_id,
            seed=seed,
            variants=tuple(sorted(set(a.variants))),
            clips=tuple(sorted(set(clips))),
            repeats=a.repeats,
            clips_dir=a.clips_dir,
            out_dir=a.out_dir,
            machine=a.machine,
            cooldown_tolerance_c=a.cooldown_tolerance,
            cooldown_timeout_s=a.cooldown_timeout,
            baseline_seconds=a.baseline_seconds,
            sample_interval_s=a.sample_interval,
            # Model load, camera set-up and the end-of-session drain come on top of the session itself.
            run_timeout_s=a.run_timeout or (a.seconds + 300 if a.webcam else 1800.0),
            session_s=a.seconds if a.webcam else None,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
