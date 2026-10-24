import itertools

import pytest

from bench.campaign import Cooldown, RunSpec, measure_baseline, plan, wait_until_cool


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
