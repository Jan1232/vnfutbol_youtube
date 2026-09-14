# Cursor task — seasonal/original mascot kits with visual references

Continue from current `main` after commit `beca92e`.

Goal: keep the 16 mascot generation jobs, but make the team kits historically and visually correct. Do not generate AI images in this task. Prepare exact outfit specs + local reference workflow so the external image generator copies the real kit design rather than inventing a generic one.

## 1. Outfit policy

### FC Barcelona

Keep the outfit id:

`barcelona-home`

but make it explicitly the **official FC Barcelona home kit 2025/26**.

Official source page:

`https://store.fcbarcelona.com/collections/men-home-kit/products/fc-barcelona-home-amshirt-25-26-ucl`

Official description to preserve in metadata:
- season: `2025/26`
- iconic blaugrana home design;
- blue/red gradient effect across the stripes;
- official crest on left chest;
- Nike mark on right chest;
- Spotify sponsor/front branding as shown on the official reference;
- dark/blue home shorts from the same 2025/26 kit.

This is NOT equivalent to `default-home`.

Set policies for this outfit to reproduce the real reference:

```json
"referenceRequired": true,
"crestPolicy": "match-reference",
"manufacturerPolicy": "match-reference",
"sponsorPolicy": "match-reference"
```

Do not add player name or player number unless explicitly requested by a future scene.

### Spain

Replace the single generic `spain-home` concept with three historical/current outfit ids:

1. `spain-home-2022`
   - used for Lamine Yamal's Spain debut in September 2023;
   - official kit launched for the 2022 World Cup and still used in the 2023 window;
   - source: `https://rfef.es/en/news/new-kit-world-cup`
   - design anchor: deep/intense red first kit, national-flag reference on collar.

2. `spain-home-2024`
   - used for EURO 2024 scenes;
   - source: `https://rfef.es/en/noticias/spains-new-kit-for-euro-2024`
   - design anchor: red base, yellow trim/details, yellow adidas stripes/badge details, carnation motif on back collar, subtle wavy motif in shirt base.

3. `spain-home-2026`
   - current Spain home outfit for 2026 / World Cup 2026 scenes;
   - source: `https://rfef.es/en/noticias/A-new-kit-for-a-new-dream`
   - design anchor: red base with fine yellow vertical pinstripes; `España` on back collar; official 2026 home design.

For Spain outfits:

```json
"referenceRequired": true,
"crestPolicy": "match-reference",
"manufacturerPolicy": "match-reference",
"sponsorPolicy": "omit"
```

The old generic `spain-home` must not remain active after migration. There are no approved generated variants for it, so after all references in current video data are migrated it may be removed from `outfits.json` or retained only as `active:false` legacy metadata if validation needs a migration bridge. Final production data must not resolve to it.

### Formal outfit

`suit-navy` remains prompt-based and does not require an external outfit reference.

## 2. Scene-to-outfit mapping for Yamal video

Do not infer this from prose. Apply exactly:

- scene-03 / pose `point-left-two` / World Cup 2026 -> `spain-home-2026`
- scene-14 / pose `count-2` / Spain senior debut 2023 -> `spain-home-2022`
- scene-16 / pose `count-3` / EURO 2024 -> `spain-home-2024`
- scene-21 / pose `celebrate` / World Cup 2026 -> `spain-home-2026`

All current-club mascot scenes remain `barcelona-home`, which now means the official 2025/26 home kit.

Update:
- `videos/lamine-yamal-new-messi/scenes/visual-plan.json`
- `videos/lamine-yamal-new-messi/assets/assets.json`
- `videos/lamine-yamal-new-messi/context/entities.json`

Rules:
- currentClub outfit stays `barcelona-home`;
- nationalTeam current outfit becomes `spain-home-2026`;
- historical national-team scenes 14 and 16 must use `outfitIntent: explicit` + explicit outfit id;
- scene 03 and scene 21 may keep `national-team` intent and resolve through the entity to `spain-home-2026`;
- mascot asset ids/tags must reflect the resolved outfit id exactly.

Expected Spain asset ids after sync:

```text
mascot-point-left-two__spain-home-2026
mascot-count-2__spain-home-2022
mascot-count-3__spain-home-2024
mascot-celebrate__spain-home-2026
```

## 3. Local outfit reference registry

Implement a generic local-only outfit reference workflow.

Add:

```bash
python scripts/import_outfit_reference.py \
  --outfit barcelona-home \
  --input /path/to/reference.png \
  --source-url "https://store.fcbarcelona.com/collections/men-home-kit/products/fc-barcelona-home-amshirt-25-26-ucl"
```

And equivalent for the three Spain outfit ids.

Store under gitignored shared local storage, reusable across videos:

