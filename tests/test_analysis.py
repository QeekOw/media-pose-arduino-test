import json

import pytest

from bench.analysis import analyze, main
from bench.runfile import read_run


def sample(t_ms=0, cpu_pct=50.0, ram_used_mb=1000, rss_mb=200, rss_peak_mb=None, temp_c=60.0, cpu_mhz=2016):
    return {"type": "sample", "t_ms": t_ms, "cpu_pct": cpu_pct, "ram_used_mb": ram_used_mb, "rss_mb": rss_mb,
            "rss_peak_mb": rss_peak_mb, "temp_c": temp_c, "cpu_mhz": cpu_mhz}


def write_run(
    path, frame_ms, status="completed", variant="lite", clip="smoke.mp4", repeat=1, machine="board", samples=()
):
    header = {
        "type": "header",
        "format_version": 1,
        "phase": "video",
        "variant": variant,
        "clip": clip,
        "repeat": repeat,
        "started_at": "2026-10-23T12:00:00+00:00",
        "machine": {"name": machine},
    }
    lines = [header]
    for i, ms in enumerate(frame_ms):
        lines.append({"type": "frame", "index": i, "video_ms": ms / 4, "model_ms": ms * 3 / 4, "landmarks": None})
    lines.extend(samples)
    if status is not None:
        lines.append({"type": "status", "status": status, "detail": ""})
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    return path


def test_constant_100ms_frames_give_10_fps(tmp_path):
    run = write_run(tmp_path / "a.jsonl", [100] * 130)

    (s,) = analyze([run])

    assert s.fps == pytest.approx(10.0)
    assert s.avg_ms == pytest.approx(100.0)
    assert s.p95_ms == pytest.approx(100.0)
    assert s.frames == 130
    assert s.kept_frames == 100
    assert s.status == "completed"


def test_first_30_frames_do_not_affect_results(tmp_path):
    run = write_run(tmp_path / "a.jsonl", [10_000] * 30 + [100] * 70)

    (s,) = analyze([run])

    assert s.fps == pytest.approx(10.0)
    assert s.avg_ms == pytest.approx(100.0)
    assert s.p95_ms == pytest.approx(100.0)
    assert s.kept_frames == 70


def test_p95_of_known_distribution(tmp_path):
    # Kept frames are 1..100 ms: linear interpolation puts the 95th percentile at 1 + 0.95 * 99.
    run = write_run(tmp_path / "a.jsonl", [5] * 30 + list(range(1, 101)))

    (s,) = analyze([run])

    assert s.p95_ms == pytest.approx(95.05)
    assert s.avg_ms == pytest.approx(50.5)
    assert s.fps == pytest.approx(100 / 5.05)


def test_missing_status_line_is_reported_as_failed(tmp_path):
    run = write_run(tmp_path / "a.jsonl", [100] * 60, status=None)

    (s,) = analyze([run])

    assert s.status == "failed: no status line"
    assert s.fps == pytest.approx(10.0)


def test_crashed_status_is_reported(tmp_path):
    run = write_run(tmp_path / "a.jsonl", [100] * 60, status="oom")

    (s,) = analyze([run])

    assert s.status == "oom"


def test_truncated_last_line_is_tolerated(tmp_path):
    run = write_run(tmp_path / "a.jsonl", [100] * 60, status=None)
    with run.open("a", encoding="utf-8") as f:
        f.write('{"type": "frame", "index": 60, "video_ms": 25.0, "mod')

    (s,) = analyze([run])

    assert s.frames == 60
    assert s.status == "failed: no status line"
    assert s.fps == pytest.approx(10.0)


def test_unknown_line_types_are_ignored(tmp_path):
    run = write_run(tmp_path / "a.jsonl", [100] * 60)
    with run.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "sample", "t_ms": 1000, "cpu_pct": 87.0}) + "\n")

    (s,) = analyze([run])

    assert s.frames == 60
    assert s.status == "completed"


