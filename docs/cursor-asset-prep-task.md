# Cursor task — asset prep and timeline pipeline

Implement the next production stage for `videos/lamine-yamal-new-messi/` without changing the approved script, voice, factcheck or visual-plan editorial decisions.

Read first:

- `docs/asset-prep-contract.md`
- `videos/lamine-yamal-new-messi/assets/asset-prep.json`
- `videos/lamine-yamal-new-messi/assets/assets.json`
- `videos/lamine-yamal-new-messi/scenes/visual-plan.json`
- `videos/lamine-yamal-new-messi/audio/voice.json`
- `videos/lamine-yamal-new-messi/context/entities.json`
- `docs/mascot-outfit-resolution.md`
- existing mascot scripts in `scripts/`

Do not create a Remotion project in this repository.

## 1. Preserve the local/public boundary

Create local staging only under:

```text
.local-assets/<video-slug>/
```

This folder is gitignored. Never commit third-party photos or match footage merely because a source URL is known.

The committed machine-readable output is:

```text
videos/<video-slug>/assets/prepared-assets.json
```

It contains metadata, hashes and relative local paths, not third-party bytes.

## 2. Implement `scripts/prepare_assets.py`

CLI:

```bash
python scripts/prepare_assets.py videos/lamine-yamal-new-messi --plan
python scripts/prepare_assets.py videos/lamine-yamal-new-messi --status
python scripts/prepare_assets.py videos/lamine-yamal-new-messi --discover
python scripts/prepare_assets.py videos/lamine-yamal-new-messi --ingest
python scripts/prepare_assets.py videos/lamine-yamal-new-messi --prepare
```

Optional explicit external fetch:

```bash
python scripts/prepare_assets.py videos/lamine-yamal-new-messi --fetch-external
```

External downloading must never happen during `--plan`, `--status` or plain validation. `--fetch-external` is explicit opt-in.

### `--plan`

Read `asset-prep.json`, `assets.json`, `visual-plan.json` and create required local directories. Populate/update `prepared-assets.json` with one record for every asset requested by the visual plan plus narration/mascot records when applicable.

Do not erase existing READY selections on rerun.

### `--discover`

For external image source pages, collect plausible large image candidates when technically possible and save them under:

```text
.local-assets/<slug>/candidates/<asset-id>/
```

Create a contact sheet in `previews/`.

Discovery is best-effort. Do not scrape behind authentication or bypass protections. If candidates cannot be discovered, keep `NEEDS_SOURCE_FILE`.

For YouTube/video source URLs, metadata discovery is allowed without downloading the full video. If `yt-dlp` is missing, report it cleanly rather than crashing.

### `--ingest`

Support editor drop-in files named by asset id:

```text
.local-assets/<slug>/inbox/player-yamal-304-celebration.jpg
.local-assets/<slug>/inbox/video-yamal-betis-debut.mp4
```

Move/copy into `source/`, hash the original, probe metadata, and update `prepared-assets.json`.

Never overwrite a different existing source silently. Use hashes.

### `--prepare`

Images:
- preserve originals;
- normalize orientation;
- do not destructively crop the source;
- create a prepared PNG or lossless/high-quality equivalent;
- record width/height;
- store crop/framing metadata separately;
- generate review preview/contact sheet.

Video:
- preserve original;
- ffprobe metadata;
- prepared excerpt H.264, 1920x1080, 30 fps, yuv420p;
- strip source audio by default;
- never invent clip timestamps;
- if no selection exists, status remains `NEEDS_SELECTION`;
- if clip range exists, create prepared excerpt and hash it.

Use ffmpeg/ffprobe through subprocess with clear errors.

## 3. `prepared-assets.json` contract

Each item should support:

```json
{
  "id": "asset-id",
  "type": "PLAYER_PHOTO",
  "status": "READY",
  "sourcePath": ".local-assets/.../source/file.jpg",
  "preparedPath": ".local-assets/.../prepared/file.png",
  "sourceSha256": "...",
  "sha256": "...",
  "width": 1920,
  "height": 1080,
  "durationMs": null,
  "clipStartMs": null,
  "clipEndMs": null,
  "sourceUrl": "...",
  "rightsStatus": "...",
  "usedInScenes": ["scene-..."]
}
```

