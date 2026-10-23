# Pass criteria for moving from the Video phase to the Webcam phase

A Model variant moves on to the Webcam phase only if, on the Board and across all Clips:

- it averages at least 10 FPS,
- the slowest 5% of frames each take 150 ms or less,
- it finds the person in at least 90% of frames in Clips that contain one,
- and it finishes every Run without crashing or running out of memory.

10 FPS is roughly the lowest rate at which body movement still looks continuous and a live feed stays usable. The 150 ms limit catches models whose average is fine but whose occasional slow frames would make a webcam feed stutter. The 90% detection rate stops a model from passing on speed alone while missing the person. These limits were chosen by us for an exploratory study, not taken from a standard, so they can be adjusted if the mentor names different targets.

If no Model variant passes, that is reported as the finding, and the Webcam phase runs with Lite only, labelled as an "as-is" demo.