def test_fewer_than_31_frames_reports_no_numbers(tmp_path, capsys):
    run = write_run(tmp_path / "a.jsonl", [100] * 30)

    (s,) = analyze([run])
    assert s.fps is None
    assert s.avg_ms is None
    assert s.p95_ms is None
    assert s.frames == 30
    assert s.kept_frames == 0

    assert main([str(run)]) == 0
    assert "too few frames" in capsys.readouterr().out


def test_31_frames_is_enough_for_numbers(tmp_path):
    run = write_run(tmp_path / "a.jsonl", [100] * 31)

    (s,) = analyze([run])

    assert s.kept_frames == 1
    assert s.fps == pytest.approx(10.0)


def test_cli_over_directory_prints_a_row_per_run(tmp_path, capsys):
    write_run(tmp_path / "a.jsonl", [100] * 130, variant="lite", clip="front.mp4", repeat=1, machine="board")
    write_run(tmp_path / "b.jsonl", [50] * 130, variant="heavy", clip="side.mp4", repeat=2, machine="dev")
    write_run(tmp_path / "c.jsonl", [200] * 130, variant="full", clip="far.mp4", repeat=3, status=None)
    (tmp_path / "notes.txt").write_text("not a run file")

    assert main([str(tmp_path)]) == 0

    out = capsys.readouterr().out.splitlines()
    header, *rows = out
    for column in ("variant", "clip", "repeat", "machine", "status", "frames", "FPS", "avg ms", "p95 ms"):
        assert column in header
    assert len(rows) == 3
    by_clip = {clip: next(r.split() for r in rows if clip in r) for clip in ("front.mp4", "side.mp4", "far.mp4")}
    assert by_clip["front.mp4"][:5] == ["lite", "front.mp4", "1", "board", "completed"]
    assert "10.00" in by_clip["front.mp4"]
    assert by_clip["side.mp4"][:5] == ["heavy", "side.mp4", "2", "dev", "completed"]
    assert "20.00" in by_clip["side.mp4"]
    assert "failed:" in " ".join(by_clip["far.mp4"])
    assert "5.00" in by_clip["far.mp4"]


def test_cli_accepts_mixed_files_and_directories(tmp_path, capsys):
    sub = tmp_path / "runs"
    sub.mkdir()
    write_run(sub / "a.jsonl", [100] * 60, clip="one.mp4")
    loose = write_run(tmp_path / "b.jsonl", [100] * 60, clip="two.mp4")

    assert main([str(sub), str(loose)]) == 0

    out = capsys.readouterr().out
    assert "one.mp4" in out
    assert "two.mp4" in out


def test_empty_run_file_is_a_failed_row_and_other_runs_still_appear(tmp_path, capsys):
    write_run(tmp_path / "video__lite__ok.mp4__r1__board.jsonl", [100] * 60, clip="ok.mp4")
    (tmp_path / "video__heavy__dead.mp4__r2__dev.jsonl").write_text("", encoding="utf-8")

    assert main([str(tmp_path)]) == 0

    out = capsys.readouterr().out
    assert "ok.mp4" in out
    dead = next(line for line in out.splitlines() if "dead.mp4" in line)
    assert "failed: no header line" in dead


def test_empty_run_file_recovers_identity_from_its_name(tmp_path):
    empty = tmp_path / "video__full__side view.mp4__r3__dev.jsonl"
    empty.write_text("", encoding="utf-8")

    (s,) = analyze([empty])

    assert (s.variant, s.clip, s.repeat, s.machine) == ("full", "side view.mp4", 3, "dev")
    assert s.status == "failed: no header line"
    assert s.frames == 0
    assert s.fps is None


def test_unrecognised_file_name_falls_back_to_placeholders(tmp_path):
    empty = tmp_path / "notes.jsonl"
    empty.write_text("", encoding="utf-8")

    (s,) = analyze([empty])

    assert (s.variant, s.clip, s.repeat, s.machine) == ("?", "notes", 0, "?")
    assert s.status == "failed: no header line"


