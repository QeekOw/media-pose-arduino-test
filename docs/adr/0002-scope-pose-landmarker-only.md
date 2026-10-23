# Compare only the three Pose Landmarker variants

The benchmark compares Pose Landmarker Lite, Full, and Heavy, which are the current MediaPipe pose models, and nothing else. Two other options are deliberately excluded:

- The legacy `mp.solutions.pose` (BlazePose `model_complexity` 0/1/2). Google stopped supporting it in 2023, it is missing from every `mediapipe` release since 0.10.30, and the old releases that contain it have no build for the Board's Python 3.13.
- Arduino's Pose Estimation Brick (PoseNet MobileNet, 17 keypoints). It is not MediaPipe, and Arduino restricts it to the VENTUNO Q.

Either can be added later as a stretch goal without changing how the three main variants are compared.

Source: `docs/research/mediapipe-pose-on-uno-q.md`, sections 1 and 3.
