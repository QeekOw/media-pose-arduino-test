"""Run one Model variant live against the webcam for one Webcam phase session and write one Run file.

    python -m bench.live --variant lite --repeat 1 --seconds 60

Every frame the camera delivers goes to MediaPipe in LIVE_STREAM mode, and MediaPipe skips the frames it is too
busy for. The result callback runs on a MediaPipe thread and only queues. This (main) thread works out each
frame's fate and stays the Run file's only writer.
"""
import argparse
import glob
import json
import subprocess
import time
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty, SimpleQueue

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

from bench.envinfo import default_machine_name, machine_info, software_info
from bench.models import VARIANTS, ensure_model
from bench.run_one import _landmarks, _sample_interval
from bench.runfile import LIVE, WEBCAM, LiveFrame, live_frame_record, run_file_name
from bench.sampler import Sampler

BRIO = "/dev/v4l/by-id/usb-046d_Brio_105_*-video-index0"
WIDTH, HEIGHT, FPS, FOURCC = 1280, 720, 30, "MJPG"
CLOCK_TOLERANCE_MS = 1000.0
DRAIN_S = 1.0


class CameraError(Exception):
    """The camera is missing, refused the format, or cannot be configured."""


@dataclass
class Camera:
    """The Brio, opened by USB identity: 1280x720 MJPG at 30 fps with exposure_dynamic_framerate off.

    settings is the header's `camera` block and size its `clip_info`.
    """

    cap: cv2.VideoCapture
    settings: dict
    size: dict

    def read(self) -> tuple[float, float, np.ndarray] | None:
        """(capture_ms, read_ms, RGB frame) on the monotonic clock, or None when the camera stopped delivering."""
        ok, bgr = self.cap.read()
        if not ok:
            return None
        read_ms = time.monotonic() * 1000
        capture_ms = self.cap.get(cv2.CAP_PROP_POS_MSEC) if self.settings["capture_clock"] == "driver" else read_ms
        return capture_ms, read_ms, cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

    def close(self) -> None:
        self.cap.release()


def _v4l2_ctl(device: str, *args: str) -> str:
    try:
        done = subprocess.run(["v4l2-ctl", "-d", device, *args], capture_output=True, text=True, timeout=10, check=True)
    except subprocess.CalledProcessError as e:
        raise CameraError(f"v4l2-ctl {' '.join(args)} failed on {device}: {e.stderr.strip()}") from e
    except (OSError, subprocess.TimeoutExpired) as e:
        raise CameraError(f"v4l2-ctl {' '.join(args)} failed on {device}: {e}") from e
    return done.stdout


def _fourcc(cap: cv2.VideoCapture) -> str:
    code = int(cap.get(cv2.CAP_PROP_FOURCC))
    return "".join(chr((code >> shift) & 0xFF) for shift in (0, 8, 16, 24))


def open_camera(pattern: str = BRIO) -> Camera:
    """Find, configure and check the camera. Raises CameraError naming what is wrong."""
    devices = sorted(glob.glob(pattern))
    if len(devices) != 1:
        raise CameraError(f"expected one camera matching {pattern}, found {len(devices)}")
    device = devices[0]
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not cap.isOpened():
        raise CameraError(f"cannot open {device}")
    try:
        # The V4L2 backend negotiates the size against the current pixel format, so MJPG has to be set first.
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*FOURCC))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
        cap.set(cv2.CAP_PROP_FPS, FPS)
        # On by default, it lets the camera slow to about 20 fps in dim light to lengthen exposure.
        _v4l2_ctl(device, "--set-ctrl=exposure_dynamic_framerate=0")
        got = _v4l2_ctl(device, "--get-ctrl=exposure_dynamic_framerate").strip()
        if got.rsplit(":", 1)[-1].strip() != "0":
            raise CameraError(f"exposure_dynamic_framerate did not switch off on {device}: {got!r}")
        ok, bgr = cap.read()
        now_ms = time.monotonic() * 1000
        if not ok:
            raise CameraError(f"{device} gave no frame")
        driver_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
        fourcc, fps = _fourcc(cap), cap.get(cv2.CAP_PROP_FPS)
        height, width = bgr.shape[:2]
        if (width, height, fourcc, round(fps)) != (WIDTH, HEIGHT, FOURCC, FPS):
            raise CameraError(f"{device} gave {width}x{height} {fourcc} at {fps:g} fps, not {WIDTH}x{HEIGHT} {FOURCC} at {FPS}")
    except BaseException:
        cap.release()
        raise
    # uvcvideo stamps buffers on CLOCK_MONOTONIC, the clock behind time.monotonic(). If this driver does not, the
    # session falls back to the time read() returned, and the header records which clock capture_ms is on.
    clock = "driver" if 0 <= now_ms - driver_ms < CLOCK_TOLERANCE_MS else "read"
    return Camera(
        cap,
        settings={"device": device, "fourcc": fourcc, "exposure_dynamic_framerate": 0, "capture_clock": clock},
        size={"width": width, "height": height, "fps": fps},
    )


@dataclass(frozen=True)
class Sent:
    index: int
    timestamp_ms: int
    capture_ms: float
    read_ms: float


@dataclass(frozen=True)
class Result:
    timestamp_ms: int
    result_ms: float
    landmarks: list[list[float]] | None


