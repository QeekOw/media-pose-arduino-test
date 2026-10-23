# MediaPipe pose estimation on the Arduino UNO Q: feasibility research

- **Date:** 2026-10-22. All sources were accessed on this date unless a row says otherwise.
- **Scope:** benchmarking MediaPipe pose models on an Arduino UNO Q, first on prerecorded video and then on a live webcam.
- **Method:** primary sources only. These are Arduino docs and Arduino's GitHub repos (`arduino/docs-content`, `arduino/app-bricks-py`, `arduino/app-bricks-examples`), Qualcomm product documents, Google AI Edge docs, the `google-ai-edge/mediapipe` repo, PyPI JSON metadata, and Debian's archive API. Where I inspected a wheel or `.task` bundle, I downloaded it into memory and listed its contents without installing or running it.
- **Labels:** every claim is tagged **[C]** Confirmed (with source), **[U]** Unverified / inferred, or **[Q]** Open question for the smoke test.

> Note on Arduino doc URLs: `docs.arduino.cc` is a single-page app that returns the same HTML shell for any path, so its URLs could not be machine-verified. For each Arduino doc page, the citation points to the Markdown source in Arduino's own `arduino/docs-content` GitHub repo, which is what docs.arduino.cc renders. The rendered URL is also given where it is known.

---

## TL;DR

- **Only the Linux side can run pose models.** That is the Qualcomm Dragonwing QRB2210 MPU: 4x Cortex-A53 at 2.0 GHz, an Adreno 702 GPU, 2 or 4 GB LPDDR4X, and Debian 13 "trixie". The STM32U585 MCU (Cortex-M33, 786 kB SRAM) is not a candidate. [C]
- **Most likely path: the official `mediapipe` wheel and the Tasks API Pose Landmarker (lite / full / heavy).** Since v1.0.0 (2026-07-27), PyPI has published a `py3-none-manylinux_2_28_aarch64` wheel; the latest is 1.1.1. Its metadata lists Python 3.9 to 3.14, and the board's Debian trixie ships Python 3.13.5. So `pip install mediapipe` *should* work on the board, but nobody has verified this on UNO Q hardware. [C] for the wheel, [U] for the board.
- **The legacy `mp.solutions.pose` (model_complexity 0/1/2) is effectively gone.** It is absent from every wheel since 0.10.30. The last aarch64 wheels that contain it (0.10.18 and earlier) exist only for cp39 to cp312, not for the board's Python 3.13. Benchmarking it would need a separate Python 3.12 interpreter, so treat it as a stretch goal. [C] for the wheel contents, [U] for the workaround.
- **Arduino has no official MediaPipe pose example for UNO Q.** Arduino's own Pose Estimation brick uses PoseNet MobileNet (17 keypoints, from Qualcomm AI Hub) with the QNN/NPU delegate. Its `brick_config.yaml` lists `supported_boards: ["ventunoq"]`, so it targets the VENTUNO Q, not the UNO Q. [C]
- **Fallback if `mediapipe` will not install: run the bundle's models directly in LiteRT.** Each `.task` bundle is a zip holding `pose_detector.tflite` and `pose_landmarks_detector.tflite`. Both can run in LiteRT (`ai-edge-litert`, which has cp313 aarch64 wheels), but you must reimplement:
  - SSD anchor decoding and NMS
  - the detection-to-ROI step (rotated crop)
  - landmark un-projection
  - frame-to-frame ROI tracking
  - smoothing

  Arduino already did exactly this for MediaPipe *hand* models in its gesture-recognition runner. [C] for the bundle contents and the precedent, [U] for the effort.
- **Biggest risk: throughput on a CPU-only Cortex-A53 cluster.** No primary source publishes pose (or any MediaPipe) frame rates for the UNO Q. Google's only CPU numbers are for a Pixel 3 (Lite ~44 FPS, Full ~18 FPS, Heavy ~4 FPS via XNNPACK). GPU acceleration is unproven on this board:
  - MediaPipe's own docstring says its Python GPU delegate is "limited to Ubuntu platforms".
  - LiteRT's Linux GPU backend is WebGPU over Vulkan, but the board's driver currently reports Vulkan 1.0.318.

  I expect Heavy to be impractical for live use, but that is an inference. [C] for the cited facts, [U] for the expectation.
- **Camera:** a standard USB UVC webcam on a USB-C hub with Power Delivery is officially supported. MIPI-CSI cameras need the UNO Media Carrier, and currently only IMX219-based modules are supported. [C]
- **RAM:** Arduino recommends the 4 GB variant for on-board (SBC/App Lab) use. A 4 GB board has "about 3.6 GB of free RAM" and "a small root filesystem". [C]

---

## 1. UNO Q hardware and OS

### Confirmed (with source)

