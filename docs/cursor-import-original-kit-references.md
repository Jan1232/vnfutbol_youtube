# Cursor task — import original seasonal kit references

Continue from latest `main` after `e70384d`.

Goal: unblock the 16 mascot outfit jobs by adding **real/original kit references** (Image C) for the four production outfits. Do not generate mascot full-edits yet.

Read first:

- `channel-assets/mascot/outfits.json`
- `videos/lamine-yamal-new-messi/context/entities.json`
- `videos/lamine-yamal-new-messi/scenes/visual-plan.json`
- `videos/lamine-yamal-new-messi/assets/mascot-generation.json`
- `scripts/import_outfit_reference.py`
- `scripts/export_mascot_generation.py`
- `scripts/build_mascot_outfit_prompt.py`

## Editorial decisions — do not change

Use exact real kit designs by season/event:

- `barcelona-home` → FC Barcelona HOME **2025/26**
- `spain-home-2022` → Spain HOME **2022** (used for Yamal Spain debut 2023)
- `spain-home-2024` → Spain HOME **EURO 2024**
- `spain-home-2026` → Spain HOME **World Cup 2026**
- `suit-navy` → no Image C required

Keep the current scene mapping exactly as already implemented:

- scene-03 → `spain-home-2026`
- scene-14 → `spain-home-2022`
- scene-16 → `spain-home-2024`
- scene-21 → `spain-home-2026`
- all current-club Yamal mascot scenes → `barcelona-home`

Do not reactivate legacy `spain-home`.

## Source pages used to verify the designs

Use these as authoritative/reference pages in metadata:

### Barcelona 2025/26
Official Barça store:
`https://store.fcbarcelona.com/collections/men-home-kit/products/fc-barcelona-home-amshirt-25-26-ucl`

The 25/26 home jersey uses the real blue/red gradient stripe design. Preserve the actual season look. This is not equivalent to the channel default kit.

### Spain 2022
Official RFEF announcement:
`https://rfef.es/en/news/new-kit-world-cup`

### Spain EURO 2024
Official RFEF page already used in project metadata:
`https://rfef.es/en/noticias/spains-new-kit-for-euro-2024`

### Spain 2026
Prefer official RFEF/FIFA store product page:
`https://shop.rfef.es/en-int/products/camiseta-hombre-primera-equipacion`

Fallback official FIFA store page:
`https://store.fifa.com/es-es/product/adidas-spain-2026-home-jersey-mens`

## 1. Make outfit references a reusable channel-level library

Do not keep the canonical reference images inside one video's folder.

Use local-only storage:

```text
.local-assets/channel/mascot/outfit-references/
  barcelona-home/
  spain-home-2022/
  spain-home-2024/
  spain-home-2026/
```

Each selected reference folder should ultimately contain:

```text
reference.png
source.json
```

`source.json` must contain at least:

```json
{
  "outfit": "...",
  "season": "...",
  "sourcePage": "...",
  "imageSourceUrl": "...",
  "sha256": "...",
  "width": 0,
  "height": 0,
  "selectedAt": "..."
}
```

Do not commit the images. Repo metadata may contain source pages and hashes, but not copyrighted kit image bytes.

## 2. Add reference discovery from source page

Extend or add tooling so we do not have to manually right-click/save product images when the page exposes them in HTML/JSON-LD/Shopify metadata.

Implement:

```bash
python scripts/discover_outfit_reference.py --outfit barcelona-home
python scripts/discover_outfit_reference.py --outfit spain-home-2022
python scripts/discover_outfit_reference.py --outfit spain-home-2024
python scripts/discover_outfit_reference.py --outfit spain-home-2026
```

Behavior:

- read the outfit's authoritative `referenceSourcePage` from `outfits.json`;
- fetch only that page (plus its normal static metadata, no browser automation required);
- extract candidate image URLs from, in this order:
  - JSON-LD product `image`;
  - `og:image` / `twitter:image`;
  - Shopify/product JSON embedded in page HTML;
  - ordinary `<img>` elements associated with the product gallery;
