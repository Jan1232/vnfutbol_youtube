# Cursor task — review boards for Yamal assets

Continue from commit `63eb53e` or latest `main`.

Goal: prepare complete local review boards so the editor can approve mascot clothing masks and choose discovered media candidates without opening dozens of files manually.

Do not change script, factcheck, voice, visual-plan editorial decisions, or source URLs. Do not run `--fetch-external`. Do not approve/reject masks. Do not select candidates automatically. Do not run AI outfit generation.

## 1. Fix mascot mask contact-sheet height

In `scripts/review_mascot_masks.py`, `build_contact_sheet()` currently allocates height with:

```python
height = rows * (panel[1] + label_h) + 40
```

but each row actually consumes `label_h + panel[1] + 8` pixels, and the sheet also starts with a top margin.

Fix the layout so every row is fully visible, including the final row. Keep at least 20 px top and bottom margin. Do not change mask contents or approval state.

Add/adjust an offline test that verifies the output image height is sufficient for all rows and that the last row is not clipped.

Regenerate:

```bash
python scripts/review_mascot_masks.py videos/lamine-yamal-new-messi --contact-sheet
```

Expected local output:

```text
.local-assets/lamine-yamal-new-messi/previews/mascot-mask-review.png
```

## 2. Create one combined candidate review board

Add a command to `scripts/prepare_assets.py`:

```bash
python scripts/prepare_assets.py videos/lamine-yamal-new-messi --candidate-review
```

It must read `prepared-assets.json` and include only assets with `status=NEEDS_SELECTION` that have discovered candidate files.

Create one local image:

```text
.local-assets/lamine-yamal-new-messi/previews/asset-candidate-review.png
```

Layout requirements:

- one clearly separated section/row per asset id;
- asset id shown prominently;
- show the intended `selection` / `selectionNotes` text when available;
- thumbnails must preserve aspect ratio;
- every candidate must have a stable visible label `C1`, `C2`, `C3`, ...;
- underneath each candidate show original dimensions if known and a short filename/source-domain hint;
- do not crop candidates destructively for the review board;
- if an asset has only video metadata / no image thumbnail, show a metadata card instead of failing;
- keep the board readable at normal desktop zoom; if one image would exceed practical dimensions, create paginated files `asset-candidate-review-01.png`, `-02.png`, etc. and print all paths.

Candidate labels must be deterministic across reruns as long as the candidate set does not change. Sort candidates stably by their stored candidate path/url before assigning C numbers.

## 3. Add explicit candidate selection command, but do not run it

Support:

```bash
python scripts/prepare_assets.py videos/lamine-yamal-new-messi \
  --select-candidate player-yamal-barcelona-no10=C3
```

Requirements:

- validate asset is currently `NEEDS_SELECTION`;
- validate requested candidate label exists for that asset;
- copy/ingest the chosen candidate into the existing local source/prepared workflow without committing third-party bytes;
- preserve candidate URL/path provenance and original source URL;
- do not overwrite a different previously selected file silently;
- selection must be idempotent when the same candidate is selected again;
- after selection, run the normal preparation logic needed to reach `READY` where possible;
- for a video candidate that still requires a clip/frame timestamp, candidate selection alone must not invent one; keep `NEEDS_SELECTION` with a precise reason.

Do not execute any `--select-candidate` command in this task.

## 4. Tests

Extend offline tests for:

- mask contact sheet final row is not clipped;
- candidate labels are deterministic;
- review board includes only `NEEDS_SELECTION` assets with candidates;
- selection rejects unknown candidate labels;
- selecting the same candidate twice is idempotent;
- selection never writes third-party files outside `.local-assets/`.

Run:

```bash
python scripts/test_asset_prep.py
python scripts/review_mascot_masks.py videos/lamine-yamal-new-messi --contact-sheet
python scripts/prepare_assets.py videos/lamine-yamal-new-messi --candidate-review
python scripts/validate_video.py videos/lamine-yamal-new-messi
```

## 5. Push/report

Push code and committed metadata only. Never commit `.local-assets/` review images or candidate bytes.

Report:

- commit SHA;
- tests PASS/FAIL;
- exact local path(s) for `mascot-mask-review.png`;
- exact local path(s) for candidate review board(s);
- assets included in the candidate board and their candidate labels;
- confirmation that no masks were approved/rejected and no candidates were selected.