| Topic | Finding | Source |
|---|---|---|
| Dual architecture | The board pairs the Qualcomm QRB2210 MPU, running Debian Linux, with the STM32U585 MCU (Arm Cortex-M33), which runs Arduino sketches over Zephyr OS. | [S1], [S2] |
| Which chip can run pose models | Only the MPU. The MCU is a Cortex-M33 at up to 160 MHz with 2 MB flash and 786 kB SRAM. The MPU side is described as "perfect for AI frameworks". | [S2] (Tech specs), [S3] |
| MPU CPU | 4x Arm Cortex-A53 @ 2.0 GHz, 64-bit. Qualcomm brands the cores "Kryo". | [S2], [S6] |
| GPU | Adreno 702 @ 845 MHz, with memory shared with system RAM. Open-source Mesa drivers: freedreno for OpenGL ES 3.1 and turnip for Vulkan. The hardware supports Vulkan 1.1, but "the current driver implementation provides Vulkan 1.0.318". OpenCL 2.0 is provided through Mesa. The datasheet reports 1740 MB of available video memory. | [S2] (Hardware acceleration section) |
| DSP / NPU | Qualcomm's brief lists an "always-on Qualcomm Hexagon DSP" for "low-power sensor fusion and voice/audio handling", plus a "dual-core DSP". No NPU is listed. The brief describes edge AI on this platform as "integrated TensorFlow Lite, enabling efficient, on-device inference via CPU and GPU". | [S6] |
| ISP / video | Dual ISPs (13 MP + 13 MP, or 25 MP, at 30 fps). Hardware H.264/H.265 encode/decode and VP9 decode through V4L2, with GStreamer recommended. | [S2] |
| RAM / storage variants | ABX00162: 2 GB RAM, 16 GB eMMC. ABX00173: 4 GB RAM, 32 GB eMMC. RAM is LPDDR4X, single-rank, 32-bit. | [S2] |
| Free RAM | "An UNO Q 4GB version generally has about 3.6 GB of free RAM and a small root filesystem." | [S8] |
| OS | Debian. Arduino's Debian guide shows `apt update` hitting `trixie`, `trixie-updates`, `trixie-security` and `trixie-backports`, which is Debian 13. Qualcomm's brief states Linux kernel v6.16 and an XFCE desktop. | [S7], [S6] |
| Docker | The store page lists "Docker and Docker Compose support". App Lab runs Apps and Bricks as containers. | [S3], [S13] |
| Debian trixie Python | Debian's `python3-defaults` package in trixie is version 3.13.5. | [S27] |
| App Lab Python runtime | App Lab Apps run in a container built `FROM python:3.13-slim-trixie`. Arduino ships its own `opencv_python_headless-4.14.0 ... cp313-cp313-linux_aarch64` wheel in that image. A user's `python/requirements.txt` is installed with `uv pip install` into a venv, created with `--system-site-packages`, when the App starts. | [S14], [S15], [S12] |
| App Lab model | An App is mandatory Python (`python/main.py`), plus optional `requirements.txt`, optional `.whl` files in `python-libraries/`, optional Bricks, and an optional sketch for the MCU. Bricks are "pre-packaged services such as AI models, web servers, or API clients" that run as Docker Compose services next to the App container. | [S2], [S12], [S13] |
| Officially supported MPU language | "Python is the officially supported language for MPU-side development on the UNO Q." | [S7] |
| Official vision examples on UNO Q | Vision Bricks without a board restriction use Edge Impulse models: `video_objectdetection`, `object_detection`, `image_classification`, `video_imageclassification` and `visual_anomaly_detection`. The App Lab catalog lists, for UNO Q: YoloX-nano object detection, Lightweight-Face-Detection (from Qualcomm AI Hub), and person classification. The examples repo has a UNO Q face-detection App that uses `video_objectdetection` with the `face-detection` model. | [S16], [S17], [S18] |
| Pose Brick | The `pose_estimation` brick uses `posenet_mobilenet_w8a8.tflite` (17 keypoints, up to 10 people) through `ai-edge-litert` with a QNN HTP delegate, and mounts `/dev/fastrpc-cdsp`. Its config lists `supported_boards: ["ventunoq"]`. App Lab 0.11 release notes call it "Pose Estimation Brick (VENTUNO Q)". | [S19], [S20], [S21], [S22] |
| MediaPipe gesture Brick | `gesture_recognition` runs MediaPipe hand models (PalmDetector, HandLandmarkDetector, CannedGestureClassifier; w8a8 builds from Qualcomm AI Hub) in LiteRT, with Python pre- and post-processing that Arduino reimplemented. It is also restricted to `ventunoq`. | [S19], [S23] |
| Edge Impulse | Edge Impulse supports the UNO Q as a Linux target. `edge-impulse-linux-runner` "will automatically compile your model with full hardware acceleration". App Lab imports Edge Impulse models as `.eim` files. Edge Impulse lists a "Linux Arduino UNO Q (GPU)" deployment. | [S24], [S25], [S11] |
| VENTUNO Q (for contrast) | A different board: Dragonwing IQ8 (QCS8275), whose Hexagon NPU delivers "up to 40 dense TOPS", with 16 GB LPDDR5. | [S26] |

### Unverified / inferred

- **[U] The UNO Q has no NPU usable for this work.** The QRB2210 DSP is described for sensor fusion and audio. Every QNN/NPU Brick is restricted to `ventunoq`, so treat the UNO Q as CPU (plus, at best, GPU).
- **[U] The model catalog contradicts the Brick config.** The App Lab catalog lists "PoseNet MobileNet Pose Estimation" with Boards = **Unrestricted** [S17]. The Brick's own `brick_config.yaml` and the release notes restrict the Pose Estimation Brick to VENTUNO Q [S20], [S22]. The runner falls back to CPU if the QNN delegate library is missing [S21], so it *might* run on UNO Q by hand, but nothing official says so.
- **[U] Host Python is probably 3.13.5,** since that is Debian trixie's default [S27]. Arduino's docs do not state the host Python version explicitly.