def test_corrupt_middle_line_fails_the_run_even_with_a_later_completed_status(tmp_path):
    run = write_run(tmp_path / "a.jsonl", [100] * 60)
    lines = run.read_text(encoding="utf-8").splitlines()
    lines[5] = '{"type": "frame", "index": 4, "vid'
    run.write_text("\n".join(lines) + "\n", encoding="utf-8")

    (s,) = analyze([run])

    assert s.status == "failed: corrupt line 6"
    assert s.frames == 4
    assert (s.variant, s.clip, s.repeat, s.machine) == ("lite", "smoke.mp4", 1, "board")


def test_corrupt_middle_line_does_not_stop_other_runs(tmp_path, capsys):
    bad = write_run(tmp_path / "a.jsonl", [100] * 60, clip="bad.mp4")
    lines = bad.read_text(encoding="utf-8").splitlines()
    lines[2] = "not json"
    bad.write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_run(tmp_path / "b.jsonl", [100] * 60, clip="good.mp4")

    assert main([str(tmp_path)]) == 0

    out = capsys.readouterr().out
    assert "failed: corrupt line 3" in out
    assert "good.mp4" in out


def test_clean_run_file_has_no_problem(tmp_path):
    run = write_run(tmp_path / "a.jsonl", [100] * 60)

    parsed = read_run(run)

    assert parsed.problem is None
    assert parsed.header is not None
    assert parsed.status == "completed"


def test_truncated_last_line_is_not_a_problem(tmp_path):
    run = write_run(tmp_path / "a.jsonl", [100] * 60, status=None)
    with run.open("a", encoding="utf-8") as f:
        f.write('{"type": "frame", "index": 60, "vid')

    parsed = read_run(run)

    assert parsed.problem is None
    assert parsed.status is None
    assert len(parsed.frames) == 60


def test_killed_run_with_samples_but_no_status_is_failed(tmp_path):
    run = write_run(tmp_path / "a.jsonl", [100] * 60, status=None, samples=[sample(0), sample(1000)])

    (s,) = analyze([run])

    assert s.status == "failed: no status line"
    assert s.peak_rss_mb == 200


def test_system_readings_are_summarised_per_run(tmp_path):
    samples = [
        sample(0, cpu_pct=None, ram_used_mb=900, rss_mb=150, temp_c=55.0, cpu_mhz=2016),
        sample(1000, cpu_pct=80.0, ram_used_mb=1200, rss_mb=310, temp_c=71.5, cpu_mhz=1500),
        sample(2000, cpu_pct=90.0, ram_used_mb=1100, rss_mb=300, temp_c=None, cpu_mhz=None),
        sample(3000, cpu_pct=100.0, ram_used_mb=None, rss_mb=None, temp_c=68.0, cpu_mhz=1800),
    ]
    run = write_run(tmp_path / "a.jsonl", [100] * 60, samples=samples)

    (s,) = analyze([run])

    assert s.peak_rss_mb == 310
    assert s.peak_ram_used_mb == 1200
    assert s.avg_cpu_pct == pytest.approx(90.0)
    assert s.max_temp_c == pytest.approx(71.5)
    assert s.min_cpu_mhz == 1500
    assert s.flags == ()


def test_missing_readings_are_not_flagged_and_show_as_dashes(tmp_path, capsys):
    blank = sample(0, cpu_pct=None, ram_used_mb=None, rss_mb=None, temp_c=None, cpu_mhz=None)
    run = write_run(tmp_path / "a.jsonl", [100] * 60, samples=[blank])

    (s,) = analyze([run])
    assert (s.peak_rss_mb, s.peak_ram_used_mb, s.avg_cpu_pct, s.max_temp_c, s.min_cpu_mhz) == (None,) * 5
    assert s.flags == ()

    assert main([str(run)]) == 0
    row = capsys.readouterr().out.splitlines()[1].split()
    assert row[-6:] == ["-"] * 6


