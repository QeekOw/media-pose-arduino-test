import pytest

from bench.live import InFlight, Result, Sent


def send(flight, *timestamps):
    for index, ts in enumerate(timestamps):
        flight.sent(Sent(index, ts, capture_ms=float(ts), read_ms=ts + 4.0))


def fates(frames):
    return [(f.index, f.dropped) for f in frames]


def test_a_result_settles_every_earlier_frame_as_dropped_and_its_own_as_processed():
    flight = InFlight()
    send(flight, 100, 133, 166, 200)

    settled = flight.settle([Result(166, result_ms=390.0, landmarks=None)])

    assert fates(settled) == [(0, True), (1, True), (2, False)]
    assert settled[2].delay_ms == pytest.approx(224.0)
    assert settled[2].read_ms == 170.0
    assert len(flight) == 1


def test_results_arriving_together_settle_in_index_order():
    flight = InFlight()
    send(flight, 100, 133, 166, 200, 233)

    settled = flight.settle([Result(100, 300.0, None), Result(200, 500.0, None)])

    assert fates(settled) == [(0, False), (1, True), (2, True), (3, False)]
    assert flight.settle([]) == []


def test_frames_still_waiting_when_the_session_ends_are_dropped():
    flight = InFlight()
    send(flight, 100, 133, 166)
    flight.settle([Result(100, 300.0, None)])

    given_up = flight.give_up()

    assert fates(given_up) == [(1, True), (2, True)]
    assert len(flight) == 0


def test_a_result_for_a_frame_never_sent_fails_loudly():
    flight = InFlight()
    send(flight, 100, 133)

    with pytest.raises(RuntimeError):
        flight.settle([Result(120, 300.0, None)])