---

## 2. Camera input

### Confirmed (with source)

- **[C] USB UVC webcams work through the single USB-C port.**
  - Store FAQ: "you can connect a standard USB UVC-compatible webcam" [S3].
  - User manual lists "Video Input: USB camera support" [S4].
  - Product page: "By using a USB-C dongle with external power delivery connected to the UNO Q USB-C port, you can connect: ... USB camera" [S1].
- **[C] The hub must provide Power Delivery.** "Make sure the dongle supports PD, because it is used to power the board itself. Without it, UNO Q will not boot." [S3]. Over PD the board requests 5 V / 3 A only [S2].
- **[C] Arduino's examples use a hub.** The UNO Q face-detection example specifies "USB-C hub adapter with external power" plus a "5 V, 3 A" supply, and must run in App Lab **Network Mode** [S18].
- **[C] On the host OS, cameras appear as `/dev/video*`.** The Debian guide uses `ls /dev/video*`, `lsusb`, `cheese`, and suggests `python3-opencv` [S7]. Note that the hardware video codec also occupies `/dev/video0` and `/dev/video1` [S2], so a webcam may not be `/dev/video0`.
- **[C] App Lab's `Camera` peripheral accepts several sources** [S28]:
  - USB/V4L (`"usb:/dev/videoN"`, `/dev/v4l/by-id/...`)
  - CSI (`"csi:0"`)
  - IP/URL (`rtsp://`, `http://`), including an `http://.../video.mp4` example in its docstring
  - Defaults are `resolution=(640, 480)`, `fps=10`.
- **[C] MIPI-CSI is supported only through the UNO Media Carrier.** The board exposes four-lane MIPI-CSI-2 on the bottom JMEDIA connector, at 1.8 V [S2]. App Lab supports MIPI-CSI only via the **UNO Media Carrier** (two 22-pin CSI connectors), and "currently, only cameras based on the Sony IMX219 (8 MP) sensor are supported, such as the Raspberry Pi Camera Module 2". A 15-to-22-pin adapter cable is required [S10].

### Unverified / inferred

- **[U] For the prerecorded-video phase, no camera is needed at all.** OpenCV `VideoCapture` on a file, or GStreamer with the hardware `v4l2h264dec` [S2], can feed frames. Decoding cost should be counted separately from inference.
- **[U] USB bandwidth may limit the webcam.** An Arduino VENTUNO Q tutorial notes that uncompressed YUYV over USB 2 is limited to a few fps above 640x480, and uses MJPG instead. That was a different board, but the same applies to any UVC camera.

---

## 3. MediaPipe pose model catalog

### 3a. Pose Landmarker (Tasks API, current)

The models section of the official guide [S29]:
- **[C] It is a two-model bundle.** "The first model detects the presence of human bodies within an image frame, and the second model locates landmarks." It outputs **33** 3D landmarks, in normalized image coordinates and in world coordinates, plus an optional segmentation mask. The architecture is "similar to MobileNetV2", a BlazePose variant using GHUM.
- **[C] All three variants are float16** and share the same input shapes: detector 224x224x3, landmarker 256x256x3.

| Variant | `.task` URL (from [S29]) | `.task` size | Inner files (inspected) | Model card size |
|---|---|---|---|---|
| Lite | `storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task` | 5,777,746 B | `pose_detector.tflite` 2,959,078 B + `pose_landmarks_detector.tflite` 2,818,390 B | "Lite (3MB size)" |
| Full | `.../pose_landmarker_full/float16/latest/pose_landmarker_full.task` | 9,398,198 B | detector 2,959,046 B + landmarks 6,438,874 B | "Full (6 MB size)" |
| Heavy | `.../pose_landmarker_heavy/float16/latest/pose_landmarker_heavy.task` | 30,664,242 B | detector 2,959,046 B + landmarks 27,704,918 B | "Heavy (26 MB size)" |

- **[C] File sizes** come from HTTP `Content-Length` and from listing each bundle's zip contents. The files are dated `Last-Modified` 2023-04-27/28 [S30].
- **[C] Model card** (BlazePose GHUM 3D, dated April 16, 2021) [S31]:
  - **Speed:** "Lite model runs ~44 FPS on a CPU via XNNPack TFLite and ~49 FPS via TFLite GPU on a Pixel 3. Full model runs ~18 FPS on a CPU ... ~40 FPS via TFLite GPU ... Heavy model runs ~4 FPS on a CPU ... ~19 FPS via TFLite GPU on a Pixel 3."
  - **Accuracy:** average PDJ (PCK@0.2) across 14 regions is Lite 87.0%, Full 91.8%, Heavy 94.2%.
  - **Input / output:** input is a 256x256x3 RGB crop in [0, 1], "centered by mid-hip". Output is 33x5 (x, y, z, visibility, presence).
  - **Limitations:** out of scope are multiple people, people farther than ~4 m, and head not visible.
- **[C] Video and live-stream modes use tracking.** "If you use the video mode or live stream mode, Pose Landmarker uses tracking to avoid triggering the model on every frame." There are three running modes: IMAGE, VIDEO (`detect_for_video(image, timestamp_ms)`) and LIVE_STREAM (`detect_async`). `num_poses` defaults to 1 [S32].
- **[C] There is an official Raspberry Pi (64-bit OS) example** for Pose Landmarker; its `requirements.txt` is just `mediapipe` [S33]. That makes it the closest official ARM64-Linux precedent.

