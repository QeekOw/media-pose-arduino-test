import json

import pytest

from bench.analysis import NO_LIVE, analyze, analyze_webcam, main
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
    assert row[-10:-5] == ["-"] * 5
    assert row[-1] == "-"


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


POSE = [[0.5, 0.5, 0.0, 1.0]] * 33


def live_frame(index, capture_ms, result_ms, pose=True, read_ms=None):
    return {"type": "live_frame", "index": index, "capture_ms": capture_ms,
            "read_ms": capture_ms + 5.0 if read_ms is None else read_ms, "result_ms": result_ms,
            "dropped": result_ms is None, "landmarks": POSE if pose and result_ms is not None else None}


def write_live_run(path, frames, status="completed", variant="lite", repeat=1, machine="board", samples=()):
    """frames: (capture_ms, result_ms or None, has_pose) per camera frame, in capture order."""
    lines = [{"type": "header", "format_version": 1, "phase": "webcam", "variant": variant, "clip": "live",
              "repeat": repeat, "started_at": "2026-10-31T12:00:00+00:00", "machine": {"name": machine}}]
    lines += [live_frame(i, capture_ms, result_ms, pose) for i, (capture_ms, result_ms, pose) in enumerate(frames)]
    lines.extend(samples)
    if status is not None:
        lines.append({"type": "status", "status": status, "detail": ""})
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    return path


def test_live_frames_are_read_with_their_fate(tmp_path):
    run = write_live_run(tmp_path / "a.jsonl", [(1000.0, 1200.0, True), (1033.0, None, False), (1066.0, 1250.0, False)])

    parsed = read_run(run)

    assert parsed.problem is None and parsed.frames == []
    assert [(f.index, f.dropped, f.delay_ms) for f in parsed.live_frames] == [
        (0, False, 200.0), (1, True, None), (2, False, 184.0),
    ]
    assert [f.landmarks is not None for f in parsed.live_frames] == [True, False, False]


@pytest.mark.parametrize(
    "bad",
    [
        {"dropped": True},
        {"result_ms": None},
        {"dropped": 0},
        {"result_ms": 899.0},
        {"capture_ms": "1000"},
        {"read_ms": None},
        {"index": 1.0},
    ],
)
def test_a_live_frame_that_contradicts_itself_is_a_corrupt_line(tmp_path, bad):
    run = write_live_run(tmp_path / "a.jsonl", [(900.0, 1100.0, True)] * 2)
    lines = run.read_text(encoding="utf-8").splitlines()
    lines[2] = json.dumps({**json.loads(lines[2]), **bad})
    run.write_text("\n".join(lines) + "\n", encoding="utf-8")

    parsed = read_run(run)

    assert parsed.problem == "corrupt line 3"
    assert len(parsed.live_frames) == 1


def test_a_dropped_frame_with_landmarks_is_a_corrupt_line(tmp_path):
    run = write_live_run(tmp_path / "a.jsonl", [(1000.0, None, False)])
    lines = run.read_text(encoding="utf-8").splitlines()
    lines[1] = json.dumps({**json.loads(lines[1]), "landmarks": POSE})
    run.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert read_run(run).problem == "corrupt line 2"


def test_a_header_with_an_unknown_phase_is_a_corrupt_line(tmp_path):
    run = write_run(tmp_path / "a.jsonl", [100] * 60)
    header, *rest = run.read_text(encoding="utf-8").splitlines()
    run.write_text("\n".join([json.dumps({**json.loads(header), "phase": "live"}), *rest]) + "\n")

    parsed = read_run(run)

    assert parsed.problem == "corrupt line 1"
    assert parsed.header is None


def camera(seconds, fps=30.0, every=6, delay_ms=200.0, start_ms=1_000_000.0, pose=True):
    """A camera at `fps` whose every `every`-th frame got a result `delay_ms` later; the rest were dropped."""
    step = 1000.0 / fps
    return [(start_ms + i * step, start_ms + i * step + delay_ms if i % every == 0 else None, pose)
            for i in range(round(seconds * fps))]


def test_processed_fps_dropped_share_and_delay_are_measured_after_warm_up(tmp_path):
    run = write_live_run(tmp_path / "webcam__lite__live__r1__board.jsonl", camera(65))

    (s,) = analyze_webcam([run])

    assert (s.variant, s.session, s.machine, s.status) == ("lite", 1, "board", "completed")
    assert s.frames == 1950
    assert s.stats.camera_frames == 1800
    assert s.stats.camera_fps == pytest.approx(30.0, rel=1e-3)
    assert s.stats.processed_fps == pytest.approx(5.0, rel=1e-3)
    assert s.stats.dropped_pct == pytest.approx(100 * 5 / 6)
    assert s.stats.delay_avg_ms == pytest.approx(200.0)
    assert s.stats.delay_p95_ms == pytest.approx(200.0)
    assert s.stats.detection_rate == pytest.approx(100.0)


def test_the_first_5_seconds_do_not_affect_results(tmp_path):
    slow_start = [(c, None if r is None else c + 3000.0, p) for c, r, p in camera(5)]
    steady = camera(60, start_ms=1_005_000.0)
    run = write_live_run(tmp_path / "a.jsonl", slow_start + steady)

    (s,) = analyze_webcam([run])

    assert s.stats.delay_avg_ms == pytest.approx(200.0)
    assert s.stats.camera_frames == 1800