Allowed prep states:

- `READY`
- `READY_RENDER_SPEC`
- `READY_MASCOT`
- `NEEDS_SELECTION`
- `NEEDS_SOURCE_FILE`
- `MISSING`
- `BLOCKED`

Reruns must be idempotent and preserve manual selections unless source/hash changed.

## 4. Render-only assets

The ids in `asset-prep.json.renderOnlyAssetIds` are not downloads.

Mark them `READY_RENDER_SPEC` when the corresponding `assets.json` record has a non-empty `renderSpec`.

No PNG needs to be generated now. The future Remotion renderer will draw them.

## 5. Materialize mascot requirements from visual-plan

Implement:

```text
scripts/sync_mascot_assets.py
```

The visual plan currently stores `poseIntent` + `outfitIntent`; existing mascot tooling requires concrete `MASCOT` assets with `basePose` and resolved outfit.

For every visual-plan scene containing a mascot:

1. Resolve `poseIntent` only against existing approved poses in `channel-assets/mascot/poses.json`.
2. Never generate or add a new pose.
3. Prefer exact approved pose id when the intent is an exact id.
4. Otherwise match approved pose category/tags/direction.
5. If several approved poses match, choose deterministically but allow variation between scenes. Do not use Python's randomized `hash()`; use stable SHA-256 of scene id to select from sorted candidates.
6. Freeze the chosen id back into `visual-plan.json` as `mascot.basePose` so future runs never silently change casting.
7. Create/dedupe a MASCOT asset by `(basePose, resolvedOutfit)` rather than making duplicate files for every scene.
8. Add the generated mascot asset id back to each scene as `mascot.assetId`.

For `current-club` and `national-team`, set subject to `player-lamine-yamal` and use `context/entities.json`.

Then reuse existing tooling rather than reimplementing it:

```bash
python scripts/resolve_mascot_outfit.py videos/lamine-yamal-new-messi --all
python scripts/ensure_mascot_variants.py videos/lamine-yamal-new-messi
```

`default-home` is immediately reusable from the base pose and needs no clothing layer.

Non-default pairs should be classified by the existing variant system. Since `variants.json` may currently be empty, queue only unique missing `(basePose, resolvedOutfit)` pairs.

Do not fabricate approved variants. Pending generation remains pending.

## 6. Keep current `assets.json` rich schema, fix validation compatibility

`assets.json` is currently richer than the original validator contract. Do NOT throw away provenance/rights/render fields just to satisfy the old validator.

Update `scripts/validate_video.py` backward-compatibly:

- accept assets manifest version 1 and 2;
- keep old v1 source/status values working;
- v2 additionally accepts sources currently used by the project: `official-source`, `major-media`, `render`;
- v2 additionally accepts `planned-render`;
- v2 may omit legacy `tags`, `license`, `author` when provenance is represented by richer fields;
- unknown values still fail;
- metadata stage remains one of the canonical stages; current video uses `assets`.

Make validation stage-aware:

- during `visual-plan`, `assets` or `voice`, an empty/not-yet-final timeline must not cause every `assets.usedInScenes` reference to fail;
- once metadata stage is `timeline`, `draft` or `published`, all scene references must resolve strictly.

Do not weaken strict checks for malformed JSON, duplicate ids, bad pose ids, bad outfit ids or approved variant requirements.

## 7. Build timeline only after prep gate

Implement:

```text
scripts/build_timeline.py
```

Command:

```bash
python scripts/build_timeline.py videos/lamine-yamal-new-messi
```

It must refuse final timeline generation if:

- voice segments are not generated or have null `startMs/endMs`;
- mascot scenes lack concrete `basePose`/asset id;
- a required external asset is `MISSING` or `BLOCKED`;
- an external asset needed by a scene is not READY unless the scene explicitly has a renderer-owned fallback;
- a non-default mascot variant is neither approved/reused nor explicitly pending with a clear blocking report.

Add `--allow-placeholders` for creating a draft timeline with unresolved external media. Placeholder mode must label unresolved visuals in the timeline; it must never pretend they are READY.

