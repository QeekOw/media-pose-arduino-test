import pytest

from bench.live import Gate, Result, Sent


def read(gate, index, ts):
    """What the session does with a frame read at ts: send it when the gate is free, else drop it."""
    if gate.busy:
        gate.drop(index, capture_ms=float(ts), read_ms=ts + 4.0)
    else:
        gate.send(Sent(index, ts, capture_ms=float(ts), read_ms=ts + 4.0))


def fates(frames):
    return [(f.index, f.dropped) for f in frames]


def test_frames_read_while_one_is_in_flight_are_dropped_and_written_after_it_in_index_order():
    gate = Gate()
    for index, ts in enumerate((100, 133, 166, 200)):
        read(gate, index, ts)

    settled = gate.settle([Result(100, result_ms=390.0, landmarks=None)])

    assert fates(settled) == [(0, False), (1, True), (2, True), (3, True)]
    assert settled[0].delay_ms == pytest.approx(290.0)
    assert settled[0].read_ms == 104.0
    assert all(f.result_ms is None and f.landmarks is None for f in settled[1:])


def test_a_result_frees_the_gate_for_the_next_frame_read():
    gate = Gate()
    read(gate, 0, 100)
    read(gate, 1, 133)
    assert gate.settle([]) == []

    gate.settle([Result(100, 300.0, None)])
    assert not gate.busy
    read(gate, 2, 166)
    read(gate, 3, 200)

    assert fates(gate.settle([Result(166, 400.0, None)])) == [(2, False), (3, True)]


def test_the_frame_in_flight_when_the_session_ends_is_dropped_with_those_behind_it():
    gate = Gate()
    read(gate, 0, 100)
    read(gate, 1, 133)
    read(gate, 2, 166)

    assert fates(gate.give_up()) == [(0, True), (1, True), (2, True)]
    assert not gate.busy
    assert gate.give_up() == []


def test_a_result_for_a_frame_not_in_flight_fails_loudly():
    gate = Gate()
    read(gate, 0, 100)
    read(gate, 1, 133)

    with pytest.raises(RuntimeError):
        gate.settle([Result(133, 300.0, None)])
