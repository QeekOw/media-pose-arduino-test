import itertools
import json
from pathlib import Path

import pytest

from bench.campaign import (
    CampaignConfig,
    Cooldown,
    ProcessResult,
    RunSpec,
    measure_baseline,
    plan,
    run_campaign,
    settle_run_file,
    wait_until_cool,
)
from bench.runfile import read_run, run_file_name


class FakeTime:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def temps(*readings):
    """A temperature reader that returns the readings in order, then repeats the last one."""
    it = iter(readings)
    last = [None]

    def read():
        last[0] = next(it, last[0])
        return last[0]

    return read


def test_plan_runs_every_combination_exactly_once():
    specs = plan(["lite", "full", "heavy"], ["a.mp4", "b.mp4"], 3, seed=1)

    expected = {RunSpec(v, c, r) for v, c, r in itertools.product(["lite", "full", "heavy"], ["a.mp4", "b.mp4"], [1, 2, 3])}
    assert len(specs) == 18
    assert set(specs) == expected


def test_plan_is_reproducible_from_the_seed_and_differs_between_seeds():
    args = (["lite", "full", "heavy"], ["a.mp4", "b.mp4", "c.mp4"], 3)

    assert plan(*args, seed=7) == plan(*args, seed=7)
    assert plan(*args, seed=7) != plan(*args, seed=8)
    assert plan(*args, seed=7) != sorted(plan(*args, seed=7), key=lambda s: (s.variant, s.clip, s.repeat))


def test_plan_ignores_the_order_the_inputs_are_listed_in():
    assert plan(["lite", "full"], ["b.mp4", "a.mp4"], 2, seed=3) == plan(["full", "lite"], ["a.mp4", "b.mp4"], 2, seed=3)


def test_baseline_is_the_median_reading_one_per_second():
    time_ = FakeTime()

    baseline = measure_baseline(temps(40.0, 41.0, 90.0, 40.5), seconds=4, sleep=time_.sleep)

    assert baseline == pytest.approx(40.75)
    assert time_.sleeps == [1.0] * 4


def test_baseline_without_a_sensor_is_none_and_does_not_wait():
    time_ = FakeTime()

    assert measure_baseline(lambda: None, seconds=30, sleep=time_.sleep) is None
    assert time_.sleeps == []


def test_no_wait_when_the_board_is_already_cool():
    time_ = FakeTime()

    cooldown = wait_until_cool(temps(41.0), target_c=42.0, timeout_s=600, sleep=time_.sleep, clock=time_.clock)

    assert cooldown == Cooldown(temp_before_c=41.0, temp_at_start_c=41.0, waited_s=0.0, timed_out=False)
    assert time_.sleeps == []


def test_waits_polling_until_the_board_cools_to_the_target():
    time_ = FakeTime()

    cooldown = wait_until_cool(
        temps(60.0, 55.0, 48.0, 41.5), target_c=42.0, timeout_s=600, poll_s=5, sleep=time_.sleep, clock=time_.clock
    )

    assert cooldown == Cooldown(temp_before_c=60.0, temp_at_start_c=41.5, waited_s=15.0, timed_out=False)
    assert time_.sleeps == [5, 5, 5]


def test_gives_up_at_the_timeout_and_says_so():
    time_ = FakeTime()

    cooldown = wait_until_cool(temps(60.0), target_c=42.0, timeout_s=12, poll_s=5, sleep=time_.sleep, clock=time_.clock)

    assert cooldown == Cooldown(temp_before_c=60.0, temp_at_start_c=60.0, waited_s=12.0, timed_out=True)
    assert time_.sleeps == [5, 5, 2]


def test_a_missing_reading_while_waiting_is_not_treated_as_cool():
    time_ = FakeTime()

    cooldown = wait_until_cool(
        temps(60.0, None, 41.0), target_c=42.0, timeout_s=600, poll_s=5, sleep=time_.sleep, clock=time_.clock
    )

    assert (cooldown.waited_s, cooldown.temp_at_start_c, cooldown.timed_out) == (10.0, 41.0, False)


@pytest.mark.parametrize("target_c, reading", [(None, 55.0), (42.0, None)])
def test_unreadable_temperature_skips_the_wait_and_records_why(target_c, reading):
    time_ = FakeTime()

    cooldown = wait_until_cool(lambda: reading, target_c, timeout_s=600, sleep=time_.sleep, clock=time_.clock)

    assert cooldown.skipped == "temperature unavailable"
    assert (cooldown.waited_s, cooldown.timed_out) == (0.0, False)
    assert time_.sleeps == []


