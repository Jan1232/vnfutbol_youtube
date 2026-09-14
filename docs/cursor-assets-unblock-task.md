# Cursor task — unblock Yamal assets without bypassing editorial approval

Continue from commit `e749847` (or latest `main`). The current asset-prep pipeline is accepted as the base. Do not rewrite it broadly.

Read first:

- `videos/lamine-yamal-new-messi/assets/prepared-assets.json`
- `videos/lamine-yamal-new-messi/assets/asset-prep.json`
- `videos/lamine-yamal-new-messi/assets/source-reuse.json`
- `videos/lamine-yamal-new-messi/assets/assets.json`
- `videos/lamine-yamal-new-messi/scenes/visual-plan.json`
- `videos/lamine-yamal-new-messi/audio/voice.json`
- `videos/lamine-yamal-new-messi/context/entities.json`
- `channel-assets/mascot/pose-masks.json`
- `channel-assets/mascot/poses.json`
- `docs/mascot-outfit-resolution.md`

Do not change script/factcheck/voice audio. Do not create new mascot poses. Do not run AI outfit generation. Do not run `--fetch-external`.

## 1. Remove Yamal hardcoding from mascot sync

`scripts/sync_mascot_assets.py` currently hardcodes `player-lamine-yamal` as `YAMAL_SUBJECT`. This must become generic for future videos.

Rules:

1. If a mascot scene already has `mascot.subject`, use it.
2. For `outfitIntent=current-club` or `national-team`, if no subject is set:
   - inspect `context/entities.json`;
   - if exactly one PLAYER entity exists, use that entity id and freeze it into `scene.mascot.subject`;
   - if zero or more than one PLAYER exists, fail with an actionable message requiring an explicit subject.
3. For `default` and `formal`, no subject is required.
4. Never infer a named player from prose.
5. Add a regression test using a non-Yamal PLAYER id to prove the script is generic.

## 2. Add explicit clothing-mask review workflow

Implement:

```bash
python scripts/review_mascot_masks.py videos/lamine-yamal-new-messi --contact-sheet
python scripts/review_mascot_masks.py videos/lamine-yamal-new-messi --status
```

The contact sheet must include only clothing masks currently blocking mascot pairs for this video (currently 16 pairs, fewer unique poses are possible if a pose appears with multiple outfits).

For every unique pose show three panels:

1. approved base pose;
2. clothing mask alone;
3. base pose with the mask overlaid in semi-transparent red.

Label each row with the `basePose` id and list required outfits for that pose.

Output locally only:

```text
.local-assets/lamine-yamal-new-messi/previews/mascot-mask-review.png
```

Do not commit the contact sheet.

Add explicit approval/rejection commands, but DO NOT run them automatically:

```bash
python scripts/review_mascot_masks.py videos/lamine-yamal-new-messi --approve point-left-two,count-3
python scripts/review_mascot_masks.py videos/lamine-yamal-new-messi --reject shock-one --reason "mask overlaps hand"
```

Approval requirements:

- target mask file exists;
- SHA256 equals `pose-masks.json` value;
- `basePoseSha256` equals current approved pose SHA;
- only then change `status` to `approved`.

Rejection stores `status: rejected` plus reason. Never silently regenerate a rejected mask.

Add offline tests for hash mismatch, stale base pose, explicit approve, explicit reject, and dedupe when one pose is needed by multiple outfits.

## 3. Support source reuse / derived assets

Read `assets/source-reuse.json`.

Goal: do not force the editor to acquire 18 independent source files when several outputs can come from one source.

Extend `prepare_assets.py` so a prepared record can include:

```json
{
  "sourceGroup": "wc2026-final",
  "derivedFrom": "video-wc2026-final-atmosphere",
  "derive": "video-frame-fallback"
}
```

Rules:

