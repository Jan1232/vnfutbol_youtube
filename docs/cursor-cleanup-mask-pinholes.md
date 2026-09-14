# Cursor task — clean mascot clothing-mask pinholes before approval

Continue from latest `main` after `bdf068d`.

The second mask review fixed the major collar/shoulder clipping, but the reviewed masks still contain small isolated black pinholes / short dark cracks inside otherwise white garment regions. Do not approve the masks yet.

## Goal

Keep the current full-height garment detection, but make masks topologically clean enough for outfit replacement/extraction:

- collar / neckline fabric included;
- both shoulders and sleeves included up to the skin boundary;
- torso included;
- visible shorts included;
- neck, arms, hands and fingers remain excluded;
- intentional large cutouts caused by arms/hands crossing the torso remain excluded;
- tiny isolated holes or short cracks caused by shading/color-classification noise are filled.

## 1. Add conservative enclosed-hole cleanup

In `scripts/generate_clothing_mask.py`, after the current garment classification and existing small morphology pass, add a topology-aware cleanup step.

Rules:

1. Operate on the binary clothing mask only.
2. Find black connected components that are completely enclosed by white mask pixels (components touching the image border are never holes).
3. Fill only small enclosed holes. Use a conservative threshold based on character/mask size, not one hardcoded absolute pixel count. A reasonable starting rule is:
   - `max_hole_area = max(16, int(character_area * 0.0008))`
   - cap it at a small value if necessary after tests.
4. Do not fill large enclosed regions.
5. Do not fill regions connected to exterior background. This is critical because arm/hand cutouts crossing the shirt must remain black.
6. After filling holes, optionally apply at most a 1 px equivalent closing operation restricted to the opaque character alpha. Do not use a large dilate that could swallow hands/fingers.
7. The final mask must still be clipped to the character alpha.

If the short dark cracks are not enclosed components, add only a very small, local closing step (3x3 max) and verify that it does not bridge around hands.

## 2. Add offline regression tests

Add tests covering synthetic masks/images:

- tiny enclosed black hole inside white garment -> filled;
- several tiny enclosed pinholes -> filled;
- large enclosed black region -> preserved;
- black region connected to exterior -> preserved;
- narrow hand/arm-like channel connected to exterior -> preserved;
- cleanup never creates mask pixels outside character alpha.

Keep existing tests passing.

## 3. Regenerate only the 13 reviewed masks

Regenerate these masks only:

- annoyed-two
- celebrate
- count-2
- count-3
- explain-five
- explain-four
- explain-six
- explain-two
- point-left-three
- point-left-two
- point-right-two
- shock-one
- shock-three

Use the existing `--poses` workflow.

All regenerated records must remain `status: generated`.

Do NOT approve masks.
Do NOT run `ensure_mascot_variants.py` expecting approved jobs.
Do NOT run AI outfit generation.

## 4. Rebuild visual review

Run:

```bash
python scripts/test_asset_prep.py
python scripts/generate_clothing_mask.py --poses annoyed-two,celebrate,count-2,count-3,explain-five,explain-four,explain-six,explain-two,point-left-three,point-left-two,point-right-two,shock-one,shock-three
python scripts/prepare_assets.py videos/lamine-yamal-new-messi --plan
python scripts/review_mascot_masks.py videos/lamine-yamal-new-messi --contact-sheet
python scripts/review_mascot_masks.py videos/lamine-yamal-new-messi --status
```

The contact sheet remains local only:

`.local-assets/lamine-yamal-new-messi/previews/mascot-mask-review.png`

## 5. Report

Push code + committed mask metadata/files only. Never commit `.local-assets/`.

Report:

- commit SHA;
- tests PASS/FAIL;
- cleanup algorithm actually used;
- max hole threshold formula/value on these poses;
- all 13 masks remain `generated`;
- path to the new `mascot-mask-review.png`;
- whether any mask still contains visible isolated pinholes/cracks after cleanup.