### 3b. Legacy MediaPipe Solutions `mp.solutions.pose` (BlazePose GHUM, model_complexity 0/1/2)

- **[C] It is officially superseded.** "As of May 10, 2023, this solution was upgraded to a new MediaPipe Solution" [S34]. The Google AI Edge guide adds: "We have ended support for the MediaPipe Legacy Solutions listed here as of March 1, 2023 ... prebuilt binaries for all MediaPipe Legacy Solutions will continue to be provided on an as-is basis." Pose is listed as "Upgraded" to Pose landmark detection [S35].
- **[C] Settings:** `model_complexity` 0, 1 or 2, default 1. "Landmark accuracy as well as inference latency generally go up with the model complexity." Other options: `static_image_mode`, `smooth_landmarks`, `enable_segmentation` and `min_tracking_confidence` [S34].
- **[C] Published quality** (17 COCO keypoints, PCK@0.2) [S34]:
  - Heavy: 96.4 / 97.2 / 97.5 (Yoga / Dance / HIIT)
  - Full: 95.5 / 96.3 / 95.7
  - Lite: 90.2 / 92.5 / 93.5
- **[C] Published latency** [S34]:
  - Pixel 3 with TFLite GPU: Heavy 53 ms, Full 25 ms, Lite 20 ms.
  - MacBook Pro 2017: 38 / 27 / 25 ms.
- **[C] Model files** (inspected in the 0.10.18 aarch64 cp312 wheel):
  - The wheel bundles only `pose_detection.tflite` (2,959,046 B) and `pose_landmark_full.tflite` (6,440,512 B).
  - `pose_landmark_lite.tflite` and `pose_landmark_heavy.tflite` are downloaded at runtime (`_download_oss_pose_landmark_model` in `solutions/pose.py`) [S36].
- **[C] It has been removed from the Python package.** `mediapipe/python/solutions/pose.py` is present in 0.10.21 and absent in 0.10.30, 0.10.31 and 1.1.1. Checked by listing the wheel contents [S36].

### 3c. Other pose models under or near MediaPipe

- **[C] Holistic Landmarker** exists as a MediaPipe Task, with pose landmarks inside it; it appears in the Tasks navigation and the legacy upgrade table [S35]. It is not a separate pose model.
- **[C] Qualcomm AI Hub has `mediapipe_pose`.** It is a re-packaging whose README says the original implementation is MediaPipePyTorch, a third-party port. Its `perf.yaml` lists **Arduino VENTUNO Q** but contains no UNO Q, QRB2210 or RB1 entries [S37]. It is not a Google artifact.

---

## 4. Runtime availability on ARM64 Linux

### Confirmed (with source)

- **[C] `mediapipe` on PyPI** [S38], with wheel contents inspected [S36]:
  - **Current aarch64 wheels.** Versions 1.0.0 (2026-07-27), 1.0.1, 1.1.0 and 1.1.1 (2026-10-14) each ship one `mediapipe-<ver>-py3-none-manylinux_2_28_aarch64.whl`. Version 1.1.1 is 39,028,305 B.
  - **Gap with no aarch64 wheel:** 0.10.10, 0.10.11, 0.10.20, 0.10.21, and 0.10.30 through 0.10.35.
  - **Older aarch64 wheels** (≤0.10.18) were per-CPython builds: cp39 to cp312 for 0.10.13 through 0.10.18. None is cp313.
  - **What the 1.1.1 aarch64 wheel contains:**
    - The Tasks Python API, as ctypes wrappers around a single `mediapipe/tasks/c/libmediapipe.so` (120,549,368 B uncompressed).
    - Classifiers for Python 3.9 to 3.14.
    - `Requires-Dist`: absl-py, certifi, numpy, sounddevice, flatbuffers, opencv-contrib-python, matplotlib.
    - No `mediapipe/python/solutions/`.
  - **Dependencies resolve on aarch64.** PyPI has wheels for `opencv-contrib-python` 5.0.0.93 (`cp37-abi3-manylinux_2_28_aarch64`), `matplotlib` 3.11.2 (cp313 aarch64) and `numpy` 2.5.4 (cp313 aarch64) [S38].
- **[C] Release notes:** v1.1.0 says "Add Python 3.13 and 3.14 support to the MediaPipe Bazel build" and "Expose LiteRT and NPU delegate options to MediaPipe Tasks." v0.10.32 says "support armv7 (32 bit in mediapipe tasks)" [S39].
- **[C] Official setup page:** "Desktop: Windows, Mac, Linux; IoT: Raspberry OS 64-bit; Python: Supports version 3.9 and later" [S40].
- **[C] MediaPipe's Python GPU delegate is limited to Ubuntu.** The `BaseOptions.Delegate` enum has CPU and GPU. Its docstring in the shipped 1.1.1 wheel says: "GPU support is currently limited to Ubuntu platforms." [S36]. The UNO Q runs Debian.
- **[C] LiteRT (`ai-edge-litert`)** [S41]:
  - Version 2.3.0 (2026-10-06) ships `manylinux_2_27_aarch64` wheels for cp310 to cp314.
  - Arduino's App Lab LiteRT runners already pin `ai-edge-litert` with `requires-python = "==3.13.*"` for `linux/aarch64` [S42].
  - The LiteRT overview table still says "Python 3.9–3.12" [S43], which lags the published wheels.
