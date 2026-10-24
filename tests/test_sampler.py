import math
import time

import pytest

from bench.sampler import Sampler, read_temp_c


def write_tree(root, stat="cpu  100 0 100 700 100 0 0 0 50 0\ncpu0 50 0 50 350 50 0 0 0 25 0\n", zones=None):
    proc = root / "proc"
    (proc / "self").mkdir(parents=True, exist_ok=True)
    (proc / "stat").write_text(stat)
    (proc / "meminfo").write_text("MemTotal:        3755008 kB\nMemFree:          500000 kB\nMemAvailable:    2730008 kB\n")
    (proc / "self" / "status").write_text("Name:\tpython\nVmPeak:\t  300000 kB\nVmHWM:\t  460800 kB\nVmRSS:\t  204800 kB\n")
    sys = root / "sys"
    if zones is None:
        zones = [("cpuss0-thermal", 61500), ("cpuss1-thermal", 63200), ("battery", 90000)]
    for i, (kind, millideg) in enumerate(zones):
        zone = sys / "class" / "thermal" / f"thermal_zone{i}"
        zone.mkdir(parents=True)
        (zone / "type").write_text(kind + "\n")
        (zone / "temp").write_text(f"{millideg}\n")
    for core, khz in [("cpu0", 2016000), ("cpu1", 1100000)]:
        freq = sys / "devices" / "system" / "cpu" / core / "cpufreq"
        freq.mkdir(parents=True)
        (freq / "scaling_cur_freq").write_text(f"{khz}\n")
    (sys / "devices" / "system" / "cpu" / "cpu2").mkdir()
    return proc, sys


def test_reads_board_style_files(tmp_path):
    proc, sys = write_tree(tmp_path)
    sampler = Sampler(interval_s=60, proc_root=proc, sys_root=sys)

    sampler.start()
    # Busy 200 -> 400 and total 1000 -> 1500 (guest columns excluded): 200 of 500 is 40 %.
    (proc / "stat").write_text("cpu  250 0 150 950 150 0 0 0 80 0\n")
    sampler.stop()
    first, last = sampler.drain()

    assert first.t_ms <= last.t_ms
    assert first.cpu_pct is None
    assert last.cpu_pct == pytest.approx(40.0)
    for s in (first, last):
        assert s.ram_used_mb == 1000
        assert s.rss_mb == 200
        assert s.rss_peak_mb == 450
        assert s.temp_c == pytest.approx(63.2)
        assert s.cpu_mhz == 2016


def test_temp_falls_back_to_all_zones_when_none_is_a_cpu(tmp_path):
    proc, sys = write_tree(tmp_path, zones=[("soc-thermal", 55000), ("gpu-thermal", 58500)])
    sampler = Sampler(interval_s=60, proc_root=proc, sys_root=sys)

    sampler.start()
    sampler.stop()

    assert [s.temp_c for s in sampler.drain()] == [pytest.approx(58.5)] * 2


def test_missing_files_give_none_without_raising(tmp_path):
    sampler = Sampler(interval_s=60, proc_root=tmp_path / "no-proc", sys_root=tmp_path / "no-sys")

    sampler.start()
    sampler.stop()
    samples = sampler.drain()

    assert len(samples) == 2
    for s in samples:
        assert (s.cpu_pct, s.ram_used_mb, s.rss_mb, s.rss_peak_mb, s.temp_c, s.cpu_mhz) == (None,) * 6


def test_samples_at_the_interval_while_running(tmp_path):
    proc, sys = write_tree(tmp_path)
    sampler = Sampler(interval_s=0.01, proc_root=proc, sys_root=sys)

    sampler.start()
    time.sleep(0.2)
    sampler.stop()
    samples = sampler.drain()

    assert len(samples) > 3
    assert [s.t_ms for s in samples] == sorted(s.t_ms for s in samples)
    assert sampler.drain() == []


def test_undecodable_zone_type_still_gives_a_sample(tmp_path):
    proc, sys = write_tree(tmp_path, zones=[("cpuss0-thermal", 61500)])
    (sys / "class" / "thermal" / "thermal_zone0" / "type").write_bytes(b"\xff\xfe\n")
    sampler = Sampler(interval_s=60, proc_root=proc, sys_root=sys)

    sampler.start()
    sampler.stop()

    assert [s.temp_c for s in sampler.drain()] == [pytest.approx(61.5)] * 2


@pytest.mark.parametrize("interval_s", [0, -1.0, math.inf, math.nan])
def test_rejects_an_interval_that_is_not_finite_and_positive(interval_s):
    with pytest.raises(ValueError):
        Sampler(interval_s=interval_s)


def test_read_temp_c_is_the_hottest_cpu_zone_or_none(tmp_path):
    _, sys = write_tree(tmp_path)

    assert read_temp_c(sys) == pytest.approx(63.2)
    assert read_temp_c(tmp_path / "no-sys") is None
