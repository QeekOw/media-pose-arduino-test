"""Run one Model variant over one Clip and write one Run file.

    python -m bench.run_one --variant lite --clip clips/smoke.mp4 --repeat 1
"""
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

from bench.envinfo import default_machine_name, machine_info, software_info
from bench.models import VARIANTS, ensure_model


def _landmarks(result) -> list | None:
    if not result.pose_landmarks:
        return None
    return [[lm.x, lm.y, lm.z, lm.visibility] for lm in result.pose_landmarks[0]]


def run_video(variant: str, clip: Path, repeat: int, machine: str, out_dir: Path, models_dir: Path) -> Path:
    model = ensure_model(variant, models_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"video__{variant}__{clip.stem}__r{repeat}__{machine}.jsonl"

    cap = cv2.VideoCapture(str(clip))
    if not cap.isOpened():
        raise SystemExit(f"cannot open clip {clip}")
    fps = cap.get(cv2.CAP_PROP_FPS)

    with out_path.open("w", encoding="utf-8") as f:
        def write(obj: dict) -> None:
            f.write(json.dumps(obj) + "\n")
            f.flush()

        write({
            "type": "header",
            "format_version": 1,
            "phase": "video",
            "variant": variant,
            "clip": clip.name,
            "repeat": repeat,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "machine": machine_info(machine, out_dir),
            "software": software_info(),
            "model": {"file": model.path.name, "size_bytes": model.size_bytes, "sha256": model.sha256},
            "clip_info": {
                "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                "fps": fps,
                "frame_count": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
            },
        })
        status, detail = "crashed", "interrupted"
        try:
            options = vision.PoseLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=str(model.path)),
                running_mode=vision.RunningMode.VIDEO,
                num_poses=1,
            )
            with vision.PoseLandmarker.create_from_options(options) as landmarker:
                index = 0
                while True:
                    t0 = time.perf_counter()
                    ok, bgr = cap.read()
                    if not ok:
                        break
                    image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
                    t1 = time.perf_counter()
                    result = landmarker.detect_for_video(image, int(index * 1000 / fps))
                    t2 = time.perf_counter()
                    write({
                        "type": "frame",
                        "index": index,
                        "video_ms": (t1 - t0) * 1000,
                        "model_ms": (t2 - t1) * 1000,
                        "landmarks": _landmarks(result),
                    })
                    index += 1
            expected = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if 0 < expected and index < expected:
                status, detail = "crashed", f"stopped early: read {index} of {expected} frames"
            else:
                status, detail = "completed", ""
        except MemoryError as e:
            status, detail = "oom", repr(e)
        except Exception as e:
            status, detail = "crashed", repr(e)
        finally:
            cap.release()
            write({"type": "status", "status": status, "detail": detail})
    return out_path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--variant", required=True, choices=VARIANTS)
    p.add_argument("--clip", required=True, type=Path)
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--machine", default=default_machine_name())
    p.add_argument("--out-dir", type=Path, default=Path("runs"))
    p.add_argument("--models-dir", type=Path, default=Path("models"))
    a = p.parse_args()
    print(run_video(a.variant, a.clip, a.repeat, a.machine, a.out_dir, a.models_dir))


if __name__ == "__main__":
    main()
