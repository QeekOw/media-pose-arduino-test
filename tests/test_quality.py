import json

import pytest

from bench.analysis import WARMUP_FRAMES, analyze, main

WIDTH, HEIGHT = 2000, 1000
TORSO = 0.2 * HEIGHT


def pose(dx=0.0, dy=0.0):
    """33 landmarks that stand 0.2 of the frame height (200 px) apart between the shoulders and the hips."""
    points = [[0.5, 0.5, 0.0, 1.0] for _ in range(33)]
    for i in (11, 12):
        points[i][1] = 0.3
    return [[x + dx, y + dy, z, v] for x, y, z, v in points]


def write_run(path, poses, variant="heavy", clip="front.mp4", repeat=1, machine="dev", status="completed"):
    header = {
        "type": "header",
        "format_version": 1,
        "phase": "video",
        "variant": variant,
        "clip": clip,
        "repeat": repeat,
        "started_at": "2026-10-23T12:00:00+00:00",
        "machine": {"name": machine},
        "clip_info": {"width": WIDTH, "height": HEIGHT, "fps": 30.0, "frame_count": len(poses)},
    }
    lines = [header]
    for i, landmarks in enumerate(poses):
        lines.append({"type": "frame", "index": i, "video_ms": 10, "model_ms": 90, "landmarks": landmarks})
    lines.append({"type": "status", "status": status, "detail": ""})
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    return path


def summaries_by_variant(*paths):
    return {(s.variant, s.machine): s for s in analyze(list(paths))}


def pck_of(tmp_path, run_poses, ref_poses=None, clip="front.mp4"):
    ref_poses = ref_poses or [pose()] * len(run_poses)
    ref = write_run(tmp_path / "ref.jsonl", ref_poses, clip=clip)
    run = write_run(tmp_path / "run.jsonl", run_poses, variant="lite", machine="board", clip=clip)
    return summaries_by_variant(ref, run)["lite", "board"].pck


def test_heavy_on_the_dev_machine_scores_100_against_itself(tmp_path):
    ref = write_run(tmp_path / "ref.jsonl", [pose(0.01 * (i % 5)) for i in range(60)])

    (s,) = analyze([ref])

    assert s.pck == 100.0


def test_landmarks_30_percent_of_torso_away_are_not_correct(tmp_path):
    off = [pose(dy=0.3 * TORSO / HEIGHT)] * 60

    assert pck_of(tmp_path, off) == 0.0


def test_landmarks_10_percent_of_torso_away_are_correct(tmp_path):
    near = [pose(dy=0.1 * TORSO / HEIGHT)] * 60

    assert pck_of(tmp_path, near) == 100.0


def test_distance_is_measured_in_pixels_not_normalised_units(tmp_path):
    # 0.03 across a 2000 px wide frame is 60 px = 30% of the 200 px torso, though only 15% of 0.2 normalised.
    off = [pose(dx=0.03)] * 60

    assert pck_of(tmp_path, off) == 0.0


def test_pck_is_the_share_of_landmarks_within_range(tmp_path):
    far = 0.3 * TORSO / HEIGHT
    one_in_three = pose()
    for i in range(11):
        one_in_three[i][1] += far

    assert pck_of(tmp_path, [one_in_three] * 60) == pytest.approx(100 * 22 / 33)


def test_pck_counts_only_frames_where_both_found_a_pose(tmp_path):
    ref = [pose()] * 50 + [None] * 10
    run = [pose()] * 40 + [None] * 10 + [pose(dy=0.5)] * 10

    assert pck_of(tmp_path, run, ref) == 100.0


def test_pck_ignores_the_warmup_frames(tmp_path):
    run = [pose(dy=0.5)] * WARMUP_FRAMES + [pose()] * 30

    assert pck_of(tmp_path, run) == 100.0


