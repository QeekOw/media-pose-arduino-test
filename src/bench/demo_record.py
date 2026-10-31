"""Make one Demo recording on the Board: the camera's frames plus the pose results, for a Demo video.

    python -m bench.demo_record --variant lite --seconds 30 | ffplay -f mjpeg -i -

A Demo recording is never a Session: it is not measured and never goes to Analysis (see GLOSSARY.md). It runs the
Webcam phase's camera and one-frame-in-flight gate (ADR 0006), but opens the camera raw. Each JPEG the camera sends
is saved as is, and only the frames sent to MediaPipe are decoded.

While it runs, every third JPEG goes to stdout as a preview stream: for --lead-in seconds before recording starts,
so the tester can get into frame, then for the whole recording. Messages go to stderr so they never mix with it.
"""
import argparse
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty, Full, Queue, SimpleQueue

import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

from bench.demo_recording import RecordingWriter
from bench.live import DRAIN_S, CameraError, Gate, Result, Sent, open_camera
from bench.models import VARIANTS, ensure_model
from bench.run_one import _landmarks, _sample_interval


def say(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


class Preview:
    """Sends JPEGs to stdout on its own thread, so a slow link drops preview frames instead of stalling the camera."""

    def __init__(self, every: int) -> None:
        self.every = every
        self._queue: Queue[bytes] = Queue(maxsize=2)
        self._out = sys.stdout.buffer
        threading.Thread(target=self._run, daemon=True).start()

    def offer(self, count: int, jpeg: bytes) -> None:
        if count % self.every == 0:
            try:
                self._queue.put_nowait(jpeg)
            except Full:
                pass

    def _run(self) -> None:
        try:
            while True:
                self._out.write(self._queue.get())
                self._out.flush()
        except (BrokenPipeError, OSError):
            say("preview closed; recording carries on")


def record(variant: str, seconds: float, lead_in: float, out_root: Path, models_dir: Path, preview_every: int) -> Path:
    model = ensure_model(variant, models_dir)
    out_dir = out_root / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    try:
        camera = open_camera(raw=True)
    except CameraError as e:
        raise SystemExit(str(e))
    preview = Preview(preview_every) if preview_every > 0 else None
    results: SimpleQueue[Result] = SimpleQueue()

    def on_result(result, image, timestamp_ms: int) -> None:
        results.put(Result(timestamp_ms, time.monotonic() * 1000, _landmarks(result)))

    with RecordingWriter(out_dir, {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "variant": variant,
        "seconds": seconds,
        "model": {"file": model.path.name, "size_bytes": model.size_bytes, "sha256": model.sha256},
        "clip_info": camera.size,
        "camera": camera.settings,
    }) as rec:
        gate = Gate()

        def write_settled(*extra) -> None:
            arrived = []
            while True:
                try:
                    arrived.append(results.get_nowait())
                except Empty:
                    break
            rec.settle([*gate.settle(arrived), *extra])

        status, detail = "crashed", "interrupted"
        try:
            options = vision.PoseLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=str(model.path)),
                running_mode=vision.RunningMode.LIVE_STREAM,
                num_poses=1,
                result_callback=on_result,
            )
            with vision.PoseLandmarker.create_from_options(options) as landmarker:
                count, index, timestamp_ms, start_ms, end_ms = 0, 0, -1, None, None
                say(f"preview for {lead_in:g} s: get into frame")
                while True:
                    frame = camera.read()
                    if frame is None:
                        raise CameraError(f"camera stopped after {count} frames")
                    capture_ms, read_ms, raw = frame
                    jpeg = raw.tobytes()
                    if preview:
                        preview.offer(count, jpeg)
                    count += 1
                    if start_ms is None:
                        start_ms = capture_ms + lead_in * 1000
                    if capture_ms < start_ms:
                        continue
                    if end_ms is None:
                        end_ms = capture_ms + seconds * 1000
                        say(f"recording {seconds:g} s")
                    if capture_ms >= end_ms:
                        break
                    rec.add_jpeg(index, jpeg)
                    write_settled()
                    if gate.busy:
                        gate.drop(index, capture_ms, read_ms)
                    else:
                        timestamp_ms = max(int(capture_ms), timestamp_ms + 1)
                        gate.send(Sent(index, timestamp_ms, capture_ms, read_ms))
                        rgb = cv2.cvtColor(cv2.imdecode(raw, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
                        landmarker.detect_async(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), timestamp_ms)
                    index += 1
                drain_until = time.monotonic() + DRAIN_S
                while gate.busy and time.monotonic() < drain_until:
                    time.sleep(0.01)
                    write_settled()
                write_settled(*gate.give_up())
            status, detail = "completed", ""
        except CameraError as e:
            status, detail = "crashed", str(e)
        except Exception as e:
            status, detail = "crashed", repr(e)
        finally:
            camera.close()
            rec.finish(status, detail)
    say(f"{status} {detail}".strip())
    say(f"saved {out_dir}")
    return out_dir


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--variant", default="lite", choices=VARIANTS)
    p.add_argument("--seconds", type=_sample_interval, default=30.0, help="length of the recording")
    p.add_argument("--lead-in", type=float, default=10.0, help="seconds of preview before recording starts")
    p.add_argument("--out-dir", type=Path, default=Path("runs-demo"))
    p.add_argument("--models-dir", type=Path, default=Path("models"))
    p.add_argument("--preview-every", type=int, default=3, help="send every Nth frame to stdout as a preview")
    p.add_argument("--no-preview", action="store_true")
    a = p.parse_args()
    record(a.variant, a.seconds, a.lead_in, a.out_dir, a.models_dir, 0 if a.no_preview else a.preview_every)


if __name__ == "__main__":
    main()
