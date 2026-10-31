# Coding standards

Read during review. Each rule is a judgement call that `ruff` and the tests cannot make; each came from a real near-miss.

## Measured Runs are untouchable

A change to `src/bench/live.py`, `run_one.py` or `campaign.py` leaves Sessions and Video phase Runs behaving exactly as before: same frames sent, same timings recorded, same Run file lines. New behaviour goes behind a default that measured Runs keep (as `open_camera(raw=False)` does), and the PR names that default.

## Board scripts check before they touch

A script that changes the Board (copying code with `push-to-board.ps1`, deleting files, starting a process) first checks that no Campaign or Run is running, and makes that check before any change. `push-to-board.ps1` replaces `~/bench/src`, so pushing under a running Campaign swaps its code mid-run.

## Glossary words in prose

Docs, comments, CLI help and messages use the terms in `GLOSSARY.md` and none of their _Avoid_ words: "Demo recording", not "recording"; "Session", not "live Run". Identifiers follow when they name a domain concept.