class InFlight:
    """Frames handed to MediaPipe whose fate is not known yet. Main thread only.

    MediaPipe returns results in timestamp order and never calls back for a frame it skipped. So a result for
    timestamp T settles every frame sent before T as dropped and the frame sent at T as processed.
    """

    def __init__(self) -> None:
        self._waiting: deque[Sent] = deque()

    def __len__(self) -> int:
        return len(self._waiting)

    def sent(self, frame: Sent) -> None:
        self._waiting.append(frame)

    def _resolve(self, result: Result | None) -> LiveFrame:
        f = self._waiting.popleft()
        if result is None:
            return LiveFrame(f.index, f.capture_ms, f.read_ms, None, None)
        return LiveFrame(f.index, f.capture_ms, f.read_ms, result.result_ms, result.landmarks)

    def settle(self, results: list[Result]) -> list[LiveFrame]:
        """The frames these results decide, in index order."""
        settled = []
        for r in results:
            while self._waiting and self._waiting[0].timestamp_ms < r.timestamp_ms:
                settled.append(self._resolve(None))
            if not self._waiting or self._waiting[0].timestamp_ms != r.timestamp_ms:
                raise RuntimeError(f"result for timestamp {r.timestamp_ms} matches no frame waiting for one")
            settled.append(self._resolve(r))
        return settled

    def give_up(self) -> list[LiveFrame]:
        """Every frame still waiting is dropped: its result never came."""
        return [self._resolve(None) for _ in range(len(self._waiting))]


def run_live(
    variant: str, repeat: int, machine: str, out_dir: Path, models_dir: Path, sample_interval: float, seconds: float
) -> Path:
    model = ensure_model(variant, models_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / run_file_name(variant, LIVE, repeat, machine, WEBCAM)
    try:
        camera = open_camera()
    except CameraError as e:
        raise SystemExit(str(e))

    with out_path.open("w", encoding="utf-8") as f:
        def write(obj: dict) -> None:
            f.write(json.dumps(obj) + "\n")
            f.flush()

        def write_samples() -> None:
            for sample in sampler.drain():
                write({"type": "sample", **asdict(sample)})

        def write_settled(*extra: LiveFrame) -> None:
            arrived = []
            while True:
                try:
                    arrived.append(results.get_nowait())
                except Empty:
                    break
            for frame in [*flight.settle(arrived), *extra]:
                write(live_frame_record(frame))

        write({
            "type": "header",
            "format_version": 1,
            "phase": WEBCAM,
            "variant": variant,
            "clip": LIVE,
            "repeat": repeat,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "sample_interval_s": sample_interval,
            "session_s": seconds,
            "machine": machine_info(machine, out_dir),
            "software": software_info(),
            "model": {"file": model.path.name, "size_bytes": model.size_bytes, "sha256": model.sha256},
            "clip_info": camera.size,
            "camera": camera.settings,
        })
        # The sampler and MediaPipe threads only queue; this thread stays the Run file's only writer.
        sampler = Sampler(sample_interval)
        sampler.start()
        write_samples()
        results: SimpleQueue[Result] = SimpleQueue()
        flight = InFlight()

        def on_result(result, image, timestamp_ms: int) -> None:
            result_ms = time.monotonic() * 1000
            results.put(Result(timestamp_ms, result_ms, _landmarks(result)))

        status, detail = "crashed", "interrupted"
        try:
            options = vision.PoseLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=str(model.path)),
                running_mode=vision.RunningMode.LIVE_STREAM,
                num_poses=1,
                result_callback=on_result,
            )
            with vision.PoseLandmarker.create_from_options(options) as landmarker:
                index, timestamp_ms, end_ms = 0, -1, None
                while True:
                    frame = camera.read()
                    if frame is None:
                        raise CameraError(f"camera stopped after {index} frames")
                    capture_ms, read_ms, rgb = frame
                    if end_ms is None:
                        end_ms = capture_ms + seconds * 1000
                    if capture_ms >= end_ms:
                        break
                    # MediaPipe needs strictly rising timestamps and hands each one back with its result.
                    timestamp_ms = max(int(capture_ms), timestamp_ms + 1)
                    flight.sent(Sent(index, timestamp_ms, capture_ms, read_ms))
                    landmarker.detect_async(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), timestamp_ms)
                    index += 1
                    write_settled()
                    write_samples()
                drain_until = time.monotonic() + DRAIN_S
                while flight and time.monotonic() < drain_until:
                    time.sleep(0.01)
                    write_settled()
                write_settled(*flight.give_up())
            status, detail = "completed", ""
        except CameraError as e:
            status, detail = "crashed", str(e)
        except MemoryError as e:
            status, detail = "oom", repr(e)
        except Exception as e:
            status, detail = "crashed", repr(e)
        finally:
            camera.close()
            sampler.stop()
            write_samples()
            write({"type": "status", "status": status, "detail": detail})
    return out_path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--variant", required=True, choices=VARIANTS)
    p.add_argument("--repeat", type=int, default=1, help="session number")
    p.add_argument("--seconds", type=_sample_interval, default=60.0, help="length of the session")
    p.add_argument("--machine", default=default_machine_name())
    p.add_argument("--out-dir", type=Path, default=Path("runs"))
    p.add_argument("--models-dir", type=Path, default=Path("models"))
    p.add_argument("--sample-interval", type=_sample_interval, default=1.0, help="seconds between system samples")
    a = p.parse_args()
    print(run_live(a.variant, a.repeat, a.machine, a.out_dir, a.models_dir, a.sample_interval, a.seconds))


if __name__ == "__main__":
    main()
