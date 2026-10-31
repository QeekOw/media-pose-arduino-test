from bench.demo_recording import RecordingWriter, read_recording
from bench.runfile import LiveFrame

POSE = [[0.5, 0.5, 0.0, 0.9]] * 33


def test_each_frame_reads_back_as_the_exact_jpeg_bytes_the_camera_gave(tmp_path):
    jpegs = [b"\xff\xd8first\xff\xd9", b"\xff\xd8second, longer\xff\xd9", b"\xff\xd8third\xff\xd9"]
    with RecordingWriter(tmp_path, {"variant": "lite"}) as rec:
        for i, jpeg in enumerate(jpegs):
            rec.add_jpeg(i, jpeg)
        # Fates arrive out of the order frames were stored, as the gate settles them.
        rec.settle([LiveFrame(0, 0.0, 5.0, 200.0, POSE), LiveFrame(1, 33.0, 38.0, None, None)])
        rec.settle([LiveFrame(2, 66.0, 71.0, None, None)])
        rec.finish("completed", "")

    recording = read_recording(tmp_path)

    assert recording.header["variant"] == "lite"
    assert recording.header["phase"] == "demo"
    assert recording.status == "completed"
    assert [f.index for f in recording.frames] == [0, 1, 2]
    assert recording.frames[0].landmarks == POSE
    assert recording.frames[1].dropped
    assert [recording.jpeg(f.index) for f in recording.frames] == jpegs


def test_a_recording_cut_off_before_its_status_line_still_reads(tmp_path):
    rec = RecordingWriter(tmp_path, {"variant": "lite"})
    rec.add_jpeg(0, b"\xff\xd8only\xff\xd9")
    rec.settle([LiveFrame(0, 0.0, 5.0, 200.0, POSE)])
    rec.close()

    recording = read_recording(tmp_path)

    assert recording.status is None
    assert recording.jpeg(0) == b"\xff\xd8only\xff\xd9"


def test_a_half_written_last_line_is_ignored(tmp_path):
    with RecordingWriter(tmp_path, {"variant": "lite"}) as rec:
        rec.add_jpeg(0, b"\xff\xd8only\xff\xd9")
        rec.settle([LiveFrame(0, 0.0, 5.0, 200.0, POSE)])
    with (tmp_path / "demo.jsonl").open("a", encoding="utf-8") as f:
        f.write('{"type": "live_frame", "index": 1, "capt')

    assert [f.index for f in read_recording(tmp_path).frames] == [0]