```text
.local-assets/shared/mascot-outfit-references/<outfit-id>/
  reference.png
  meta.json
```

`meta.json` must include:
- outfit id;
- source URL/page;
- sha256;
- width/height;
- importedAt;
- rights note: `official visual reference; do not commit third-party image`.

Requirements:
- PNG/JPEG input accepted, normalize saved copy to PNG;
- reject unreadable/empty image;
- reject silent overwrite with different bytes unless explicit `--replace`;
- never commit these reference images;
- reference image is for AI guidance only, not for direct publication/render.

Do NOT automatically scrape/download the official pages in this task. The editor will supply the four reference images locally.

## 4. Generation packs must include Image C

Update `scripts/export_mascot_generation.py`.

For any outfit with `referenceRequired=true`, export must fail clearly if the local outfit reference is missing.

Generation pack becomes:

```text
.local-assets/lamine-yamal-new-messi/mascot-generation/<job-id>/
  canonical-reference.png
  base-pose.png
  clothing-mask.png
  outfit-reference.png
  prompt.txt
  job.json
  output/
```

`outfit-reference.png` is copied from the shared local outfit reference registry.

`job.json` must freeze `outfitReferenceSha256` in addition to existing pose/mask/outfit hashes.

Import of full edit must reject a job if the frozen reference hash no longer matches the current local reference.

`suit-navy` has no `referenceRequired`, so its generation pack continues without Image C.

## 5. Prompt semantics

Update `build_mascot_outfit_prompt.py` so it is policy-driven, not hardcoded to `No sponsor text / No manufacturer logo`.

For referenced kits the prompt must contain:

```text
Image A: canonical mascot identity reference
Image B: approved base pose
Image C: official outfit visual reference

Preserve exact identity from A.
Preserve exact pose, gesture, body geometry, hands and framing from B.
Change ONLY the clothing region defined by the approved mask.
Reproduce the real kit design from Image C as faithfully as possible: colors, pattern, collar, sleeve design and official visual marks according to outfit policies.
Do not invent marks or text not visible in Image C.
Do not add player name or number unless explicitly requested.
Transparent background. Same canvas/composition.
```

Policy rendering:
- `match-reference`: reproduce the visible element from Image C;
- `omit`: do not add that category;
- no unconditional sponsor/logo prohibition for official kits.

The generation description may help disambiguate the kit, but Image C is the primary visual source.

## 6. Rebuild queue after outfit migration

Because outfit specs and some outfit ids change, the existing `mascot-generation.json` hashes/packs are stale.

After code/data migration run in this order:

```bash
python scripts/test_asset_prep.py
python scripts/test_generate_clothing_mask.py
python scripts/test_mascot_outfit_workflow.py

python scripts/sync_mascot_assets.py videos/lamine-yamal-new-messi
python scripts/resolve_mascot_outfit.py videos/lamine-yamal-new-messi --all
python scripts/ensure_mascot_variants.py videos/lamine-yamal-new-messi
```

Expected total stays:

```text
jobs=16
reused=8
blocked_mask=0
```

Expected outfit distribution among 16 jobs:
- `barcelona-home`: 11
- `spain-home-2026`: 2
- `spain-home-2024`: 1
- `spain-home-2022`: 1
- `suit-navy`: 1

Do not AI-generate anything yet.

Old local generation packs created before this migration are stale. Do not silently reuse them. Export should overwrite/rebuild a pack only when its frozen job hashes match the new queue, otherwise require explicit rebuild/clean behavior.

## 7. Tests

Add offline tests for:
- importing an outfit reference;
- missing local reference blocks export for `referenceRequired=true`;
- `suit-navy` can export without Image C;
- generation pack includes `outfit-reference.png` and frozen hash;
- changing reference invalidates import of the old job;
- sponsor/manufacturer/crest prompt policy is rendered correctly;
- no hardcoded Barcelona/Spain logic in generic helper code;
- historical scene explicit outfit survives resolver/sync;
- current national-team entity resolves to `spain-home-2026`.

## 8. Do not do these things

- Do not run external AI/API.
- Do not generate full edits.
- Do not commit official kit reference images.
- Do not simplify Barcelona back to generic stripes.
- Do not use Barcelona 26/27.
- Do not use Spain 2026 kit in the EURO 2024/debut-2023 mascot scenes.
- Do not change approved mascot poses/masks.
- Do not change script or voice.

## 9. Final report

Push code + JSON/text metadata only.

Report:
- commit SHA;
- tests PASS/FAIL;
- final outfit ids and seasons;
- exact scene -> outfit mapping for scenes 03/14/16/21;
- ensure queue counts + outfit distribution;
- which four local outfit references are still missing/present;
- exact commands the editor must run to import the four reference images;
- whether generation packs can be exported immediately or are blocked only by missing reference images.
