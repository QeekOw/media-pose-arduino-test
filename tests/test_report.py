import json

import pytest

from bench.analysis import WARMUP_FRAMES, analyze
from bench.report import NONE_PASSED, format_verdicts, main, spread, summary_table, verdicts

POSE = [[0.3 + i * 0.01, 0.2 + i * 0.015, 0.0, 1.0] for i in range(33)]


def write_run(
    dir_, variant="lite", clip="front", repeat=1, machine="board", frame_ms=100.0, frames=100, detected=100,
    status="completed",
):
    """A Run whose kept frames (after warm-up) all take frame_ms, and the first `detected` percent of them have a pose."""
    lines = [{"type": "header", "format_version": 1, "phase": "video", "variant": variant, "clip": f"{clip}.mp4",
              "repeat": repeat, "started_at": "2026-10-31T12:00:00+00:00", "machine": {"name": machine},
              "clip_info": {"width": 640, "height": 360}}]
    found = round(frames * detected / 100)
    for i in range(WARMUP_FRAMES + frames):
        kept = i - WARMUP_FRAMES
        ms = frame_ms[kept] if isinstance(frame_ms, list) and kept >= 0 else frame_ms if kept >= 0 else 500.0
        lines.append({"type": "frame", "index": i, "video_ms": 0.0, "model_ms": ms,
                      "landmarks": POSE if kept < found else None})
    lines.append({"type": "sample", "t_ms": 0, "cpu_pct": 50.0, "temp_c": 60.0})
    if status is not None:
        lines.append({"type": "status", "status": status, "detail": ""})
    path = dir_ / f"video__{variant}__{clip}__r{repeat}__{machine}.jsonl"
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    return path


def verdict_for(tmp_path, **run):
    write_run(tmp_path, **run)
    (v,) = verdicts(analyze([tmp_path]))
    return v


def failed_names(v):
    return [r.rule.name for r in v.failed_rules]


def test_a_variant_meeting_every_rule_passes(tmp_path):
    v = verdict_for(tmp_path)

    assert v.passed
    assert format_verdicts([v]).splitlines()[0] == "lite: PASS (1 Run)"


@pytest.mark.parametrize(("frame_ms", "passed"), [(100.0, True), (100.5, False)])
def test_average_fps_passes_at_10_and_fails_below(tmp_path, frame_ms, passed):
    v = verdict_for(tmp_path, frame_ms=frame_ms)

    assert v.passed is passed
    assert failed_names(v) == ([] if passed else ["average FPS at least 10"])


@pytest.mark.parametrize(("slow_ms", "passed"), [(150.0, True), (151.0, False)])
def test_slowest_5_percent_passes_at_150_ms_and_fails_above(tmp_path, slow_ms, passed):
    v = verdict_for(tmp_path, frame_ms=[50.0] * 90 + [slow_ms] * 10)

    assert failed_names(v) == ([] if passed else ["slowest-5% frame time at most 150 ms"])


@pytest.mark.parametrize(("detected", "passed"), [(90, True), (89, False)])
def test_detection_passes_at_90_percent_and_fails_below(tmp_path, detected, passed):
    v = verdict_for(tmp_path, detected=detected)

    assert failed_names(v) == ([] if passed else ["detection at least 90% on Clips with a person"])


def test_empty_room_clip_does_not_count_against_detection(tmp_path):
    write_run(tmp_path, clip="front", detected=100)
    write_run(tmp_path, clip="empty", detected=0)

    (v,) = verdicts(analyze([tmp_path]))

    assert v.passed


def test_rules_apply_to_all_runs_of_a_variant_together(tmp_path):
    write_run(tmp_path, clip="front", repeat=1, frame_ms=80.0)
    write_run(tmp_path, clip="side", repeat=1, frame_ms=115.0)

    (v,) = verdicts(analyze([tmp_path]))

    assert v.runs == 2
    assert v.passed


@pytest.mark.parametrize("status", ["crashed", "oom", None])
def test_one_failed_run_fails_its_variant(tmp_path, status):
    write_run(tmp_path, repeat=1)
    write_run(tmp_path, repeat=2)
    write_run(tmp_path, repeat=3, status=status)

    (v,) = verdicts(analyze([tmp_path]))

    assert failed_names(v) == ["no failed Runs"]
    assert "fails: no failed Runs (1 failed)" in format_verdicts([v])


