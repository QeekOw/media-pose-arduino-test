import math
import queue
import threading
import time
from pathlib import Path

from bench.runfile import Sample


def _fields(path: Path) -> dict[str, list[str]] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None
    return {parts[0].rstrip(":"): parts[1:] for parts in map(str.split, text.splitlines()) if parts}


def _cpu_times(proc: Path) -> tuple[int, int] | None:
    try:
        values = [int(v) for v in _fields(proc / "stat")["cpu"]]
    except (TypeError, KeyError, ValueError):
        return None
    # guest and guest_nice (fields 9 and 10) are already counted in user and nice.
    total = sum(values[:8])
    idle = sum(values[3:5])
    return total - idle, total


def _kb(fields: dict[str, list[str]] | None, name: str) -> int | None:
    try:
        return int(fields[name][0])
    except (TypeError, KeyError, IndexError, ValueError):
        return None


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def read_temp_c(root: Path = Path("/sys")) -> float | None:
    zones = []
    for zone in sorted(root.glob("class/thermal/thermal_zone*")):
        try:
            kind = (zone / "type").read_text(encoding="utf-8").strip()
        except (OSError, ValueError):
            kind = ""
        millideg = _read_int(zone / "temp")
        if millideg is not None:
            zones.append((kind, millideg / 1000))
    cpu = [t for kind, t in zones if kind.startswith("cpu")]
    temps = cpu or [t for _, t in zones]
    return max(temps) if temps else None


def _cpu_mhz(root: Path) -> int | None:
    # Max across cores: idle cores clock down on their own, but a thermal throttle caps every core.
    khz = [_read_int(p) for p in root.glob("devices/system/cpu/cpu*/cpufreq/scaling_cur_freq")]
    khz = [k for k in khz if k is not None]
    return max(khz) // 1000 if khz else None


class Sampler:
    def __init__(self, interval_s: float = 1.0, proc_root: Path = Path("/proc"), sys_root: Path = Path("/sys")):
        if not (math.isfinite(interval_s) and interval_s > 0):
            raise ValueError(f"sample interval must be a finite number of seconds above 0, got {interval_s}")
        self.interval_s = interval_s
        self._proc = Path(proc_root)
        self._sys = Path(sys_root)
        self._queue: queue.SimpleQueue[Sample] = queue.SimpleQueue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._start = 0.0
        self._prev_cpu: tuple[int, int] | None = None

    def _take(self) -> Sample:
        cpu = _cpu_times(self._proc)
        cpu_pct = None
        if cpu is not None and self._prev_cpu is not None:
            busy, total = cpu[0] - self._prev_cpu[0], cpu[1] - self._prev_cpu[1]
            if total > 0:
                cpu_pct = 100.0 * busy / total
        meminfo = _fields(self._proc / "meminfo")
        mem_total, mem_available = _kb(meminfo, "MemTotal"), _kb(meminfo, "MemAvailable")
        status = _fields(self._proc / "self" / "status")
        rss, rss_peak = _kb(status, "VmRSS"), _kb(status, "VmHWM")
        sample = Sample(
            t_ms=round((time.monotonic() - self._start) * 1000),
            cpu_pct=cpu_pct,
            ram_used_mb=None if mem_total is None or mem_available is None else (mem_total - mem_available) // 1024,
            rss_mb=None if rss is None else rss // 1024,
            rss_peak_mb=None if rss_peak is None else rss_peak // 1024,
            temp_c=read_temp_c(self._sys),
            cpu_mhz=_cpu_mhz(self._sys),
        )
        # Set only once the sample exists, so cpu_pct always spans back to the previous recorded sample.
        self._prev_cpu = cpu
        return sample

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_s):
            try:
                self._queue.put(self._take())
            except Exception:
                # One bad read skips its tick; letting it escape would end sampling for the rest of the Run.
                pass

    def start(self) -> None:
        self._start = time.monotonic()
        self._queue.put(self._take())
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join()
        self._queue.put(self._take())

    def drain(self) -> list[Sample]:
        samples = []
        while True:
            try:
                samples.append(self._queue.get_nowait())
            except queue.Empty:
                return samples
