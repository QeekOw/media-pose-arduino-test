import platform
import shutil
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def _os_name() -> str:
    release = Path("/etc/os-release")
    if release.exists():
        for line in release.read_text().splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip('"')
    return f"{platform.system()} {platform.release()}"


def _meminfo_mb() -> dict[str, int | None]:
    meminfo = Path("/proc/meminfo")
    if not meminfo.exists():
        return {"ram_total_mb": None, "ram_available_mb": None}
    kb = {k: int(v.split()[0]) for k, v in (l.split(":", 1) for l in meminfo.read_text().splitlines())}
    return {"ram_total_mb": kb["MemTotal"] // 1024, "ram_available_mb": kb["MemAvailable"] // 1024}


def _pkg(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def default_machine_name() -> str:
    return "board" if platform.machine() == "aarch64" else "dev"


def machine_info(name: str, disk_path: Path) -> dict:
    return {
        "name": name,
        "os": _os_name(),
        "kernel": platform.release(),
        "arch": platform.machine(),
        "python": platform.python_version(),
        **_meminfo_mb(),
        "disk_free_mb": shutil.disk_usage(disk_path).free // (1024 * 1024),
    }


def software_info() -> dict:
    opencv = next(
        (v for v in map(_pkg, ("opencv-contrib-python", "opencv-python", "opencv-python-headless")) if v),
        None,
    )
    return {"mediapipe": _pkg("mediapipe"), "numpy": _pkg("numpy"), "opencv": opencv, "python": sys.version.split()[0]}