def test_pck_is_none_without_reference_landmarks_for_the_clip(tmp_path):
    ref = write_run(tmp_path / "ref.jsonl", [pose()] * 60, clip="side.mp4")
    run = write_run(tmp_path / "run.jsonl", [pose()] * 60, variant="lite", machine="board", clip="front.mp4")

    assert summaries_by_variant(ref, run)["lite", "board"].pck is None


@pytest.mark.parametrize(
    "variant, machine, status",
    [("full", "dev", "completed"), ("heavy", "board", "completed"), ("heavy", "dev", "crashed")],
)
def test_only_a_completed_heavy_run_on_the_dev_machine_is_a_reference(tmp_path, variant, machine, status):
    not_a_reference = write_run(tmp_path / "ref.jsonl", [pose()] * 60, variant=variant, machine=machine, status=status)
    run = write_run(tmp_path / "run.jsonl", [pose()] * 60, variant="lite", machine="board")

    assert summaries_by_variant(not_a_reference, run)["lite", "board"].pck is None


def test_detection_rate_is_the_share_of_frames_with_a_pose_on_a_clip_with_a_person(tmp_path):
    run = write_run(tmp_path / "run.jsonl", [None] * WARMUP_FRAMES + [pose()] * 45 + [None] * 5, clip="side.mp4")

    (s,) = analyze([run])

    assert s.detection_rate == pytest.approx(90.0)
    assert s.false_detection_rate is None


def test_detections_on_the_empty_room_clip_are_false_detections_not_detection_rate(tmp_path):
    run = write_run(tmp_path / "run.jsonl", [None] * 30 + [pose()] * 5 + [None] * 45, clip="empty.mp4")

    (s,) = analyze([run])

    assert s.false_detection_rate == pytest.approx(10.0)
    assert s.detection_rate is None


def test_a_clean_empty_room_run_has_no_false_detections(tmp_path):
    run = write_run(tmp_path / "run.jsonl", [None] * 60, clip="empty.mp4")

    (s,) = analyze([run])

    assert s.false_detection_rate == 0.0


def test_jitter_is_movement_between_frames_in_torso_lengths(tmp_path):
    # Each frame moves every landmark 0.02 of the 2000 px width = 40 px = 0.2 torso lengths.
    run = write_run(tmp_path / "run.jsonl", [pose(dx=0.02 * i) for i in range(60)], clip="front.mp4")

    (s,) = analyze([run])

    assert s.jitter == pytest.approx(0.2)


def test_a_still_pose_has_no_jitter(tmp_path):
    run = write_run(tmp_path / "run.jsonl", [pose()] * 60, clip="front.mp4")

    (s,) = analyze([run])

    assert s.jitter == 0.0


def test_jitter_skips_movement_across_frames_without_a_pose(tmp_path):
    poses = [pose()] * 40 + [None] + [pose(dx=0.5)] * 19
    run = write_run(tmp_path / "run.jsonl", poses, clip="front.mp4")

    (s,) = analyze([run])

    assert s.jitter == 0.0


def test_jitter_is_only_reported_on_the_front_view_clip(tmp_path):
    run = write_run(tmp_path / "run.jsonl", [pose(dx=0.02 * i) for i in range(60)], clip="side.mp4")

    (s,) = analyze([run])

    assert s.jitter is None


def test_a_run_with_the_wrong_number_of_landmarks_fails_only_its_run(tmp_path, capsys):
    bad = write_run(tmp_path / "video__lite__side__r1__board.jsonl", [pose()[:5]] * 40, clip="side.mp4")
    good = write_run(tmp_path / "video__lite__side__r2__board.jsonl", [pose()] * 40, clip="side.mp4")

    assert main([str(bad), str(good)]) == 0

    out = capsys.readouterr().out
    assert "failed: corrupt line 2" in out
    assert "completed" in out


def test_the_table_shows_quality_columns(tmp_path, capsys):
    ref = write_run(tmp_path / "ref.jsonl", [pose()] * 60)

    assert main([str(ref)]) == 0

    header, row = capsys.readouterr().out.splitlines()
    assert "PCK@0.2 %" in header
    assert "100.0" in row.split()