- one ingested primary source may feed multiple derived prepared assets;
- never duplicate the source bytes merely because multiple asset ids use it;
- every derived output has its own hash and prepared path;
- preserve provenance to the primary source and original source URL;
- never invent frame timestamps or crop selections;
- when a video-frame derivative needs a timestamp and none is explicitly selected, mark it `NEEDS_SELECTION`, not READY;
- candidate/contact-sheet generation may propose timestamps, but selection remains explicit.

For the current Yamal plan support the three groups already described in `source-reuse.json`:

- `wc2026-final`
- `euro2024-yamal`
- `yamal-barcelona-no10`

The separate official image source should still win over a fallback video frame when a good candidate has been selected.

## 4. Discovery pass, no full external download

After implementing the above, run:

```bash
python scripts/prepare_assets.py videos/lamine-yamal-new-messi --discover
```

Allowed:

- inspect official/public source pages;
- discover candidate image URLs/files when normal HTTP access allows it;
- save local candidate images and contact sheets under `.local-assets/`;
- query video metadata if supported by installed tools.

Not allowed:

- authentication bypass;
- DRM/protection bypass;
- full YouTube/match-footage download;
- `--fetch-external`;
- committing third-party bytes.

If discovery cannot retrieve a candidate, keep `NEEDS_SOURCE_FILE`.

## 5. Draft timeline should tolerate mascot outfit placeholders

`build_timeline.py --allow-placeholders` currently tolerates missing external media but still blocks on a missing mascot outfit variant.

Change draft-only behavior:

- if `basePose` is approved but the requested non-default outfit variant is blocked/missing, `--allow-placeholders` may create the scene using the approved base pose;
- preserve requested outfit id in timeline metadata;
- mark `visual.placeholderOutfit = true` and `visual.prepStatus = "BLOCKED"`;
- final build without `--allow-placeholders` MUST still fail until an approved outfit variant exists.

Do not pretend the outfit exists.

Then run:

```bash
python scripts/build_timeline.py videos/lamine-yamal-new-messi --allow-placeholders
```

The purpose is timing/structure validation only.

## 6. Do not silently auto-partition ambiguous voice/visual splits

Keep current behavior for mappings that are unambiguous, but add support for optional explicit per-scene:

```json
"voiceSourceKeys": ["SCRIPT-014:000"]
```

When present, this field is authoritative.

If multiple visual scenes share one SCRIPT and automatic partitioning cannot map cleanly, fail with `AMBIGUOUS_SCENE_SPLIT` and tell us which scenes need explicit `voiceSourceKeys`.

Do not regenerate voice audio merely to satisfy scene timing.

## 7. Tests and run order

Add/update offline tests, then run:

```bash
python scripts/test_asset_prep.py
python scripts/sync_mascot_assets.py videos/lamine-yamal-new-messi
python scripts/prepare_assets.py videos/lamine-yamal-new-messi --plan
python scripts/review_mascot_masks.py videos/lamine-yamal-new-messi --contact-sheet
python scripts/review_mascot_masks.py videos/lamine-yamal-new-messi --status
python scripts/prepare_assets.py videos/lamine-yamal-new-messi --discover
python scripts/prepare_assets.py videos/lamine-yamal-new-messi --status
python scripts/build_timeline.py videos/lamine-yamal-new-messi --allow-placeholders
python scripts/validate_video.py videos/lamine-yamal-new-messi
```

Do NOT approve/reject masks yourself. Do NOT run `ensure_mascot_variants.py` expecting jobs until mask approval is supplied by the editor. Do NOT run AI generation.

## 8. Report after push

Return:

- commit SHA;
- tests PASS/FAIL;
- local path of `mascot-mask-review.png`;
- unique mask poses awaiting review and their required outfits;
- discovery results: candidates found per external asset;
- how many distinct source files are actually still needed after source reuse;
- list of assets moved from `NEEDS_SOURCE_FILE` to `NEEDS_SELECTION`;
- placeholder timeline scene count and total duration;
- any `AMBIGUOUS_SCENE_SPLIT` cases;
- exact blockers remaining for FINAL timeline.

Push code and committed JSON metadata only. Never push `.local-assets/` contents.
