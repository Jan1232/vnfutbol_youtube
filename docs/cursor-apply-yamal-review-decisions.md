# Cursor task — apply approved Yamal review decisions

Continue from latest `main` after commit `596c141`.

This task applies explicit editorial decisions made after visual review of:

- `.local-assets/lamine-yamal-new-messi/previews/mascot-mask-review.png`
- `.local-assets/lamine-yamal-new-messi/previews/asset-candidate-review.png`

Do not reinterpret these decisions. Do not select additional candidates automatically. Do not run `--fetch-external`. Do not run external AI outfit generation.

## 1. Approve the reviewed mascot clothing masks

The following 13 unique clothing masks were visually reviewed and approved:

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

Use the existing explicit approval command so integrity checks remain authoritative:

```bash
python scripts/review_mascot_masks.py videos/lamine-yamal-new-messi --approve annoyed-two,celebrate,count-2,count-3,explain-five,explain-four,explain-six,explain-two,point-left-three,point-left-two,point-right-two,shock-one,shock-three
```

Do not approve any other masks.

Then run:

```bash
python scripts/ensure_mascot_variants.py videos/lamine-yamal-new-messi
```

Expected result: the previously blocked non-default mascot pairs should become generation jobs. Do not execute the jobs or call any AI provider. Report the exact unique job count and pair list.

## 2. Apply explicit candidate selections

Select these reviewed candidates:

```text
player-yamal-barcelona-no10 = C1
player-yamal-youth-lamasia = C1
player-messi-early-barcelona = C1
coach-hansi-flick = C1
```

Use the existing `--select-candidate` workflow. After selection, run preparation as appropriate so image assets become READY if their local files and metadata satisfy the existing contract.

### Do NOT select these candidate records for their current asset

`video-yamal-euro2024-france-champion`: do not select C1 as fulfillment of this VIDEO asset. C1 is a still image, while the visual plan currently requests match footage. Keep the VIDEO asset unresolved until a real video source/excerpt is supplied.

`player-yamal-injury-2026`: do not select C1 for the injury asset. The image is a normal Yamal portrait and does not visually support the injury/load scene. Keep the injury asset unresolved.

## 3. Reuse the rejected injury candidate as the hero portrait

Although `player-yamal-injury-2026=C1` is unsuitable for an injury scene, it is a strong contemporary Yamal portrait and should be reused for:

`player-yamal-hero-portrait`

Add a generic, explicit cross-asset candidate reuse operation rather than manually duplicating undocumented bytes. Preferred CLI:

```bash
python scripts/prepare_assets.py videos/lamine-yamal-new-messi --reuse-candidate player-yamal-hero-portrait=player-yamal-injury-2026:C1
```

Requirements:

- source candidate must already exist under this video's `.local-assets/` tree;
- target and source candidate ids/labels must be explicit;
- preserve provenance: source asset id, candidate label, original source URL and candidate path;
- do not download again;
- do not overwrite an existing different target source silently;
- image may be copied into the target's local `source/` path or referenced safely, but do not commit third-party bytes;
- run normal image preparation for the target so `player-yamal-hero-portrait` can become READY;
- add offline tests for success, missing candidate, unknown target, and overwrite/hash conflict.

This CLI should remain generic for future videos; do not hardcode Yamal ids.

## 4. Filter obvious page-chrome candidates from review boards

Current discovery/review boards include 64×64 social/service icons (Facebook, X, Instagram, Spotify, Discord). They are not editorial media candidates and should not consume C-labels.

Improve candidate review filtering conservatively:

- exclude known page-chrome/social icon candidates based on filename/URL hints such as `facebook`, `twitter`, `x-logo`, `instagram`, `spotify`, `discord`, and equivalent obvious UI asset names;
- exclude tiny square UI images when both dimensions are <= 256 px and the candidate looks like page chrome;
- do NOT globally reject all small images: historical/editorial imagery may be modest resolution;
- assign C1..Cn only after filtering so labels shown to the editor refer to meaningful media;
- preserve the raw discovered candidate list/provenance even if a candidate is hidden from the review board;
- add offline tests proving social icons are hidden while a small non-square editorial image remains reviewable.

Regenerate the candidate review board after filtering. It is okay if the previously selected content images become the only visible candidates for several assets.

## 5. Prepare and refresh manifests

After applying the approved decisions, run:

```bash
python scripts/test_asset_prep.py
python scripts/sync_mascot_assets.py videos/lamine-yamal-new-messi
python scripts/resolve_mascot_outfit.py videos/lamine-yamal-new-messi --all
python scripts/ensure_mascot_variants.py videos/lamine-yamal-new-messi
python scripts/prepare_assets.py videos/lamine-yamal-new-messi --plan
```

Important: `--plan` must not erase the READY candidate selections or cross-asset reuse selection.

Then run the explicit selections if they were not already applied before `--plan`:

```bash
python scripts/prepare_assets.py videos/lamine-yamal-new-messi --select-candidate player-yamal-barcelona-no10=C1
python scripts/prepare_assets.py videos/lamine-yamal-new-messi --select-candidate player-yamal-youth-lamasia=C1
python scripts/prepare_assets.py videos/lamine-yamal-new-messi --select-candidate player-messi-early-barcelona=C1
python scripts/prepare_assets.py videos/lamine-yamal-new-messi --select-candidate coach-hansi-flick=C1
python scripts/prepare_assets.py videos/lamine-yamal-new-messi --reuse-candidate player-yamal-hero-portrait=player-yamal-injury-2026:C1
```

Then:

```bash
python scripts/prepare_assets.py videos/lamine-yamal-new-messi --prepare
python scripts/prepare_assets.py videos/lamine-yamal-new-messi --status
python scripts/build_timeline.py videos/lamine-yamal-new-messi --allow-placeholders
python scripts/validate_video.py videos/lamine-yamal-new-messi
```

Do not run final timeline yet if blockers remain.

## 6. Final report

Push code + committed metadata only. Never commit `.local-assets/`.

Report:

- commit SHA;
- tests PASS/FAIL;
- approved mask count;
- mascot generation jobs count and exact pose+outfit pairs;
- READY external/local image assets after selections;
- confirmation that `video-yamal-euro2024-france-champion` remains unresolved as VIDEO;
- confirmation that `player-yamal-injury-2026` remains unresolved;
- confirmation that `player-yamal-hero-portrait` reused injury C1 with provenance;
- updated distinct source files still needed;
- updated `NEEDS_SOURCE_FILE`, `NEEDS_SELECTION`, READY counts;
- draft timeline placeholder count and total duration;
- exact blockers remaining for FINAL timeline.
