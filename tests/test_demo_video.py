from bench.demo_video import face_boxes, live_view, window
from bench.runfile import LiveFrame

POSE_A = [[0.1, 0.1, 0.0, 1.0]] * 33
POSE_B = [[0.2, 0.2, 0.0, 1.0]] * 33


def frame(index, capture_ms, result_ms=None, landmarks=None):
    return LiveFrame(index, capture_ms, capture_ms + 5.0, result_ms, landmarks)


def test_each_frame_shows_the_latest_result_that_had_arrived_when_it_was_read():
    frames = [
        frame(0, 0.0, result_ms=200.0, landmarks=POSE_A),
        frame(1, 33.0),
        frame(2, 66.0),
        frame(3, 200.0),  # read at 205, after frame 0's result arrived at 200
        frame(4, 233.0, result_ms=450.0, landmarks=POSE_B),
        frame(5, 266.0),
        frame(6, 450.0),  # read at 455, after frame 4's result
    ]

    shown = live_view(frames)

    assert shown == [None, None, None, POSE_A, POSE_A, POSE_A, POSE_B]


def test_a_result_with_no_pose_clears_the_skeleton():
    frames = [
        frame(0, 0.0, result_ms=100.0, landmarks=POSE_A),
        frame(1, 150.0, result_ms=300.0, landmarks=None),
        frame(2, 400.0),
    ]

    assert live_view(frames) == [None, POSE_A, None]


def face_pose(dx=0.0):
    """A pose whose face landmarks (0-10) span x 0.4-0.5 and y 0.2-0.25; the body sits far below."""
    face = [[0.4 + dx, 0.2, 0.0, 1.0], [0.5 + dx, 0.25, 0.0, 1.0]] + [[0.45 + dx, 0.22, 0.0, 1.0]] * 9
    return face + [[0.45 + dx, 0.9, 0.0, 1.0]] * 22


# On a 1000x1000 frame face_pose() spans 100 x 50 px around (450, 225). Its box is 3 x 100 px square, centred a
# quarter of that span lower to cover the chin and the hair.
BOX = (300, 100, 600, 400)


def test_a_frame_with_a_pose_blurs_a_padded_box_around_the_face():
    frames = [frame(0, 0.0, result_ms=200.0, landmarks=face_pose())]

    assert face_boxes(frames, 1000, 1000) == [BOX]


def test_between_two_poses_the_box_moves_with_the_face():
    frames = [
        frame(0, 0.0, result_ms=200.0, landmarks=face_pose()),
        frame(1, 100.0),
        frame(2, 200.0, result_ms=400.0, landmarks=face_pose(dx=0.1)),
    ]

    boxes = face_boxes(frames, 1000, 1000)

    assert boxes[1] == (350, 100, 650, 400)
    assert boxes[2] == (400, 100, 700, 400)


def test_a_pose_on_only_one_side_within_half_a_second_still_places_the_box():
    frames = [
        frame(0, 0.0, result_ms=200.0, landmarks=face_pose()),
        frame(1, 400.0),
        frame(2, 1200.0, result_ms=1400.0, landmarks=face_pose(dx=0.1)),
    ]

    assert face_boxes(frames, 1000, 1000)[1] == BOX


def test_a_frame_with_no_pose_within_half_a_second_is_blurred_whole():
    frames = [
        frame(0, 0.0, result_ms=200.0, landmarks=face_pose()),
        frame(1, 600.0),
        frame(2, 700.0, result_ms=900.0, landmarks=None),  # no pose found, so it places nothing
        frame(3, 1300.0, result_ms=1500.0, landmarks=face_pose()),
    ]

    assert face_boxes(frames, 1000, 1000) == [BOX, None, None, BOX]


def test_the_box_is_clipped_to_the_frame():
    frames = [frame(0, 0.0, result_ms=200.0, landmarks=face_pose(dx=-0.4))]

    assert face_boxes(frames, 1000, 1000) == [(0, 100, 200, 400)]


def test_the_window_keeps_frames_from_start_for_length_seconds_counted_from_the_first_frame():
    times_ms = [1000.0 + 250.0 * i for i in range(12)]  # 0 s, 0.25 s ... 2.75 s after the first frame

    assert window(times_ms, start_s=1.0, length_s=1.0) == range(4, 8)


def test_a_window_running_past_the_last_frame_stops_there():
    times_ms = [250.0 * i for i in range(6)]

    assert window(times_ms, start_s=0.5, length_s=15.0) == range(2, 6)
