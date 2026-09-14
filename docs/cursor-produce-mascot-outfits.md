# Cursor task — produce reusable mascot outfit layers

Continue from latest `main` after commit `759b194`.

The 13 clothing masks are approved and `ensure_mascot_variants.py` currently queues 16 non-default pairs. Do not call an external AI provider from Cursor in this task. The goal is to prepare all 16 generation jobs cleanly and create a safe import/review/promote workflow for AI full edits.

Read first:

- `channel-assets/mascot/outfits.json`
- `channel-assets/mascot/poses.json`
- `channel-assets/mascot/pose-masks.json`
- `channel-assets/mascot/variants.json`
- `videos/lamine-yamal-new-messi/assets/mascot-generation.json`
- `scripts/ensure_mascot_variants.py`
- `scripts/build_mascot_outfit_prompt.py`
- `scripts/extract_outfit_layer.py`
- `scripts/compose_mascot.py`
- `scripts/promote_mascot_variant.py`

Do not change mascot identity, poses, masks, script, voice, visual-plan order, outfit resolver semantics, or the editorial meaning of any outfit.

## 1. Keep Barcelona as a distinct outfit

`barcelona-home` is a real distinct outfit and must NOT be aliased to `default-home`, reused as the base pose, or treated as visually equivalent.

Do not add any `renderPolicy=base-pose` shortcut.
Do not reduce the queue by reclassifying Barcelona jobs as reuse.
Do not rewrite `barcelona-home` to `default-home` anywhere in assets or timeline.

The current 16 queued pose + outfit pairs are intentional and should remain generation jobs unless an actually approved matching variant already exists in `variants.json`.

Expected production requirement remains:

- all queued `barcelona-home` pairs need their own approved outfit layers;
- all queued `spain-home` pairs need their own approved outfit layers;
- the queued `suit-navy` pair needs its own approved outfit layer.

Use the outfit descriptions from `outfits.json` as the source of truth. Do not invent season-specific details, sponsor marks, crest details, manufacturers, numbers or text unless the outfit spec is explicitly changed later by the editor.

## 2. Export provider-agnostic generation packs

Implement:

```bash
python scripts/export_mascot_generation.py videos/lamine-yamal-new-messi --all
```

For every pending generation job create a local-only directory:

```text
.local-assets/lamine-yamal-new-messi/mascot-generation/<job-id>/
  canonical-reference.png
  base-pose.png
  clothing-mask.png
  prompt.txt
  job.json
  output/
```

Requirements:

- export ALL current pending jobs, including Barcelona jobs;
- copy inputs only from approved/hash-verified library files;
- `prompt.txt` must use the same provider-agnostic prompt semantics already implemented in `build_mascot_outfit_prompt.py`;
- `job.json` includes job id, pose, outfit, all three input hashes, expected output filename and target paths;
- never commit `.local-assets/`;
- do not alter queue status merely by exporting;
- no AI/API calls.

The expected AI full-edit filename should be:

```text
output/full-edit.png
```

## 3. Import and validate an AI full edit

Implement generic CLI:

```bash
python scripts/import_mascot_full_edit.py videos/lamine-yamal-new-messi mascot-job-XXX \
  --input .local-assets/.../output/full-edit.png
```

Validation before import:

- job still exists and is `pending` or `generated-review`/equivalent pre-review state;
- current pose/mask/outfit hashes still equal the hashes frozen in the job;
- input is PNG/RGBA-readable;
- canvas dimensions exactly equal the approved base pose;
- image is not empty;
- reject silent overwrite when different bytes already exist.

Then:

1. copy/save the full edit to `job.targetFullEdit` inside the video folder;
2. run the same logic as `extract_outfit_layer.py` to produce `job.targetLayer`;
3. compose `original base pose + extracted layer` into a local review image;
4. update job status to `needs-review`;
5. record SHA256 of full edit, extracted layer and composed preview.

Do **not** promote automatically.

Generated full edits/layers for the video may be committed only if the existing repository policy permits generated channel-owned media. Review previews stay local.

## 4. Build outfit review board

Implement:

```bash
python scripts/review_mascot_variants.py videos/lamine-yamal-new-messi --contact-sheet
python scripts/review_mascot_variants.py videos/lamine-yamal-new-messi --status
```

For each `needs-review` job show one row with four panels:

1. original approved base pose;
2. AI full edit;
3. extracted transparent outfit layer on neutral checker/dark preview background;
4. final composition `base + layer`.

Label with:

- job id;
- pose id;
- outfit id;
- status.

Output local-only:

```text
.local-assets/lamine-yamal-new-messi/previews/mascot-variant-review.png
```

## 5. Explicit approval and promotion

Support explicit commands only:

```bash
python scripts/review_mascot_variants.py videos/lamine-yamal-new-messi --approve mascot-job-001,mascot-job-002
python scripts/review_mascot_variants.py videos/lamine-yamal-new-messi --reject mascot-job-003 --reason "identity drift / bad clothing boundary"
```

Approval requirements:

- status is `needs-review`;
- full edit/layer hashes match job metadata;
- frozen pose/mask/outfit hashes are still current;
- extracted layer exists and has non-zero alpha.

Approval changes only the job status to `approved`.

Then use existing `promote_mascot_variant.py` to promote approved jobs into `channel-assets/mascot/...` and `variants.json`.

Do not combine approval and promotion into one automatic action.

Rejection stores reason and does not destroy outputs.

## 6. Tests

Add offline tests for:

- all pending jobs remain exportable, including `barcelona-home`;
- generation pack hash verification;
- import rejects wrong dimensions;
- import rejects stale job hashes;
- import creates layer + composed preview;
- approval requires `needs-review`;
- rejection preserves files;
- promotion still refuses unapproved job;
- no code path aliases `barcelona-home` to `default-home`.

Run:

```bash
python scripts/test_asset_prep.py
python scripts/test_generate_clothing_mask.py
python scripts/ensure_mascot_variants.py videos/lamine-yamal-new-messi
python scripts/export_mascot_generation.py videos/lamine-yamal-new-messi --all
```

Do not import fake outputs just to satisfy production state. Do not run AI generation.

## 7. Report

Push code + committed JSON metadata only. Never push `.local-assets/`.

Report:

- commit SHA;
- tests PASS/FAIL;
- counts from `ensure_mascot_variants`;
- exact pending AI jobs (expected: 16 unless an approved variant genuinely exists already);
- local generation-pack paths for all pending jobs;
- confirm Barcelona remains a distinct generated outfit and was not aliased to default-home;
- whether import/review/promote workflow is ready;
- exact next manual/external step required to obtain the `full-edit.png` files.
