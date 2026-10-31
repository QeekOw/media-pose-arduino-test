# MediaPipe Pose on UNO Q

A benchmark comparing MediaPipe pose estimation models running on an Arduino UNO Q, first on prerecorded video and then on a live webcam, to find out which model works best on the board.

## Hardware

**Board**:
The Linux side of the Arduino UNO Q 4 GB (Qualcomm QRB2210 running Debian), where every model under test runs.
_Avoid_: Arduino, device, MCU (the STM32 microcontroller plays no part in the benchmark)

**Dev machine**:
The Windows laptop where code is written and from which the Board is driven over SSH.
_Avoid_: host, PC

## Models

**Model variant**:
One of the three Pose Landmarker models under comparison: Lite, Full, or Heavy. All three output the same 33 landmarks and differ only in size and accuracy.
_Avoid_: model type, version, complexity

## Measurement

**Clip**:
One of the five free stock videos used in the Video phase, each chosen to cover one situation (front view, side view, fast movement, far away or partly hidden, empty room) and converted to the same size, frame rate, and length.
_Avoid_: video, sample, test video

**Run**:
One Model variant processing one clip from start to finish on the Board. Each pairing of Model variant and clip is repeated as several Runs.
_Avoid_: trial, test, iteration

**Campaign**:
One Run plan executed unattended on the Board: every Model variant on every Clip, repeated, in shuffled order with the seed recorded, with the Board cooled between Runs. Its Run files and a log of the order and cool-down waits come back to the Dev machine together.
_Avoid_: batch, suite

**Reference landmarks**:
The landmarks produced by Heavy running on the Dev machine, used as the stand-in for correct answers when scoring a Run's accuracy. They are a stand-in, not ground truth.
_Avoid_: ground truth, labels, correct answers

**Laptop baseline**:
All three Model variants run on the Dev machine against the same Clips, shown next to the Board's results for comparison.
_Avoid_: PC results, control

## Phases

**Video phase**:
The first phase, in which every Model variant runs on the Board against the same set of prerecorded video files.
_Avoid_: offline test, file test

**Pass criteria**:
The minimum a Model variant must achieve on the Board in the Video phase to move on to the Webcam phase.
_Avoid_: gate, threshold, requirements

**Webcam phase**:
The second phase, in which Model variants that met the Pass criteria run on the Board against live frames from a USB webcam.
_Avoid_: live test, camera test, real-time phase

**Session**:
One Webcam phase Run: one Model variant fed live frames from the webcam for a fixed time, 60 s by default. Each variant in scope gets three.
_Avoid_: take, recording, live Run

**Demo recording**:
A webcam capture on the Board that saves the camera frames together with the pose results, made only to show tracking on a slide. It is never measured, never counted as a Session, never given to Analysis, and never made while a Campaign runs.
_Avoid_: demo Session, demo Run, recording
