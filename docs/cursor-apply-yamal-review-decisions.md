# Cursor task — fix clipped mascot masks and apply approved media selections

Continue from latest `main` after commit `596c141`.

IMPORTANT CORRECTION: the previous version of this task incorrectly said to approve the 13 mascot clothing masks. Do NOT approve them. Visual review found a systematic defect: the masks are clipped at the top and do not reliably include the full collar/neckline and shoulder area of the jersey.

The likely root cause is `scripts/generate_clothing_mask.py`: it ignores all pixels above a fixed `HEAD_RATIO` cut. On waist-up mascot poses that cut can run through the upper garment. The clothing mask must represent the complete editable garment region, not just the torso below an arbitrary Y coordinate.

Do not run external AI outfit generation. Do not run `--fetch-external`. Do not change script/factcheck/voice.

## 1. Fix clothing-mask generation

Update `scripts/generate_clothing_mask.py` so mask generation does NOT use a fixed vertical/head cutoff that can remove garment pixels.

Requirements:

- remove or replace the `HEAD_RATIO` / `head_cut` exclusion;
- detect garment pixels across the entire opaque character bbox;
- preserve the existing dark-skin/head exclusion through garment-color classification rather than a global Y cut;
- the resulting mask must include all visible clothing that may need replacement:
  - collar / neckline fabric;
  - both shoulder caps;
  - sleeves;
  - torso;
  - visible shorts when present;
- do not include head, neck skin, bare arms, hands or fingers;
- antialiased garment edges should not leave obvious uneditable gaps;
- keep the mask on the same full-size canvas as the base pose;
- regenerated masks remain `status: generated`; never auto-approve them.

Do not solve this by blindly dilating the whole silhouette into hands/neck. The seed should still come from garment colors. Small morphology for edge cleanup is fine.

Add offline regression tests using synthetic RGBA fixtures proving:

1. garment pixels in the collar/shoulder region above the old 30% cutoff are included;
2. a dark head/neck above the shirt is excluded;
3. dark arms/hands adjacent to short sleeves are excluded;
4. visible shorts remain included;
5. generated masks stay `generated`, not `approved`.

## 2. Regenerate only the 13 blocking pose masks

Regenerate these masks after the algorithm fix:

- `annoyed-two`
- `celebrate`
- `count-2`
- `count-3`
- `explain-five`
- `explain-four`
- `explain-six`
- `explain-two`
- `point-left-three`
- `point-left-two`
- `point-right-two`
- `shock-one`
- `shock-three`

Use the existing generator one pose at a time or add a generic comma-separated `--poses` option if useful. Do not regenerate unrelated masks unnecessarily.

After regeneration run:

```bash
python scripts/review_mascot_masks.py videos/lamine-yamal-new-messi --contact-sheet
python scripts/review_mascot_masks.py videos/lamine-yamal-new-messi --status
```

Expected local review file:

```text
.local-assets/lamine-yamal-new-messi/previews/mascot-mask-review.png
```

All 13 masks must still await editor approval. Do NOT call `--approve` or `--reject`.

Do NOT run `ensure_mascot_variants.py` expecting generation jobs yet. Outfit generation remains blocked until the regenerated masks are visually approved.

## 3. Apply the already approved MEDIA candidate selections

The following media choices remain approved and are unrelated to the mask correction:

```text
player-yamal-barcelona-no10 = C1
player-yamal-youth-lamasia = C1
player-messi-early-barcelona = C1
coach-hansi-flick = C1
```

Use the existing explicit `--select-candidate` workflow. Run normal image preparation so these can become READY when the current contract allows it.

Do NOT select:

- `video-yamal-euro2024-france-champion = C1` — C1 is a still, while this asset is VIDEO;
- `player-yamal-injury-2026 = C1` — it is a normal portrait and does not communicate injury/load.

## 4. Reuse injury C1 as the hero portrait

The current `player-yamal-injury-2026` C1 is suitable as `player-yamal-hero-portrait`.

Implement/use a generic explicit command:

```bash
python scripts/prepare_assets.py videos/lamine-yamal-new-messi --reuse-candidate player-yamal-hero-portrait=player-yamal-injury-2026:C1
```

Requirements:

- candidate must already exist under this video's `.local-assets/`;
- preserve source asset id, candidate label, original source URL/path and hash provenance;
- no redownload;
- no silent overwrite of different target bytes;
- run normal image preparation for the target;
- third-party bytes remain local only;
- add offline tests for success, missing candidate, unknown target and hash conflict.

Do not hardcode Yamal-specific ids into the implementation.

## 5. Filter page-chrome discovery candidates

Current boards include social/service icons. Filter obvious page chrome before assigning C-labels:

- known hints: facebook, twitter, x-logo, instagram, spotify, discord and equivalent UI/social names;
- tiny square UI images <=256×256 when they clearly look like page chrome;
- do NOT reject all small images globally;
- keep raw discovery provenance even when hidden from review;
- assign C1..Cn after filtering;
- add tests proving social icons are hidden while a small non-square editorial image remains eligible.

Regenerate the candidate review board after filtering.

## 6. Run order

Run:

```bash
python scripts/test_asset_prep.py
```

Regenerate the 13 masks, then:

```bash
python scripts/review_mascot_masks.py videos/lamine-yamal-new-messi --contact-sheet
python scripts/review_mascot_masks.py videos/lamine-yamal-new-messi --status
python scripts/sync_mascot_assets.py videos/lamine-yamal-new-messi
python scripts/resolve_mascot_outfit.py videos/lamine-yamal-new-messi --all
python scripts/prepare_assets.py videos/lamine-yamal-new-messi --plan
```

Apply the four explicit media selections and hero-portrait reuse, then:

```bash
python scripts/prepare_assets.py videos/lamine-yamal-new-messi --prepare
python scripts/prepare_assets.py videos/lamine-yamal-new-messi --candidate-review
python scripts/prepare_assets.py videos/lamine-yamal-new-messi --status
python scripts/build_timeline.py videos/lamine-yamal-new-messi --allow-placeholders
python scripts/validate_video.py videos/lamine-yamal-new-messi
```

Do not approve masks. Do not run AI outfit generation. Do not run final timeline while blockers remain.

## 7. Report

Push code + committed metadata only; never commit `.local-assets/`.

Report:

- commit SHA;
- tests PASS/FAIL;
- confirmation that the fixed generator no longer applies the destructive global head cutoff;
- local path to the regenerated `mascot-mask-review.png`;
- status of all 13 regenerated masks (must be `generated`, not approved);
- selected/READY media assets;
- confirmation EURO video remains unresolved;
- confirmation injury asset remains unresolved;
- confirmation hero portrait reuses injury C1 with provenance;
- updated source/status counts;
- draft timeline placeholder count / duration;
- exact FINAL timeline blockers.
