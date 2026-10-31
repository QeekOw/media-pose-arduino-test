import json
import os
import subprocess

import pytest

from bench.analysis import WARMUP_FRAMES, analyze, analyze_webcam
from bench.report import (
    CLIPS,
    NONE_PASSED,
    REPEATS,
    format_verdicts,
    main,
    pooled_pck,
    provenance,
    spread,
    summary_table,
    verdicts,
    webcam_table,
)

POSE = [[0.3 + i * 0.01, 0.2 + i * 0.015, 0.0, 1.0] for i in range(33)]


def write_run(
    dir_, variant="lite", clip="front", repeat=1, machine="board", frame_ms=100.0, frames=100, detected=100,
    status="completed", pose=POSE,
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
                      "landmarks": pose if kept < found else None})
    lines.append({"type": "sample", "t_ms": 0, "cpu_pct": 50.0, "temp_c": 60.0})
    if status is not None:
        lines.append({"type": "status", "status": status, "detail": ""})
    path = dir_ / f"video__{variant}__{clip}__r{repeat}__{machine}.jsonl"
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    return path


def write_campaign(dir_, **run):
    for clip in CLIPS:
        for repeat in range(1, REPEATS + 1):
            write_run(dir_, clip=clip, repeat=repeat, **run)


def write_session(dir_, variant="lite", session=1, machine="board", status="completed", every=6, delay_ms=200.0):
    """A 65 s Webcam phase session from a 30 fps camera: every `every`-th frame got a result `delay_ms` after capture."""
    lines = [{"type": "header", "format_version": 1, "phase": "webcam", "variant": variant, "clip": "live",
              "repeat": session, "started_at": "2026-10-31T14:00:00+00:00", "machine": {"name": machine}}]
    for i in range(65 * 30):
        capture_ms = 1_000_000.0 + i * 1000 / 30
        result_ms = capture_ms + delay_ms if i % every == 0 else None
        lines.append({"type": "live_frame", "index": i, "capture_ms": capture_ms, "read_ms": capture_ms + 5.0,
                      "result_ms": result_ms, "dropped": result_ms is None,
                      "landmarks": POSE if result_ms is not None else None})
    lines.append({"type": "sample", "t_ms": 0, "cpu_pct": 50.0, "temp_c": 60.0})
    if status is not None:
        lines.append({"type": "status", "status": status, "detail": ""})
    path = dir_ / f"webcam__{variant}__live__r{session}__{machine}.jsonl"
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    return path


def verdict_for(tmp_path, **run):
    write_campaign(tmp_path, **run)
    (v,) = verdicts(analyze([tmp_path]))
    return v


def failed_names(v):
    return [r.rule.name for r in v.failed_rules]


def test_a_variant_meeting_every_rule_passes(tmp_path):
    v = verdict_for(tmp_path)

    assert v.passed
    assert format_verdicts([v]).splitlines()[0] == "lite: PASS (15 Runs)"


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
    write_campaign(tmp_path, detected=100)
    write_run(tmp_path, clip="empty", detected=0)

    (v,) = verdicts(analyze([tmp_path]))

    assert v.passed


def test_rules_apply_to_all_runs_of_a_variant_together(tmp_path):
    write_campaign(tmp_path, frame_ms=100.0)
    write_run(tmp_path, clip="front", frame_ms=80.0)
    write_run(tmp_path, clip="side", frame_ms=115.0)

    (v,) = verdicts(analyze([tmp_path]))

    assert v.runs == 15
    assert v.passed


@pytest.mark.parametrize("status", ["crashed", "oom", None])
def test_one_failed_run_fails_its_variant(tmp_path, status):
    write_campaign(tmp_path)
    write_run(tmp_path, repeat=3, status=status)

    (v,) = verdicts(analyze([tmp_path]))

    assert failed_names(v) == ["no failed Runs"]
    assert "fails: no failed Runs (1 failed)" in format_verdicts([v])


def test_every_failed_rule_is_named(tmp_path):
    v = verdict_for(tmp_path, frame_ms=200.0, detected=50, status="crashed")

    text = format_verdicts([v])

    assert text.splitlines()[:5] == [
        "lite: FAIL (15 Runs)",
        "  fails: average FPS at least 10 (5.0 FPS)",
        "  fails: slowest-5% frame time at most 150 ms (200 ms)",
        "  fails: detection at least 90% on Clips with a person (50.0%)",
        "  fails: no failed Runs (15 failed)",
    ]


def test_a_variant_missing_a_campaign_clip_fails(tmp_path):
    for clip in ("front", "side", "fast"):
        for repeat in range(1, REPEATS + 1):
            write_run(tmp_path, clip=clip, repeat=repeat)

    (v,) = verdicts(analyze([tmp_path]))

    assert failed_names(v) == ["3 Runs on each of the five Campaign Clips"]
    assert "fails: 3 Runs on each of the five Campaign Clips (fewest on one Clip: 0)" in format_verdicts([v])