def test_every_failed_rule_is_named(tmp_path):
    v = verdict_for(tmp_path, frame_ms=200.0, detected=50, status="crashed")

    text = format_verdicts([v])

    assert text.splitlines()[:5] == [
        "lite: FAIL (1 Run)",
        "  fails: average FPS at least 10 (5.0 FPS)",
        "  fails: slowest-5% frame time at most 150 ms (200 ms)",
        "  fails: detection at least 90% on Clips with a person (50.0%)",
        "  fails: no failed Runs (1 failed)",
    ]


def test_no_variant_passed_says_webcam_phase_falls_back_to_lite(tmp_path):
    write_run(tmp_path, variant="lite", frame_ms=120.0)
    write_run(tmp_path, variant="full", frame_ms=200.0)
    write_run(tmp_path, variant="heavy", status="oom")

    text = format_verdicts(verdicts(analyze([tmp_path])))

    assert text.endswith('No Model variant passed the Pass criteria, so the Webcam phase falls back to an "as-is" Lite demo.')


def test_variants_without_board_runs_are_named_and_hold_back_the_finding(tmp_path):
    write_run(tmp_path, variant="lite", frame_ms=120.0)

    text = format_verdicts(verdicts(analyze([tmp_path])))

    assert "full: no Board Runs on the Campaign Clips yet" in text
    assert "heavy: no Board Runs on the Campaign Clips yet" in text
    assert NONE_PASSED not in text


def test_message_is_absent_when_one_variant_passes(tmp_path):
    write_run(tmp_path, variant="lite", frame_ms=50.0)
    write_run(tmp_path, variant="full", frame_ms=200.0)

    text = format_verdicts(verdicts(analyze([tmp_path])))

    assert NONE_PASSED not in text
    assert text.startswith("lite: PASS")


def test_laptop_and_smoke_runs_do_not_count_toward_verdicts(tmp_path):
    write_run(tmp_path, frame_ms=50.0)
    write_run(tmp_path, machine="dev", status="crashed")
    write_run(tmp_path, clip="smoke", status="crashed")

    (v,) = verdicts(analyze([tmp_path]))

    assert v.runs == 1
    assert v.passed


def test_spread_leaves_out_runs_off_the_campaign_clips(tmp_path):
    write_run(tmp_path, clip="smoke")

    assert spread(analyze([tmp_path])) == []


def test_spread_reports_fps_range_across_repeats(tmp_path):
    for repeat, ms in enumerate([100.0, 125.0, 80.0], start=1):
        write_run(tmp_path, repeat=repeat, frame_ms=ms)

    (s,) = spread(analyze([tmp_path]))

    assert (s.variant, s.clip, s.machine, s.repeats) == ("lite", "front", "board", 3)
    assert (s.fps_min, s.fps_max) == (pytest.approx(8.0), pytest.approx(12.5))
    assert s.fps_mean == pytest.approx(30.5 / 3)
    assert s.fps_spread_pct == pytest.approx(100 * 4.5 / (30.5 / 3))
    assert (s.p95_min, s.p95_max) == (pytest.approx(80.0), pytest.approx(125.0))


def test_summary_table_puts_board_and_laptop_side_by_side(tmp_path):
    write_run(tmp_path, machine="board", frame_ms=100.0)
    write_run(tmp_path, machine="dev", frame_ms=20.0)

    headers, rows = summary_table(analyze([tmp_path]))

    row = dict(zip(headers, rows[0]))
    assert row["Variant"] == "Lite"
    assert (row["FPS\nBoard"], row["FPS\nLaptop"]) == ("10.0", "50.0")
    assert row["Verdict"] == "PASS"


def test_main_prints_verdicts_and_writes_charts(tmp_path, capsys):
    runs = tmp_path / "runs"
    runs.mkdir()
    for machine in ("board", "dev"):
        for variant in ("lite", "heavy"):
            write_run(runs, variant=variant, machine=machine)

    assert main([str(runs), "--out-dir", str(tmp_path / "out")]) == 0

    out = capsys.readouterr().out
    assert "heavy: PASS" in out
    assert "Spread across repeats" in out
    images = sorted(p.name for p in (tmp_path / "out").iterdir())
    assert images == ["accuracy-vs-speed.png", "fps.png", "frame-times.png", "summary-table.png", "temperature.png"]