@pytest.mark.parametrize(
    "frames, samples, flag",
    [
        ([], [sample()], "no frames"),
        ([100] * 60, [], "no samples"),
        ([100] * 60, [sample(temp_c=0.0)], "temp 0 or out of range"),
        ([100] * 60, [sample(temp_c=130.0)], "temp 0 or out of range"),
        ([100] * 60, [sample(cpu_mhz=0)], "clock 0"),
        ([100] * 60, [sample(ram_used_mb=0)], "ram 0"),
        ([100] * 60, [sample(rss_mb=0)], "ram 0"),
        ([100] * 60, [sample(rss_peak_mb=0)], "ram 0"),
        ([100] * 60, [sample(cpu_pct=-1.0)], "cpu % out of range"),
        ([100] * 60, [sample(cpu_pct=100.5)], "cpu % out of range"),
    ],
)
def test_implausible_readings_are_flagged(tmp_path, capsys, frames, samples, flag):
    run = write_run(tmp_path / "a.jsonl", frames, samples=[sample(), *samples, sample()] if samples else [])

    (s,) = analyze([run])

    assert s.flags == (flag,)
    assert main([str(run)]) == 0
    assert flag in capsys.readouterr().out


def test_clean_run_has_no_flags(tmp_path, capsys):
    run = write_run(tmp_path / "a.jsonl", [100] * 60, samples=[sample(0), sample(1000, temp_c=125.0, cpu_pct=100.0)])

    (s,) = analyze([run])

    assert s.flags == ()
    assert main([str(run)]) == 0
    assert capsys.readouterr().out.splitlines()[1].endswith(" -")


def test_avg_cpu_weights_each_reading_by_the_time_it_covers(tmp_path):
    # The 10 ms reading from stop() barely moves the average: (1000 * 100 + 10 * 0) / 1010.
    samples = [sample(0, cpu_pct=None), sample(1000, cpu_pct=100.0), sample(1010, cpu_pct=0.0)]
    run = write_run(tmp_path / "a.jsonl", [100] * 60, samples=samples)

    (s,) = analyze([run])

    assert s.avg_cpu_pct == pytest.approx(99.00990099)


def test_avg_cpu_is_none_when_no_reading_covers_any_time(tmp_path):
    run = write_run(tmp_path / "a.jsonl", [100] * 60, samples=[sample(0), sample(0)])

    (s,) = analyze([run])

    assert s.avg_cpu_pct is None


def test_peak_rss_uses_the_high_water_mark_over_polled_rss(tmp_path):
    samples = [sample(0, rss_mb=200, rss_peak_mb=210), sample(1000, rss_mb=300, rss_peak_mb=450)]
    run = write_run(tmp_path / "a.jsonl", [100] * 60, samples=samples)

    (s,) = analyze([run])

    assert s.peak_rss_mb == 450


@pytest.mark.parametrize(
    "bad",
    [
        sample(1000, cpu_pct="bad"),
        sample(1000, ram_used_mb="1000"),
        sample(1000, temp_c=True),
        sample(1000, rss_peak_mb=[450]),
        sample(t_ms=1.5),
        sample(t_ms=None),
    ],
)
def test_sample_with_a_non_number_value_fails_only_its_run(tmp_path, capsys, bad):
    write_run(tmp_path / "a.jsonl", [100] * 60, clip="bad.mp4", samples=[sample(0), bad, sample(2000)])
    write_run(tmp_path / "b.jsonl", [100] * 60, clip="good.mp4", samples=[sample(0), sample(1000)])

    assert main([str(tmp_path)]) == 0

    rows = capsys.readouterr().out.splitlines()
    # Header, 60 frames and one good sample come first, so the bad sample is line 63.
    assert "failed: corrupt line 63" in next(r for r in rows if "bad.mp4" in r)
    assert "completed" in next(r for r in rows if "good.mp4" in r)
    assert len(read_run(tmp_path / "a.jsonl").frames) == 60


def test_header_sample_interval_is_optional(tmp_path):
    old = write_run(tmp_path / "old.jsonl", [100] * 60)
    new = write_run(tmp_path / "new.jsonl", [100] * 60)
    header, *rest = new.read_text(encoding="utf-8").splitlines()
    new.write_text("\n".join([json.dumps({**json.loads(header), "sample_interval_s": 0.5}), *rest]) + "\n")

    assert read_run(old).header.sample_interval_s is None
    assert read_run(new).header.sample_interval_s == 0.5
