# Score accuracy against Heavy on the Dev machine, not hand-labelled data

The Clips are free stock videos, so nobody has marked where the joints actually are. Instead of labelling frames by hand or switching to a labelled research dataset, we treat the landmarks Heavy produces on the Dev machine as Reference landmarks. Each Run is scored by PCK@0.2 against those: the percentage of landmarks that land within 20% of torso length of the reference. This is quick to set up, works for any Clip, and is the same measure Google's model card uses, but it measures agreement with Heavy rather than true correctness, so Heavy on the Board will score close to 100% by construction. The slides must say this plainly.

## Considered Options

- **Hand-label a few frames per Clip**: correct, but slow for an exploratory study.
- **A labelled dataset such as Penn Action**: gives real accuracy, but labels only 13 joints that have to be matched to MediaPipe's 33, has no empty-room footage, and is licensed for academic use only. This remains the natural next step if the mentor wants true accuracy.
