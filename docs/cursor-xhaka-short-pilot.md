# Cursor task — first end-to-end Shorts pilot: Granit Xhaka COVID-certificate case

## Goal

Run the existing content-factory pipeline on a short vertical video and stop at sensible editor checkpoints.

Video:

`videos/granit-xhaka-covid-certificate-short/`

Do NOT touch or continue the Lamine Yamal video in this task.

The editorial/research/script/factcheck/visual-plan files are already prepared. Treat them as source of truth.

## 0. Pull and inspect

```bash
git pull --ff-only origin main
git log -3 --oneline
git status --short
```

Do not delete unrelated untracked local files.

## 1. Shorts format support — minimal, reusable, backwards compatible

Before generating timeline, check whether the current timeline/validation flow carries canvas metadata from `metadata.json`.

For a video with:

```json
{
  "format": "shorts",
  "canvas": {"width":1080,"height":1920,"fps":30},
  "hardMaxDurationSec":72
}
```

ensure:

1. `build_timeline.py` writes at timeline root:
   - `format`
   - `canvas.width`
   - `canvas.height`
   - `canvas.fps`
   - `aspectRatio`
2. Existing long-form videos remain unchanged/default-compatible.
3. `validate_video.py` / timeline validation checks:
   - Shorts total duration <= `hardMaxDurationSec` if the field exists.
   - Canvas for shorts is portrait, width < height.
4. Do not invent a separate duplicate Shorts pipeline. Reuse existing scripts with metadata-driven format.

Add small regression tests. No Remotion redesign in this task.

## 2. Voice

Use the existing stable MiniMax setup. First:

```bash
python scripts/generate_voice.py videos/granit-xhaka-covid-certificate-short --dry-run
```

Inspect the generated/synced `audio/voice.json`.

Then synthesize:

```bash
python scripts/generate_voice.py videos/granit-xhaka-covid-certificate-short
```

Requirements:

- reuse the channel's current stable MiniMax voice config;
- do not alter voice model/profile globally;
- target narration must remain <= 72 seconds;
- if narration > 72 sec: STOP, report actual duration; do not arbitrarily speed up voice or cut the presumption-of-innocence line;
- preserve natural pauses appropriate to Shorts, but no long dead air.

## 3. Mascot

This pilot uses ONLY `default-home`.

Important:

- no outfit API generation;
- no Barcelona/Spain/Sunderland/Switzerland kit generation;
- use existing approved pose PNGs directly;
- use only poses already frozen in `visual-plan.json`;
- do not create new mascot poses.

This is intentional: the pilot is testing the full content pipeline, not outfit generation.

## 4. Assets plan

Run:

```bash
python scripts/prepare_assets.py videos/granit-xhaka-covid-certificate-short --plan
```

Expected external media requirement should be essentially one reusable Xhaka photo:

`player-xhaka-current`

All evidence cards / certificate graphic / date timeline are renderer-owned assets and must NOT require third-party screenshot bytes.

Then:

```bash
python scripts/prepare_assets.py videos/granit-xhaka-covid-certificate-short --discover
python scripts/prepare_assets.py videos/granit-xhaka-covid-certificate-short --candidate-review
```

Do NOT auto-select external photo candidates.

If candidate discovery succeeds, give the editor the exact path(s) to the review board and STOP external selection there.

If the official Swiss FA page yields no usable image candidates, try the official Sunderland fallback page already stored in assets.json. Do not use random fan reposts as primary source.

## 5. Draft timeline

After narration exists, build:

```bash
python scripts/build_timeline.py videos/granit-xhaka-covid-certificate-short --allow-placeholders
```

Timeline should be 1080x1920 / 30 fps and use the eight editorial scenes from visual-plan.

Scene boundaries should follow actual voice timings rather than the initial estimated durations.

The 6→8→9 November diagram is the main visual retention beat and should get enough screen time to read on a phone.

## 6. Validate

Run relevant offline tests plus:

```bash
python scripts/validate_video.py videos/granit-xhaka-covid-certificate-short
python scripts/prepare_assets.py videos/granit-xhaka-covid-certificate-short --status
```

If validation requires final external selection, draft placeholder status is acceptable at this checkpoint; report it clearly.

## 7. Content safety / fact rules

Do not rewrite these into stronger claims:

GOOD:
- possible fake certificate
- prosecutors opened proceedings
- according to Blick
- chronology raises questions
- route was physically possible
- guilt has not been established
- presumption of innocence applies

BAD:
- Xhaka forged/bought a fake certificate (as fact)
- doctor issued a fake certificate to him (as fact)
- the 6/8/9 chronology proves fraud
- prison/disqualification is inevitable

Do not remove SCRIPT-006 or SCRIPT-007 to shorten the Short.

## 8. Commit policy

Commit:
- voice.json metadata
- source-side JSON/MD changes
- timeline.json
- code/tests for generic Shorts metadata support
- renderer-owned metadata/specs

Do not commit:
- third-party Xhaka photo bytes
- external article screenshots
- .local-assets
- API secrets

Audio policy: follow the repository's existing policy for generated narration; do not change gitignore behavior in this task.

## 9. Stop/report checkpoint

Do NOT attempt a final render yet.

Return:

1. HEAD SHA
2. narration duration
3. voice segment count / generated / reused / failed
4. timeline duration + canvas
5. validate_video result
6. prepare-assets status summary
7. candidate review board path for `player-xhaka-current`
8. unresolved assets
9. git status
10. list of committed files

Push the commit, then STOP for editor review.
