# Run the benchmark in a plain Python venv over SSH, not as an App Lab App

App Lab is Arduino's standard way to run Python on the UNO Q, but it runs code inside a container next to Arduino's own OpenCV build. `mediapipe` installs its own OpenCV, which may clash with Arduino's. The container also adds startup and runtime overhead that would get mixed into the timings, and App Lab's camera defaults are 640x480 at 10 fps. We therefore run the benchmark in a plain Python venv on the Board's Debian, driven over SSH from the Dev machine, so the measured numbers reflect the model rather than the platform. App Lab can be revisited for a final demo once a Model variant is chosen.

Source: `docs/research/mediapipe-pose-on-uno-q.md`, sections 1 and 2.