HEADER = {
    "type": "header", "format_version": 1, "phase": "video", "variant": "lite", "clip": "a.mp4", "repeat": 1,
    "started_at": "2026-10-24T12:00:00+00:00",
}
FRAME = {"type": "frame", "index": 0, "video_ms": 1.0, "model_ms": 2.0, "landmarks": None}


def write_lines(path, *records, tail=""):
    path.write_text("".join(json.dumps(r) + "\n" for r in records) + tail)


def last_record(path):
    return json.loads(path.read_text().splitlines()[-1])


def test_a_run_killed_by_sigkill_is_recorded_as_oom_and_keeps_its_frames(tmp_path):
    path = tmp_path / "run.jsonl"
    write_lines(path, HEADER, FRAME, tail='{"type": "frame", "ind')

    status, detail = settle_run_file(path, ProcessResult(-9, "Killed", False), run_timeout_s=60)

    assert status == "oom"
    assert "-9" in detail and "Killed" in detail
    assert last_record(path) == {"type": "status", "status": "oom", "detail": detail}
    run = read_run(path)
    assert (run.status, run.problem, len(run.frames)) == ("oom", None, 1)


def test_a_run_that_exited_before_creating_its_file_gets_a_crashed_file(tmp_path):
    path = tmp_path / "video__lite__a__r1__dev.jsonl"

    status, detail = settle_run_file(path, ProcessResult(1, "cannot open clip a.mp4\n", False), run_timeout_s=60)

    assert (status, detail) == ("crashed", "exit code 1: cannot open clip a.mp4")
    assert read_run(path).status == "crashed"


def test_a_run_that_hung_is_recorded_as_crashed_with_the_timeout(tmp_path):
    path = tmp_path / "run.jsonl"
    write_lines(path, HEADER)

    status, detail = settle_run_file(path, ProcessResult(None, "", True), run_timeout_s=5)

    assert (status, detail) == ("crashed", "timed out after 5 s")


def test_a_run_that_wrote_its_own_status_is_left_alone(tmp_path):
    path = tmp_path / "run.jsonl"
    write_lines(path, HEADER, FRAME, {"type": "status", "status": "crashed", "detail": "ValueError('x')"})
    before = path.read_bytes()

    status, detail = settle_run_file(path, ProcessResult(1, "traceback", False), run_timeout_s=60)

    assert (status, detail) == ("crashed", "ValueError('x')")
    assert path.read_bytes() == before


class FakeBoard:
    """Stands in for `python -m bench.run_one`: writes the Run file the way each scripted behaviour would."""

    def __init__(self, behaviours=None):
        self.behaviours = behaviours or {}
        self.calls = []
        self.seen_logs = []

    def __call__(self, cmd, timeout_s):
        args = dict(zip(cmd[3::2], cmd[4::2]))
        variant, clip, repeat = args["--variant"], Path(args["--clip"]).name, int(args["--repeat"])
        self.calls.append((variant, clip, repeat))
        out_dir = Path(args["--out-dir"])
        self.seen_logs.append(json.loads((out_dir / "campaign.json").read_text()))
        path = out_dir / run_file_name(variant, Path(clip).stem, repeat, args["--machine"])
        behaviour = self.behaviours.get((variant, clip, repeat), "completed")
        header = {**HEADER, "variant": variant, "clip": clip, "repeat": repeat}
        if behaviour == "completed":
            write_lines(path, header, FRAME, {"type": "status", "status": "completed", "detail": ""})
            return ProcessResult(0, "", False)
        if behaviour == "killed":
            write_lines(path, header, FRAME)
            return ProcessResult(-9, "", False)
        return ProcessResult(1, "boom", False)


def make_config(tmp_path, **overrides):
    values = dict(
        campaign_id="c1", seed=5, variants=("lite", "full"), clips=("a.mp4", "b.mp4"), repeats=2,
        clips_dir=tmp_path / "clips", out_dir=tmp_path / "out", machine="board", cooldown_tolerance_c=2.0,
        cooldown_timeout_s=600.0, baseline_seconds=3, sample_interval_s=1.0, run_timeout_s=60.0,
    )
    return CampaignConfig(**{**values, **overrides})