def test_a_variant_short_of_three_repeats_on_one_clip_fails(tmp_path):
    write_campaign(tmp_path)
    (tmp_path / "video__lite__far__r3__board.jsonl").unlink()

    (v,) = verdicts(analyze([tmp_path]))

    assert failed_names(v) == ["3 Runs on each of the five Campaign Clips"]


def test_no_variant_passed_says_webcam_phase_falls_back_to_lite(tmp_path):
    write_campaign(tmp_path, variant="lite", frame_ms=120.0)
    write_campaign(tmp_path, variant="full", frame_ms=200.0)
    write_campaign(tmp_path, variant="heavy", status="oom")

    text = format_verdicts(verdicts(analyze([tmp_path])))

    assert text.endswith('No Model variant passed the Pass criteria, so the Webcam phase falls back to an "as-is" Lite demo.')


def test_variants_without_board_runs_are_named_and_hold_back_the_finding(tmp_path):
    write_run(tmp_path, variant="lite", frame_ms=120.0)

    text = format_verdicts(verdicts(analyze([tmp_path])))

    assert "full: no Board Runs on the Campaign Clips yet" in text
    assert "heavy: no Board Runs on the Campaign Clips yet" in text
    assert NONE_PASSED not in text


def test_message_is_absent_when_one_variant_passes(tmp_path):
    write_campaign(tmp_path, variant="lite", frame_ms=50.0)
    write_campaign(tmp_path, variant="full", frame_ms=200.0)

    text = format_verdicts(verdicts(analyze([tmp_path])))

    assert NONE_PASSED not in text
    assert text.startswith("lite: PASS")


def test_laptop_and_smoke_runs_do_not_count_toward_verdicts(tmp_path):
    write_campaign(tmp_path, frame_ms=50.0)
    write_run(tmp_path, machine="dev", status="crashed")
    write_run(tmp_path, clip="smoke", status="crashed")

    (v,) = verdicts(analyze([tmp_path]))

    assert v.runs == 15
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
    write_campaign(tmp_path, machine="board", frame_ms=100.0)
    write_campaign(tmp_path, machine="dev", frame_ms=20.0)

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
            write_campaign(runs, variant=variant, machine=machine)

    assert main([str(runs), "--out-dir", str(tmp_path / "out")]) == 0

    out = capsys.readouterr().out
    assert "heavy: PASS" in out
    assert "Spread across repeats" in out
    head = subprocess.run(["git", "rev-parse", "--short=7", "HEAD"], capture_output=True, text=True).stdout.strip()
    assert f"Made by commit {head}" in out
    images = sorted(p.name for p in (tmp_path / "out").iterdir())
    assert images == ["accuracy-vs-speed.png", "fps.png", "frame-times.png", "summary-table.png", "temperature.png"]


def test_pooled_pck_weights_each_run_by_the_landmarks_it_was_scored_on(tmp_path):
    write_run(tmp_path, variant="heavy", machine="dev")
    write_run(tmp_path, repeat=1, detected=100)
    write_run(tmp_path, repeat=2, detected=10, pose=[[x + 0.5, y, z, v] for x, y, z, v in POSE])

    board = [s for s in analyze([tmp_path]) if s.machine == "board"]

    assert [s.pck for s in board] == [pytest.approx(100.0), pytest.approx(0.0)]
    assert pooled_pck(board) == pytest.approx(100.0 * 100 / 110)


def test_overlapping_inputs_count_each_run_file_once(tmp_path):
    for clip in CLIPS:
        write_run(tmp_path, clip=clip)

    (v,) = verdicts(analyze([tmp_path, tmp_path, tmp_path / "video__lite__front__r1__board.jsonl"]))

    assert v.runs == 5
    assert failed_names(v) == ["3 Runs on each of the five Campaign Clips"]


def test_a_copied_campaign_directory_counts_each_run_once(tmp_path):
    import shutil

    original = tmp_path / "campaign"
    original.mkdir()
    for clip in CLIPS:
        write_run(original, clip=clip)
    shutil.copytree(original, tmp_path / "backup")

    (v,) = verdicts(analyze([original, tmp_path / "backup"]))

    assert v.runs == 5
    assert failed_names(v) == ["3 Runs on each of the five Campaign Clips"]


def test_a_failed_run_without_a_header_keeps_its_name_when_passed_by_another_path(tmp_path):
    write_campaign(tmp_path)
    failed = tmp_path / "video__lite__front__r4__board.jsonl"
    failed.write_text(json.dumps({"type": "status", "status": "oom"}) + "\n", encoding="utf-8")
    alias = tmp_path.parent / f"{tmp_path.name}-failed-alias.jsonl"
    try:
        alias.symlink_to(failed)
    except OSError:
        pytest.skip("creating symlinks needs extra rights on this machine")

    (v,) = verdicts(analyze([tmp_path, alias]))

    assert failed_names(v) == ["no failed Runs"]


def test_hard_links_do_not_add_repeats(tmp_path):
    for clip in CLIPS:
        run = write_run(tmp_path, clip=clip)
        for n in (2, 3):
            os.link(run, tmp_path / f"copy{n}-{run.name}")

    (v,) = verdicts(analyze([tmp_path]))

    assert v.runs == 5
    assert failed_names(v) == ["3 Runs on each of the five Campaign Clips"]