- ignore logos, favicons, social icons, thumbnails below 500 px on the long side, tracking pixels and SVG UI icons;
- download candidates to local-only cache;
- preserve original aspect ratio and bytes where possible;
- never auto-select a candidate.

If an official historical page (especially Spain 2022/2024) has no clean product image, allow an explicit `--candidate-url` fallback, but still keep the official RFEF page as `sourcePage` and record the fallback page/image URL separately.

## 3. Build one review board for the 4 kits

Implement:

```bash
python scripts/review_outfit_references.py --contact-sheet
python scripts/review_outfit_references.py --status
```

Output local-only:

```text
.local-assets/channel/mascot/outfit-references/review/outfit-reference-review.png
```

The board must group candidates by outfit and label them `C1`, `C2`, ...

Show enough resolution to judge:

- front pattern;
- collar;
- sleeve colors;
- shoulder stripes;
- crest/logo/sponsor placement;
- shorts if present.

Prefer clean front-facing shirt/product shots over action photos or model shots.

Do not auto-select.

## 4. Explicit selection/import only

Support:

```bash
python scripts/review_outfit_references.py --select barcelona-home:C2
python scripts/review_outfit_references.py --select spain-home-2022:C1
```

Selection must:

- copy the chosen candidate to `reference.png` in the channel-level local library;
- save `source.json`;
- update repo metadata for the outfit with selected reference SHA256 and provenance, but never commit the image bytes;
- mark `referenceStatus=ready` only after explicit selection.

Do not mutate unrelated outfit fields.

## 5. Update outfit prompt semantics

For outfits with `referenceRequired=true`, `build_mascot_outfit_prompt.py` / exported generation packs must clearly define:

- Image A = canonical mascot identity reference
- Image B = approved base pose
- Image C = selected exact seasonal kit reference
- clothing mask = editable area

Prompt requirements:

- preserve identity and pose from A/B;
- copy the **actual kit design from Image C** into the masked clothing area;
- preserve real season-specific colors, pattern, collar and sleeve design;
- for this project, crest/manufacturer/sponsor may be copied from Image C because the editor explicitly wants the original kit look;
- do not invent a different season, alternate kit, number or player name;
- do not alter head, eyes, hands, skin, body proportions, pose, framing or background;
- output transparent PNG on the same canvas.

For `suit-navy`, keep current no-Image-C behavior.

## 6. Important queue/hash behavior

Changing reference metadata or selected reference hash must invalidate existing exported generation packs/jobs for that outfit.

Do not leave the old `outfitSpecSha256` frozen after changing the outfit reference selection.

After all four references are selected, run in this order:

```bash
python scripts/ensure_mascot_variants.py videos/lamine-yamal-new-messi
python scripts/export_mascot_generation.py videos/lamine-yamal-new-messi --all --force
```

Expected production queue remains:

- 11 × `barcelona-home`
- 2 × `spain-home-2026`
- 1 × `spain-home-2024`
- 1 × `spain-home-2022`
- 1 × `suit-navy`

Total = **16 jobs**.

## 7. Tests

Add offline tests for:

- candidate extraction filters social/favicons/small images;
- review board does not auto-select;
- explicit selection writes `reference.png` + `source.json`;
- selected image SHA enters outfit/job hash inputs;
- changing selected reference makes old job stale;
- export pack includes `outfit-reference.png` only when required;
- `suit-navy` exports without Image C;
- Barcelona remains separate from default-home;
- legacy `spain-home` stays inactive.

Run:

```bash
python scripts/test_mascot_outfit_workflow.py
python scripts/test_asset_prep.py
python scripts/test_generate_clothing_mask.py
```

Do not run AI/API or import any fake full-edit.

## 8. Stop point / report

Push code + metadata only.

Report:

- commit SHA;
- tests PASS/FAIL;
- candidate counts for each of the 4 outfits;
- local path to `outfit-reference-review.png`;
- whether any outfit is still `MISSING_REFERENCE`;
- after selection is NOT required in this task unless editor has explicitly reviewed the board;
- confirm no full-edit generation was performed.

Stop after the review board is produced. The editor will choose C1/C2/etc before generation.