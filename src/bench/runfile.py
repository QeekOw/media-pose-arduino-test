import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Header:
    format_version: int
    phase: str
    variant: str
    clip: str
    repeat: int
    started_at: str
    machine: dict = field(default_factory=dict)
    software: dict = field(default_factory=dict)
    model: dict = field(default_factory=dict)
    clip_info: dict = field(default_factory=dict)

    @property
    def machine_name(self) -> str:
        return self.machine.get("name", "")


@dataclass(frozen=True)
class Frame:
    index: int
    video_ms: float
    model_ms: float
    landmarks: list[list[float]] | None

    @property
    def frame_ms(self) -> float:
        return self.video_ms + self.model_ms


@dataclass(frozen=True)
class RunFile:
    path: Path
    header: Header | None
    frames: list[Frame]
    status: str | None
    problem: str | None


def read_run(path: str | Path) -> RunFile:
    path = Path(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = [(n, ln) for n, ln in enumerate(text.splitlines(), 1) if ln.strip()]
    header = None
    frames: list[Frame] = []
    status = None
    problem = None
    for pos, (number, line) in enumerate(lines):
        try:
            record = json.loads(line)
            kind = record.get("type")
            if kind == "header" and pos == 0:
                header = Header(
                    format_version=record["format_version"],
                    phase=record["phase"],
                    variant=record["variant"],
                    clip=record["clip"],
                    repeat=record["repeat"],
                    started_at=record["started_at"],
                    machine=record.get("machine", {}),
                    software=record.get("software", {}),
                    model=record.get("model", {}),
                    clip_info=record.get("clip_info", {}),
                )
            elif kind == "frame":
                frames.append(
                    Frame(
                        index=record["index"],
                        video_ms=record["video_ms"],
                        model_ms=record["model_ms"],
                        landmarks=record.get("landmarks"),
                    )
                )
            elif kind == "status":
                status = record["status"]
        except json.JSONDecodeError:
            # A crash mid-write leaves a partial last line, which is not corruption.
            if pos != len(lines) - 1:
                problem = f"corrupt line {number}"
            break
        except (AttributeError, KeyError, TypeError):
            problem = f"corrupt line {number}"
            break
    if header is None and problem is None:
        problem = "no header line"
    return RunFile(path=path, header=header, frames=frames, status=status, problem=problem)
