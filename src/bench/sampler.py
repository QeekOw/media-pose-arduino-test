import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Sample:
    t_ms: int
    cpu_pct: float | None
    ram_used_mb: int | None
    rss_mb: int | None
    temp_c: float | None
    cpu_mhz: int | None


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


def _kb_fields(path: Path, *names: str) -> list[int] | None:
    try:
        fields = _fields(path)
        return [int(fields[n][0]) for n in names]
    except (TypeError, KeyError, IndexError, ValueError):
        return None


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _temp_c(root: Path) -> float | None:
    zones = []
    for zone in sorted(root.glob("class/thermal/thermal_zone*")):
        try:
            kind = (zone / "type").read_text(encoding="utf-8").strip()
        except OSError:
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
        self._prev_cpu = cpu
        mem = _kb_fields(self._proc / "meminfo", "MemTotal", "MemAvailable")
        rss = _kb_fields(self._proc / "self" / "status", "VmRSS")
        return Sample(
            t_ms=round((time.monotonic() - self._start) * 1000),
            cpu_pct=cpu_pct,
            ram_used_mb=None if mem is None else (mem[0] - mem[1]) // 1024,
            rss_mb=None if rss is None else rss[0] // 1024,
            temp_c=_temp_c(self._sys),
            cpu_mhz=_cpu_mhz(self._sys),
        )

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_s):
            self._queue.put(self._take())

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