## 8. Voice → scene timing

`voice.json` is timing source of truth.

For each visual-plan scene, map `scriptRefs` to contiguous voice segments where `voice.segment.script` matches the script id.

Store in timeline:

```json
{
  "voiceIds": ["voice-..."],
  "voiceSourceKeys": ["SCRIPT-...:000"]
}
```

Scene `start` begins at the first assigned voice segment `startMs / 1000`.
Scene end includes the last assigned voice segment plus its relevant transition/pause, without overlapping the next scene.

If one script id is used by multiple consecutive visual scenes:

- partition only at voice-segment boundaries;
- preserve segment order;
- prefer a balanced contiguous partition;
- never cut in the middle of a WAV merely to make equal scene lengths;
- if there are fewer voice segments than visual scenes, fail with an `AMBIGUOUS_SCENE_SPLIT` report instead of inventing a word-level timestamp.

CTA ids are handled the same way.

## 9. Timeline output

Keep current top-level contract:

```json
{
  "version": 1,
  "fps": 30,
  "width": 1920,
  "height": 1080,
  "scenes": []
}
```

Each scene should carry at least:

```json
{
  "id": "scene-01",
  "start": 0.0,
  "duration": 3.39,
  "script": "SCRIPT-001",
  "voiceIds": ["voice-001"],
  "voiceSourceKeys": ["SCRIPT-001:000"],
  "layout": "full",
  "visual": {
    "type": "VIDEO",
    "asset": "video-wc2026-final-atmosphere"
  },
  "overlay": {...},
  "animation": "slowZoom"
}
```

For mascot scenes preserve:

```json
"visual": {
  "type": "MASCOT",
  "asset": "mascot-...",
  "pose": "approved-pose-id",
  "outfit": "resolved-outfit-id",
  "supportingAsset": "player/photo/video id when present"
}
```

Timeline references asset ids, not absolute filesystem paths.

## 10. Do not touch editorial content

Do not change:

- `script/script.md` text;
- research/factcheck claims;
- MiniMax voice/model/speed;
- generated WAV files;
- visual-plan scene order, overlays, layouts or outfit intent except adding resolved `basePose` / `assetId` fields;
- mascot identity or pose library;
- title/thumbnail concept.

## 11. Tests

Add offline tests with temporary directories. No network in tests.

Minimum coverage:

- plan creates all required prepared records;
- rerun preserves READY/manual selection;
- render-only becomes READY_RENDER_SPEC;
- inbox image/video ingestion hashes safely;
- same source hash does not duplicate;
- changed file is detected;
- no external fetch without explicit flag;
- mascot pose selection is deterministic across runs;
- no new mascot pose can be invented;
- mascot assets dedupe by `(basePose, resolvedOutfit)`;
- default-home requires no variant layer;
- timeline mapping uses generated voice start/end;
- repeated script refs partition by whole voice segments;
- fewer voice segments than scenes returns `AMBIGUOUS_SCENE_SPLIT`;
- validator accepts current assets v2 but still accepts old v1 template;
- stage-aware scene cross-reference validation;
- final strict timeline validation.

## 12. Expected first run

After implementation run only offline/non-network steps first:

```bash
python scripts/sync_mascot_assets.py videos/lamine-yamal-new-messi
python scripts/resolve_mascot_outfit.py videos/lamine-yamal-new-messi --all
python scripts/ensure_mascot_variants.py videos/lamine-yamal-new-messi
python scripts/prepare_assets.py videos/lamine-yamal-new-messi --plan
python scripts/prepare_assets.py videos/lamine-yamal-new-messi --status
python scripts/validate_video.py videos/lamine-yamal-new-messi
```

Do NOT run `--fetch-external` automatically.

Do NOT generate new mascot clothing with an external AI automatically.

Report at the end:

- READY external assets;
- NEEDS_SOURCE_FILE;
- NEEDS_SELECTION;
- READY_RENDER_SPEC;
- mascot reused pairs;
- mascot missing/stale pairs queued for generation;
- whether timeline can be built now;
- exact blockers.

Commit code/manifests/tests, but never commit `.local-assets/` third-party media.