- **[C] `tflite-runtime` is stale.** The last release is 2.14.0 (2023-10-03); its aarch64 wheels cover cp38 to cp311 only, with no cp313 [S44]. Do not use it on this board.
- **[C] LiteRT GPU on Linux uses WebGPU over Vulkan.** The LiteRT GPU page lists the Linux backend as "WebGPU (Vulkan)" [S45]. The overview's accelerator table lists Linux GPU as "WebGPU / OpenCL" [S43].
- **[C] The board's Vulkan stack** is Mesa turnip, reporting Vulkan 1.0.318 even though the hardware supports 1.1. OpenCL 2.0 is available through Mesa [S2].

### What a LiteRT-only fallback must reimplement (if `mediapipe` will not import)

The following comes from Google's own graph definitions [S46] and the model card [S31]:

1. **[C] Detector pre-processing.** Letterbox the frame to 224x224 RGB (`ImageToTensorCalculator`, `output_tensor_width: 224`).
2. **[C] Detector decoding.**
   - Generate SSD anchors: `num_layers: 5`, `strides: 8, 16, 32, 32, 32`, `min_scale 0.1484375`, `max_scale 0.75`, `fixed_anchor_size: true`.
   - Decode `num_boxes: 2254`, `num_coords: 12` (a box plus `num_keypoints: 4` x 2 values).
   - Apply NMS with `min_suppression_threshold: 0.3` (IoU).
   - Remove the letterbox.
3. **[C] Detection to ROI** (`PoseDetectionToRoi`). The detector predicts virtual keypoints: hip midpoint, a circle radius covering the body, and a shoulder-hip incline. These define a rotated square ROI [S34].
4. **[C] Landmark model.** Crop and rotate the ROI to 256x256 RGB in [0, 1]. Run the model; outputs include 33x5 landmarks, world landmarks and segmentation. Then inverse-project the landmarks into image coordinates (`PoseLandmarksAndSegmentationInverseProjection`).
5. **[C] Tracking loop.** Derive the next-frame ROI from the current landmarks (`PoseLandmarksToRoi` plus `PreviousLoopbackCalculator`). Re-run the detector only when tracking is lost [S34], [S46].
6. **[C] Smoothing** (`PoseLandmarkFiltering`), plus sigmoid on the visibility and presence values [S31].
7. **[C] There is a precedent.** Arduino's `gesture-recognition-runner` does the equivalent for MediaPipe *hands*. It ships an `anchors_palm.npy` file and `bbox_processing.py`, `image_processing.py` and `post_processing.py`, running in LiteRT [S23].

### Unverified / inferred

- **[U] `pip install mediapipe` should work on the board.** Inside a venv on Debian trixie aarch64 with Python 3.13.5, the 1.1.1 wheel *should* install, because the tag is `py3-none` and the glibc floor is 2.28. This is unverified on hardware. Debian's PEP 668 "externally managed" policy may require a venv; that is a general Debian behaviour I did not source here.
- **[U] Inside App Lab, putting `mediapipe` in `requirements.txt` may cause an OpenCV clash.** It would pull `opencv-contrib-python` alongside Arduino's custom `opencv-python-headless` build, and both provide `cv2` [S14], [S15]. A plain venv on the host over SSH may be simpler for a benchmark.
- **[U] GPU acceleration is unproven on this board.** MediaPipe's Python GPU path is documented as Ubuntu-only. Whether LiteRT's WebGPU/Vulkan backend initializes on turnip's Vulkan 1.0.318, and whether the PyPI `ai-edge-litert` wheel includes the Linux GPU accelerator at all, is not stated in any source I found. Plan the benchmark as **CPU (XNNPACK) first**.
- **[U] Fallback quality may differ from MediaPipe's own output.** The LiteRT route measures *model* latency faithfully, but pipeline behaviour (tracking, smoothing) will only approximate MediaPipe's unless it is ported carefully. Results from the two paths are not directly comparable.

---

## 5. Feasibility risks

### Confirmed (with source)

- **[C] Arduino steers on-board use to the 4 GB variant.** It recommends 4 GB for SBC use and for running App Lab on the board [S1], [S4], [S5]. The store describes the 2 GB variant as for "cost-efficient, dedicated lightweight applications" and the 4 GB for "complex AI model support" [S3].
- **[C] The root filesystem is small.** A 4 GB board has ~3.6 GB free RAM and "a small root filesystem" [S8]. The App Lab model docs tell users to check **Disk storage** before downloading large models [S17].
- **[C] The App Lab LLM catalog for UNO Q stays around 1B parameters.** "the built-in language models for the UNO Q have about 1 billion parameters or fewer" [S17]. This signals the compute class Arduino targets.
- **[C] Operating temperature is −10 to 60 °C ambient.** "operating near the limits can reduce the available output current" [S9]. Qualcomm describes the QRB2210 as "optimized for thermally constrained ... devices" [S6].
- **[C] No primary source gives UNO Q frame rates for any pose model**, MediaPipe or PoseNet. The only nearby numbers are Edge Impulse Studio estimates in an Arduino App Lab tutorial that trains a model "for the Arduino UNO Q": MobileNetV2 SSD FPN-Lite 320x320 at "Inferencing Time: 370 ms", and FOMO 96x96 at "3 ms". The tutorial's guidance is "<500ms for ~2 FPS" [S11]. These are object-detection estimates, not pose measurements.