def run(tmp_path, board, config=None, read_temp=lambda: None):
    time_ = FakeTime()
    lines = []
    log = run_campaign(
        config or make_config(tmp_path), read_temp=read_temp, sleep=time_.sleep, clock=time_.clock,
        now=lambda: "2026-10-24T12:00:00+00:00", run_process=board, say=lines.append,
    )
    return log, lines


def planned():
    return plan(["lite", "full"], ["a.mp4", "b.mp4"], 2, seed=5)


def test_campaign_runs_the_planned_order_and_writes_every_run_file_into_its_own_directory(tmp_path):
    board = FakeBoard()

    log, _ = run(tmp_path, board)

    order = [(s.variant, s.clip, s.repeat) for s in planned()]
    assert board.calls == order
    assert [(r["variant"], r["clip"], r["repeat"]) for r in log["runs"]] == order
    files = sorted(p.name for p in (tmp_path / "out" / "c1").glob("*.jsonl"))
    assert files == sorted(r["file"] for r in log["runs"]) and len(files) == 8
    assert log["seed"] == 5 and log["machine"] == "board"


def test_campaign_json_is_readable_after_every_run_and_finished_only_at_the_end(tmp_path):
    board = FakeBoard()

    log, _ = run(tmp_path, board)

    assert [len(seen["runs"]) for seen in board.seen_logs] == list(range(8))
    assert all(seen["finished_at"] is None for seen in board.seen_logs)
    on_disk = json.loads((tmp_path / "out" / "c1" / "campaign.json").read_text())
    assert on_disk["finished_at"] == "2026-10-24T12:00:00+00:00"
    assert on_disk == json.loads(json.dumps(log, default=str))
    assert on_disk["totals"]["status_counts"] == {"completed": 8}


def test_a_failing_run_does_not_stop_the_campaign(tmp_path):
    victim = planned()[2]
    board = FakeBoard({(victim.variant, victim.clip, victim.repeat): "killed"})

    log, _ = run(tmp_path, board)

    assert len(board.calls) == 8
    failed = log["runs"][2]
    assert (failed["status"], failed["returncode"]) == ("oom", -9)
    assert last_record(tmp_path / "out" / "c1" / failed["file"])["status"] == "oom"
    assert log["totals"]["status_counts"] == {"completed": 7, "oom": 1}


def test_a_run_that_leaves_no_file_still_gets_a_failed_run_file(tmp_path):
    victim = planned()[0]
    board = FakeBoard({(victim.variant, victim.clip, victim.repeat): "exit"})

    log, _ = run(tmp_path, board)

    first = log["runs"][0]
    assert (first["status"], first["detail"]) == ("crashed", "exit code 1: boom")
    assert read_run(tmp_path / "out" / "c1" / first["file"]).status == "crashed"


def test_each_run_is_preceded_by_a_cooldown_that_is_logged(tmp_path):
    board = FakeBoard()
    readings = iter([40.0] * 3 + [50.0, 45.0, 41.0] + [40.0] * 100)

    log, lines = run(tmp_path, board, read_temp=lambda: next(readings))

    assert log["baseline_c"] == 40.0 and log["target_c"] == 42.0
    first, second = log["runs"][:2]
    assert first["cooldown"] == {
        "temp_before_c": 50.0, "temp_at_start_c": 41.0, "waited_s": 10.0, "timed_out": False, "skipped": None,
    }
    assert second["cooldown"]["waited_s"] == 0.0
    assert log["totals"]["total_cooldown_s"] == 10.0
    assert "cooled 50.0 -> 41.0 C in 10 s" in lines[2]


def test_a_cooldown_timeout_is_recorded_and_the_run_still_starts(tmp_path):
    board = FakeBoard()
    config = make_config(tmp_path, variants=("lite",), clips=("a.mp4",), repeats=1, cooldown_timeout_s=10)
    readings = iter([40.0] * 3 + [70.0] * 100)

    log, lines = run(tmp_path, board, config, read_temp=lambda: next(readings))

    (only,) = log["runs"]
    assert only["cooldown"]["timed_out"] is True and only["status"] == "completed"
    assert log["totals"]["cooldown_timeouts"] == 1
    assert "TIMED OUT" in lines[-2]


def test_without_a_temperature_sensor_runs_start_at_once_and_say_so(tmp_path):
    board = FakeBoard()

    log, _ = run(tmp_path, board)

    assert log["baseline_c"] is None and log["target_c"] is None
    assert {r["cooldown"]["skipped"] for r in log["runs"]} == {"temperature unavailable"}
    assert log["totals"]["total_cooldown_s"] == 0
