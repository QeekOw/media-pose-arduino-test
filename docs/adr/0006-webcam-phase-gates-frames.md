# The Webcam phase session lets one frame at a time into MediaPipe

The Webcam phase was designed to hand every camera frame to MediaPipe in LIVE_STREAM mode and let MediaPipe skip the frames it is too busy for. Its flow limiter is configured to hold one frame and skip the rest, which would cap the wait at about one model time. `mediapipe` 0.10.18 does not behave that way. It queues frames. In a 10 s Lite session on the Board (`webcam-trial1`), the delay grew from 1.1 s to 8.8 s over the first 2.8 s of capture. No frame captured after that got a result. From about 4.9 s on, the read loop slowed to about 6 frames a second and every frame it read was about 620 ms old, so the camera starved too. The only call in the loop that waits on MediaPipe is `detect_async`. On the Dev machine it queued about 100 frames and skipped none.

So the session gates frames itself. It reads the camera at the camera's rate. It sends a frame to `detect_async` only when no frame is in flight, meaning the previous frame's result has come back. Every frame read while one is in flight is never sent and is recorded as dropped. The result callback still only queues, and the main thread decides each frame's fate.

## Considered Options

- **Measure LIVE_STREAM's own queue as it is**: delay has no bound and grows with session length, so its average depends on how long the session ran. The camera falls far below 30 fps, so dropped % and Camera FPS describe a blocked loop, not the model.

## Consequences

- Dropped % is the share of camera frames the model never saw. Delay is capture to result of the frames it did see, with no queue wait inside MediaPipe. Processed FPS is bounded by model speed.
- After a result, the model waits for the next camera frame, up to one frame time (33 ms), before it gets new work. So processed FPS can sit a little below what the model would manage flat out (inferred, not measured).
- This measures the gate plus MediaPipe, not MediaPipe's LIVE_STREAM scheduling. The slides must say so.