### Unverified / inferred

- **[U] Throughput.** A Pixel 3 has big cores (2.5 GHz Kryo 385 Gold, which is Cortex-A75 class); the UNO Q has 4x A53 at 2.0 GHz. Google's Pixel 3 CPU numbers (Lite ~44, Full ~18, Heavy ~4 FPS) are therefore an upper bound, and the UNO Q will likely be several times slower. The Pixel 3 CPU detail is general knowledge and not sourced here.
- **[U] Thermal throttling.** The UNO Q has no fan or heatsink in its docs; the VENTUNO Q docs mention a fan, the UNO Q docs do not. I found no Arduino statement about QRB2210 throttling. Log `/sys/class/thermal` and CPU frequency during sustained runs.
- **[U] Memory.** The models themselves are small (≤28 MB for Heavy). The bigger costs are `libmediapipe.so` (~120 MB uncompressed), OpenCV, the desktop session if in SBC mode, and the App Lab containers. On the 2 GB board this may be tight. Prefer headless (SSH) operation for benchmarks.
- **[U] Power.** Use a PD supply that can deliver 5 V / 3 A and still power a webcam through the hub, since the board requests only 5 V / 3 A [S2].

---

## 6. Comparable alternatives (non-MediaPipe, brief)

| Option | Status on UNO Q | Source |
|---|---|---|
| Arduino **Pose Estimation Brick** (PoseNet MobileNet w8a8, 17 kp, multi-person, from Qualcomm AI Hub) | Officially VENTUNO Q only. The model catalog says "Unrestricted", and the runner falls back to CPU without the QNN library. Running it on UNO Q is unofficial and untested. | [S17], [S20], [S21], [S22] |
| **Qualcomm AI Hub** `mediapipe_pose` / `posenet_mobilenet` | Published perf data covers VENTUNO Q, not UNO Q or QRB2210. | [S37] |
| **Edge Impulse** on UNO Q | Supported as a Linux target with a GPU deployment option, but the official UNO Q material covers classification, detection, FOMO and anomaly detection, not pose. | [S24], [S25] |
| Arduino **gesture recognition** (MediaPipe hands, LiteRT) | VENTUNO Q only, but a useful code template for a LiteRT re-implementation. | [S19], [S23] |

---

## Open questions for the smoke test

Run these on the physical board, over SSH and headless first, and record outputs verbatim.

1. **Identity and OS**
   - `cat /etc/os-release`
   - `uname -a`
   - `python3 --version`. I expect 3.13.x; this is unverified.
   - `free -h`
   - `df -h /`
   - Which RAM variant is the test board (2 GB or 4 GB)?
2. **CPU and thermal baseline**
   - `nproc`
   - `cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq`
   - `cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor`
   - `cat /sys/class/thermal/thermal_zone*/{type,temp}`, idle and after 10 minutes of load. Is there throttling?
3. **MediaPipe install**
   - `python3 -m venv ~/mp && ~/mp/bin/pip install mediapipe`. Record the resolved version and every dependency wheel. Check for any source build, especially of `sounddevice`, `matplotlib` or `opencv-contrib-python`.
   - `python -c "import mediapipe as mp; print(mp.__version__)"`
   - Does `import mediapipe` need `libportaudio2` because of `sounddevice`?
4. **Pose Landmarker smoke test**
   - Load each of lite, full and heavy `.task` in `RunningMode.VIDEO`.
   - Run `detect_for_video` on a short MP4.
   - Record per-frame latency (p50/p95), RSS memory and CPU %.
5. **GPU delegate**
   - Does `BaseOptions(delegate=GPU)` initialize, or fail with a clear error? MediaPipe documents this as Ubuntu-only.
   - Run `vulkaninfo --summary` and `clinfo`, which need `vulkan-tools` and `clinfo`.
6. **LiteRT fallback**
   - `pip install ai-edge-litert`
   - Load the two `.tflite` files extracted from a `.task` zip.
   - Print the input and output tensor shapes and types.
   - Time `invoke()` with `num_threads` set to 1, 2 and 4.
   - Check whether any GPU accelerator is exposed in the Python API on this build.
7. **Legacy Solutions (optional)**
   - Can a Python 3.12 interpreter be provisioned, for example with `uv python install 3.12`?
   - Does `mediapipe==0.10.18` (cp312 aarch64) install and run `mp.solutions.pose` with `model_complexity` 0, 1 and 2? The lite and heavy models download at runtime, which needs network access.
8. **Camera**
   - Do this with the webcam on a PD hub.
   - `v4l2-ctl --list-devices`
   - `v4l2-ctl -d /dev/videoN --list-formats-ext`. Check MJPG versus YUYV at 640x480 and 1280x720.
   - Confirm which `/dev/video*` nodes belong to the codec and which to the webcam.
   - Measure the achieved capture FPS with OpenCV.
9. **Video decode**
   - Compare decode-only FPS for the benchmark MP4 with OpenCV versus GStreamer `v4l2h264dec`, so decode cost can be subtracted.