def test_provenance_names_the_commit_and_the_inputs(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                    "--allow-empty", "-m", "x"], check=True)
    head = subprocess.run(["git", "-C", str(tmp_path), "rev-parse", "--short=7", "HEAD"],
                          capture_output=True, text=True).stdout.strip()

    assert provenance(["runs/board/x", "runs/dev"], repo=tmp_path) == f"Made by commit {head} from runs/board/x, runs/dev"
    (tmp_path / "tracked.txt").write_text("a")
    subprocess.run(["git", "-C", str(tmp_path), "add", "tracked.txt"], check=True)
    assert provenance(["runs/dev"], repo=tmp_path) == f"Made by commit {head} + uncommitted changes from runs/dev"


def test_provenance_outside_git_says_the_commit_is_unknown(tmp_path):
    assert provenance(["runs/dev"], repo=tmp_path) == "Made by an unknown commit from runs/dev"


def webcam_rows(tmp_path):
    return webcam_table(analyze_webcam([tmp_path]), verdicts(analyze([tmp_path])))[1]


@pytest.mark.parametrize(
    ("video", "label"),
    [({"frame_ms": 185.0}, "Lite (as-is)"), ({"frame_ms": 100.0}, "Lite"), (None, "Lite (no verdict)")],
)
def test_a_variant_run_live_is_labelled_by_its_video_phase_verdict(tmp_path, video, label):
    if video is not None:
        write_campaign(tmp_path, **video)
    for session in (1, 2, 3):
        write_session(tmp_path, session=session)

    (row,) = webcam_rows(tmp_path)

    assert row[:2] == [label, "3"]


def test_completed_sessions_are_pooled_and_failed_ones_counted(tmp_path):
    write_session(tmp_path, session=1, every=6, delay_ms=200.0)
    write_session(tmp_path, session=2, every=3, delay_ms=100.0)
    write_session(tmp_path, session=3, every=1, delay_ms=50.0, status="crashed")

    headers, (row,) = webcam_table(analyze_webcam([tmp_path]), [])

    cells = dict(zip(headers, row))
    assert cells["Sessions"] == "2 + 1 failed"
    assert (cells["Camera FPS"], cells["Processed FPS"], cells["Dropped %"]) == ("30.0", "7.5", "75.0")
    assert (cells["Delay avg ms"], cells["Delay p95 ms"], cells["Detect %"]) == ("133", "200", "100.0")


def test_webcam_sessions_never_change_the_verdicts(tmp_path):
    write_campaign(tmp_path)
    write_session(tmp_path, status="crashed")

    (v,) = verdicts(analyze([tmp_path]))

    assert v.passed and v.runs == 15


def test_summary_table_without_board_sessions_is_unchanged(tmp_path):
    write_campaign(tmp_path, frame_ms=185.0)
    write_session(tmp_path, machine="dev")
    summaries = analyze([tmp_path])

    headers, rows = summary_table(summaries, analyze_webcam([tmp_path]))

    assert (headers, rows) == summary_table(summaries)
    assert headers[-1] == "Verdict" and rows[0][0] == "Lite"


def test_summary_table_shows_the_webcam_phase_after_the_verdict(tmp_path):
    write_campaign(tmp_path, frame_ms=185.0)
    for session in (1, 2, 3):
        write_session(tmp_path, session=session)

    headers, (row,) = summary_table(analyze([tmp_path]), analyze_webcam([tmp_path]))

    cells = dict(zip(headers, row))
    assert cells["Variant"] == "Lite (as-is)"
    assert cells["Verdict"] == "FAIL"
    assert (cells["Webcam\nFPS"], cells["Webcam\ndropped %"], cells["Webcam delay ms\navg / p95"]) == (
        "5.0", "83.3", "200 / 200",
    )


def test_main_prints_the_webcam_phase_and_writes_its_charts(tmp_path, capsys):
    runs = tmp_path / "runs"
    runs.mkdir()
    write_campaign(runs, frame_ms=185.0)
    for session in (1, 2, 3):
        write_session(runs, session=session)

    assert main([str(runs), "--out-dir", str(tmp_path / "out")]) == 0

    out = capsys.readouterr().out
    webcam = out.split("\nWebcam phase (")[1].splitlines()
    assert webcam[2].split()[:3] == ["Lite", "(as-is)", "3"]
    images = sorted(p.name for p in (tmp_path / "out").iterdir())
    assert images == ["fps.png", "frame-times.png", "summary-table.png", "temperature.png", "webcam-delay.png",
                      "webcam-fps.png"]


def test_main_reports_webcam_sessions_given_on_their_own(tmp_path, capsys):
    write_session(tmp_path)

    assert main([str(tmp_path), "--out-dir", str(tmp_path / "out")]) == 0

    assert "Lite (no verdict)" in capsys.readouterr().out
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["summary-table.png", "webcam-delay.png",
                                                                    "webcam-fps.png"]
