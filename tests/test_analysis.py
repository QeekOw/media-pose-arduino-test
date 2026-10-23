import json

import pytest

from bench.analysis import analyze, main
from bench.runfile import read_run


def write_run(path, frame_ms, status="completed", variant="lite", clip="smoke.mp4", repeat=1, machine="board"):
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
