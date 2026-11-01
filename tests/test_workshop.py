from pathlib import Path

import pytest

from bench.workshop import PROVIDED, find_video, new_demo_recording, safe_name


def test_the_new_demo_recording_is_the_one_folder_that_appeared():
    before = ["/home/arduino/bench/runs-demo/20261031T050614Z/"]
    after = [*before, "/home/arduino/bench/runs-demo/20261101T090000Z/"]

    assert new_demo_recording(before, after) == "/home/arduino/bench/runs-demo/20261101T090000Z"


def test_no_new_folder_fails_loudly():
    before = ["/home/arduino/bench/runs-demo/20261031T050614Z/"]

    with pytest.raises(SystemExit, match="found 0"):
        new_demo_recording(before, before)


def test_a_provided_video_is_found_by_name():
    assert find_video("front") == PROVIDED / "front.mp4"


def test_an_unknown_video_lists_the_provided_ones():
    with pytest.raises(SystemExit, match="front"):
        find_video("no-such-video.mp4")


def test_an_own_video_file_is_found_by_path(tmp_path):
    own = tmp_path / "IMG_1234.MOV"
    own.write_bytes(b"")

    assert find_video(str(own)) == own


def test_a_video_name_is_made_safe_for_the_board():
    assert safe_name(Path("My Dance (final) v2.MOV")) == "my-dance-final-v2"
    assert safe_name(Path("¿?.mp4")) == "video"