def test_delay_p95_and_detection_of_known_values(tmp_path):
    # 100 processed frames with delays 1..100 ms: linear interpolation puts the 95th percentile at 1 + 0.95 * 99.
    frames = [(1_000.0 + i * 100, 1_000.0 + i * 100 + (i - 49), i % 4 == 0) for i in range(50, 150)]
    run = write_live_run(tmp_path / "a.jsonl", [(0.0, None, False)] + frames)

    (s,) = analyze_webcam([run])

    assert s.stats.delay_p95_ms == pytest.approx(95.05)
    assert s.stats.delay_avg_ms == pytest.approx(50.5)
    assert s.stats.detection_rate == pytest.approx(25.0)
    assert s.stats.dropped_pct == pytest.approx(0.0)


def test_a_session_no_longer_than_its_warm_up_has_no_numbers(tmp_path, capsys):
    run = write_live_run(tmp_path / "a.jsonl", camera(5))

    (s,) = analyze_webcam([run])

    assert s.stats is None
    assert main([str(run)]) == 0
    assert "too short (needs more than 5 s)" in capsys.readouterr().out


def test_sessions_pool_by_adding_their_counts(tmp_path):
    write_live_run(tmp_path / "a.jsonl", camera(65, every=6, delay_ms=200.0), repeat=1)
    write_live_run(tmp_path / "b.jsonl", camera(65, every=3, delay_ms=100.0), repeat=2)

    one, two = analyze_webcam([tmp_path])
    pooled = sum((one.stats, two.stats), NO_LIVE)

    assert pooled.processed_fps == pytest.approx(7.5, rel=1e-3)
    assert pooled.dropped_pct == pytest.approx(100 * 3 / 4)
    assert pooled.delay_avg_ms == pytest.approx((300 * 200 + 600 * 100) / 900)
    assert pooled.delay_p95_ms == pytest.approx(200.0)


@pytest.mark.parametrize(
    "frames, flag",
    [
        (camera(65, fps=20.0), "camera below 25 fps"),
        (camera(65, fps=30.0), None),
    ],
)
def test_a_camera_below_25_fps_is_flagged(tmp_path, frames, flag):
    run = write_live_run(tmp_path / "a.jsonl", frames, samples=[sample(0), sample(1000)])

    (s,) = analyze_webcam([run])

    assert s.flags == (() if flag is None else (flag,))


def test_a_read_time_far_from_the_capture_time_flags_the_clock(tmp_path):
    run = write_live_run(tmp_path / "a.jsonl", camera(65), samples=[sample(0), sample(1000)])
    lines = run.read_text(encoding="utf-8").splitlines()
    lines[1000] = json.dumps({**json.loads(lines[1000]), "read_ms": json.loads(lines[1000])["capture_ms"] + 1500})
    run.write_text("\n".join(lines) + "\n", encoding="utf-8")

    (s,) = analyze_webcam([run])

    assert s.flags == ("capture clock off",)


def test_a_session_with_no_frames_is_flagged_and_keeps_its_system_readings(tmp_path):
    run = write_live_run(tmp_path / "a.jsonl", [], status="crashed", samples=[sample(0), sample(1000, rss_mb=350)])

    (s,) = analyze_webcam([run])

    assert s.flags == ("no frames",)
    assert s.status == "crashed"
    assert s.peak_rss_mb == 350


def test_webcam_sessions_never_reach_the_video_phase(tmp_path):
    write_live_run(tmp_path / "webcam__lite__live__r1__board.jsonl", camera(65))
    write_run(tmp_path / "video__lite__front.mp4__r1__board.jsonl", [100] * 60, clip="front.mp4")

    assert [s.clip for s in analyze([tmp_path])] == ["front.mp4"]
    assert [s.session for s in analyze_webcam([tmp_path])] == [1]


def test_a_session_that_died_before_its_header_is_a_failed_webcam_row(tmp_path):
    dead = tmp_path / "webcam__lite__live__r2__board.jsonl"
    dead.write_text(json.dumps({"type": "status", "status": "crashed", "detail": "exit code 1"}) + "\n")

    (s,) = analyze_webcam([tmp_path])

    assert analyze([tmp_path]) == []
    assert (s.variant, s.session, s.machine, s.status) == ("lite", 2, "board", "failed: no header line")


def test_cli_prints_the_webcam_table_after_the_video_table(tmp_path, capsys):
    write_run(tmp_path / "a.jsonl", [100] * 60, clip="front.mp4")
    write_live_run(tmp_path / "b.jsonl", camera(65))

    assert main([str(tmp_path)]) == 0

    video, webcam = capsys.readouterr().out.split("\n\nWebcam phase\n")
    assert "front.mp4" in video
    header, row = webcam.splitlines()
    for column in ("session", "camera FPS", "processed FPS", "dropped %", "delay avg ms", "delay p95 ms"):
        assert column in header
    assert row.split()[:6] == ["lite", "1", "board", "completed", "1950", "1800"]
    assert "5.00" in row.split() and "83.3" in row.split()
