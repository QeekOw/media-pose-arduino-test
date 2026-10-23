# Run `mediapipe` 0.10.18 on a uv-managed Python 3.12, on both machines

The `mediapipe` 1.x aarch64 wheels install and import on the Board, but creating a Pose Landmarker kills the process with SIGILL (exit 132). With 1.1.1 the message was `This binary was compiled with lse enabled, but this feature is not available on this processor`. With 1.0.0 only the exit code was seen. The Board's Cortex-A53 cores have no ARMv8.1 LSE atomics (`/proc/cpuinfo` shows no `atomics` flag). `mediapipe` 0.10.18, whose wheel is tagged manylinux2014, creates and runs the same Pose Landmarker bundles fine on the Board. The older aarch64 wheels only exist for Python 3.12 and below, and the Board's system Python is 3.13.

So both machines use `mediapipe==0.10.18` on Python 3.12. On the Board, `uv` installs a standalone Python 3.12 into the venv with no `sudo`, which also removes the need for the `python3-venv` system package. The Dev machine uses the same pin so the Laptop baseline and the Reference landmarks come from the same runtime as the Board's Runs. This supersedes the "Python 3.13 on both" line in the spec. ADR 0002 still holds, because the model bundles are the same Pose Landmarker Lite, Full and Heavy files and the Tasks API is the same one the spec names.

## Considered Options

- **LiteRT directly** (`ai-edge-litert`, which has cp313 aarch64 wheels): works with any Python, but means reimplementing MediaPipe's detection-to-ROI step, landmark un-projection and tracking. Kept as the fallback if 0.10.18 turns out to be unusable.
- **Build `mediapipe` 1.x from source without LSE**: needs a Bazel build on a 4-core A53 with limited disk. Not tried.

## Consequences

- The benchmark measures `mediapipe` 0.10.18's runtime, not the current release. The slides must say this. Results for 1.x on a CPU with LSE could differ.
- Every Run header records the `mediapipe`, `numpy` and `opencv` versions, so this stays traceable.