10. **App Lab path (if wanted)**
    - Does adding `mediapipe` to an App's `requirements.txt` install cleanly in the App container?
    - Does `cv2` resolve to Arduino's headless build or to `opencv-contrib-python`?
    - Does the Pose Estimation Brick (PoseNet) start on UNO Q with CPU fallback?

---

## Claims I could not verify from a primary source

- The UNO Q's exact host Python version. I inferred it from Debian trixie's default; Arduino does not state it.
- Whether any QRB2210 DSP is usable for neural-network inference. Qualcomm documents it only for sensor fusion and audio, so I assumed it is not usable.
- Whether LiteRT's Linux GPU (WebGPU/Vulkan) or OpenCL path works with the board's Mesa drivers, and whether the PyPI `ai-edge-litert` wheel includes it.
- Any UNO Q frame rate for any pose model. Every throughput expectation above is an inference from Pixel 3 numbers.
- Thermal throttling behaviour of the UNO Q under sustained load.
- That a Pixel 3's CPU is substantially faster per core than a 2.0 GHz Cortex-A53. This is general knowledge and is not cited.
- PEP 668 / "externally managed environment" behaviour of Debian trixie's pip. This is general Debian knowledge and is not cited.

---

## Sources

All sources were accessed 2026-10-22.

**Arduino**

