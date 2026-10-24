"""Run the whole Video phase as one unattended Campaign, on the Board.

    python -m bench.campaign --clips-dir clips --out-dir campaigns
"""
import random
import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass
from itertools import product


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
