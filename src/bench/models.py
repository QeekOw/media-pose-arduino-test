import hashlib
import urllib.request
from dataclasses import dataclass
from pathlib import Path

VARIANTS = ("lite", "full", "heavy")
URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_{v}/float16/latest/pose_landmarker_{v}.task"
)


@dataclass(frozen=True)
class ModelFile:
    path: Path
    size_bytes: int
    sha256: str


def ensure_model(variant: str, models_dir: Path) -> ModelFile:
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}, expected one of {VARIANTS}")
    path = models_dir / f"pose_landmarker_{variant}.task"
    if not path.exists():
        models_dir.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(".part")
        urllib.request.urlretrieve(URL.format(v=variant), partial)
        partial.rename(path)
    return ModelFile(path, path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest())