- [S1] Arduino UNO Q product page. https://docs.arduino.cc/hardware/uno-q/ (rendered page fetched); source: https://github.com/arduino/docs-content/blob/main/content/hardware/uno/boards/uno-q/features.md
- [S2] Arduino UNO Q datasheet (ABX00162/ABX00173), revision history through 26/08/2026, rev 15. https://github.com/arduino/docs-content/blob/main/content/hardware/uno/boards/uno-q/datasheet/en-datasheet.md (PDF: https://docs.arduino.cc/resources/datasheets/ABX00162-ABX00173-datasheet.pdf)
- [S3] Arduino Store, UNO Q (2GB page, including FAQ). https://store.arduino.cc/products/uno-q
- [S4] UNO Q User Manual. https://github.com/arduino/docs-content/blob/main/content/hardware/uno/boards/uno-q/tutorials/first-steps/user-manual/content.md (rendered: https://docs.arduino.cc/tutorials/uno-q/user-manual/)
- [S5] UNO Q as a Single-Board Computer. https://github.com/arduino/docs-content/blob/main/content/hardware/uno/boards/uno-q/tutorials/guides/single-board-computer/content.md
- [S7] UNO Q Debian guide. https://github.com/arduino/docs-content/blob/main/content/hardware/uno/boards/uno-q/tutorials/linux/debian-guide/content.md
- [S8] UNO Q llama.cpp guide (free RAM, root filesystem). https://github.com/arduino/docs-content/blob/main/content/hardware/uno/boards/uno-q/tutorials/guides/llama-cpp/llama-cpp.md
- [S9] UNO Q power specification. https://github.com/arduino/docs-content/blob/main/content/hardware/uno/boards/uno-q/tutorials/first-steps/power-specification/content.md
- [S10] App Lab, MIPI-CSI Camera. https://github.com/arduino/docs-content/blob/main/content/software/app-lab/2.configure/5.mipi-camera/mipi-camera.md
- [S11] App Lab, Custom AI Models (Edge Impulse). https://github.com/arduino/docs-content/blob/main/content/software/app-lab/8.integrations/2.ai-models/ai-models.md
- [S12] App Lab, About Apps. https://github.com/arduino/docs-content/blob/main/content/software/app-lab/4.apps/1.about-apps/about-apps.md
- [S13] App Lab, Custom Bricks. https://github.com/arduino/docs-content/blob/main/content/software/app-lab/5.bricks/3.custom-bricks/custom-bricks.md
- [S14] `arduino/app-bricks-py`, `containers/base/python-base/Dockerfile`. https://github.com/arduino/app-bricks-py/blob/main/containers/base/python-base/Dockerfile
- [S15] `arduino/app-bricks-py`, `containers/bricks/python-apps-base/` (Dockerfile and `scripts/run.sh`). https://github.com/arduino/app-bricks-py/tree/main/containers/bricks/python-apps-base
- [S16] `arduino/app-bricks-py`, Brick configs (`src/arduino/app_bricks/*/brick_config.yaml`). https://github.com/arduino/app-bricks-py/tree/main/src/arduino/app_bricks
- [S17] App Lab, AI Models (catalog). https://github.com/arduino/docs-content/blob/main/content/software/app-lab/8.integrations/3.models/models.md
- [S18] `arduino/app-bricks-examples`, UNO Q video face detection. https://github.com/arduino/app-bricks-examples/tree/main/inspirational/platform_unoq/video-face-detection
- [S19] `arduino/app-bricks-py`, repository tree (containers/ai/*). https://github.com/arduino/app-bricks-py
- [S20] Pose Estimation Brick config and README. https://github.com/arduino/app-bricks-py/tree/main/src/arduino/app_bricks/pose_estimation
- [S21] Pose estimation runner (`inference.py`, Dockerfile) and `aihub/tf.py`. https://github.com/arduino/app-bricks-py/tree/main/containers/ai/pose-estimation-runner and https://github.com/arduino/app-bricks-py/blob/main/containers/base/aihub-framework/aihub/tf.py
- [S22] App Lab 0.11 release notes. https://github.com/arduino/docs-content/blob/main/content/software/app-lab/9.release-notes/03.release-0-11/content.md
- [S23] Gesture recognition runner (MediaPipe hand models in LiteRT). https://github.com/arduino/app-bricks-py/tree/main/containers/ai/gesture-recognition-runner
- [S26] Arduino VENTUNO Q datasheet. https://github.com/arduino/docs-content/blob/main/content/hardware/ventuno/boards/ventuno-q/datasheet/en-datasheet.md
- [S28] `arduino/app-bricks-py`, Camera peripheral. https://github.com/arduino/app-bricks-py/blob/main/src/arduino/app_peripherals/camera/camera.py
- [S42] `aihub-litert-models-runner/pyproject.toml`. https://github.com/arduino/app-bricks-py/blob/main/containers/ai/aihub-litert-models-runner/pyproject.toml

**Qualcomm**

- [S6] Qualcomm Dragonwing QRB2210 Processor Product Brief, 87-61720-1. The file URL says REV_C; the document body says "Rev. D". https://docs.qualcomm.com/doc/87-61720-1/87-61720-1_REV_C_Qualcomm_Dragonwing_QRB2210_Processor_Product_Brief.pdf
- [S37] Qualcomm AI Hub models repo: `mediapipe_pose` and `posenet_mobilenet` README and `perf.yaml`. https://github.com/quic/ai-hub-models/tree/main/src/qai_hub_models/models/mediapipe_pose and https://github.com/quic/ai-hub-models/tree/main/src/qai_hub_models/models/posenet_mobilenet

**Edge Impulse**

- [S24] Edge Impulse docs, Arduino UNO Q. https://docs.edgeimpulse.com/hardware/boards/arduino-uno-q
- [S25] Edge Impulse docs, Run Arduino App Lab. https://docs.edgeimpulse.com/hardware/deployments/run-arduino-app-lab

**Debian**

- [S27] Debian sources API, `python3-defaults` (trixie: 3.13.5-1). https://sources.debian.org/api/src/python3-defaults/

**Google AI Edge / MediaPipe**

- [S29] Google AI Edge, Pose landmark detection guide (models table). https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker
- [S30] Pose Landmarker `.task` files (HTTP headers and zip listing). https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_{lite,full,heavy}/float16/latest/pose_landmarker_{lite,full,heavy}.task
- [S31] Model Card, BlazePose GHUM 3D. https://storage.googleapis.com/mediapipe-assets/Model%20Card%20BlazePose%20GHUM%203D.pdf
- [S32] Pose landmark detection guide for Python. https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker/python
- [S33] mediapipe-samples, Pose Landmarker Raspberry Pi example. https://github.com/google-ai-edge/mediapipe-samples/tree/main/examples/pose_landmarker/raspberry_pi
- [S34] MediaPipe legacy docs, Pose (`docs/solutions/pose.md`). https://github.com/google-ai-edge/mediapipe/blob/master/docs/solutions/pose.md
- [S35] Google AI Edge, MediaPipe Solutions guide (Legacy solutions section). https://ai.google.dev/edge/mediapipe/solutions/guide
- [S36] Inspected wheel contents. These were downloaded from PyPI into memory and listed, not installed: `mediapipe-1.1.1-py3-none-manylinux_2_28_aarch64.whl`, `mediapipe-0.10.18-cp312-cp312-manylinux_2_17_aarch64.manylinux2014_aarch64.whl`, and `mediapipe-0.10.{21,30,31}` manylinux x86_64. URLs from https://pypi.org/pypi/mediapipe/json
- [S39] google-ai-edge/mediapipe GitHub releases (v1.1.1, v1.1.0, v1.0.0, v0.10.32, ...). https://github.com/google-ai-edge/mediapipe/releases
- [S40] Google AI Edge, MediaPipe setup guide for Python. https://ai.google.dev/edge/mediapipe/solutions/setup_python
- [S43] Google AI Edge, LiteRT overview. https://ai.google.dev/edge/litert/overview
- [S45] Google AI Edge, LiteRT GPU acceleration. https://ai.google.dev/edge/litert/next/gpu
- [S46] MediaPipe graph definitions. https://github.com/google-ai-edge/mediapipe/blob/master/mediapipe/modules/pose_detection/pose_detection_cpu.pbtxt, https://github.com/google-ai-edge/mediapipe/blob/master/mediapipe/modules/pose_landmark/pose_landmark_cpu.pbtxt, https://github.com/google-ai-edge/mediapipe/blob/master/mediapipe/modules/pose_landmark/pose_landmark_by_roi_cpu.pbtxt

**PyPI**

- [S38] PyPI `mediapipe` (JSON API and project page) and dependency checks. https://pypi.org/project/mediapipe/ (https://pypi.org/pypi/mediapipe/json); dependencies: https://pypi.org/pypi/opencv-contrib-python/json, https://pypi.org/pypi/matplotlib/json, https://pypi.org/pypi/numpy/json
- [S41] PyPI `ai-edge-litert`. https://pypi.org/project/ai-edge-litert/ (https://pypi.org/pypi/ai-edge-litert/json)
- [S44] PyPI `tflite-runtime`. https://pypi.org/project/tflite-runtime/ (https://pypi.org/pypi/tflite-runtime/json)
