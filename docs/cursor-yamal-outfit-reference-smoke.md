# Cursor task — download official outfit refs and run ONE live smoke test

Goal: prepare the two local official outfit references for the Yamal video and run exactly one real OpenAI image edit smoke test. Do not run the full 16-job batch yet.

## 1. Pull latest

```bash
git pull --ff-only origin main
```

Expected latest commit includes:

- `scripts/fetch_yamal_outfit_references.py`

## 2. Download/import the two official references

Run:

```bash
python scripts/fetch_yamal_outfit_references.py
```

The script uses only these official sources:

### Barcelona home 2025/26

Official product page:

`https://store.fcbarcelona.com/collections/men-kits/products/fc-barcelona-home-amshirt-25-26-ucl`

Official Store CDN image:

`https://store.fcbarcelona.com/cdn/shop/files/HJ4590-456_415227879_D_A_1X1_e3028dab-beb3-4a47-a7bc-0783a5f75462.jpg?v=1751431616&width=1200`

### Spain home 2026

Official RFEF product page:

`https://shop.rfef.es/en-int/products/camiseta-hombre-primera-equipacion`

Official RFEF Store CDN image:

`https://shop.rfef.es/cdn/shop/files/25CM0844-3.png?v=1764595319&width=2000`

Important:

- downloaded third-party image bytes MUST remain under `.local-assets/`;
- NEVER commit these PNG/JPG reference files;
- `import_outfit_reference.py` should update tracked `reference.sha256` in the corresponding `outfit.json` files;
- commit only the resulting tracked metadata changes.

## 3. Verify references

Check that these local files exist:

```text
.local-assets/shared/mascot-outfit-references/barcelona-home/reference.png
.local-assets/shared/mascot-outfit-references/spain-home-2026/reference.png
```

Check that these tracked files now contain non-null reference SHA values:

```text
channel-assets/mascot/outfits/barcelona-home/outfit.json
channel-assets/mascot/outfits/spain-home-2026/outfit.json
```

Do NOT edit branding rules manually unless the import process changed only `reference.sourceUrl` / `reference.sha256`.

Barcelona production rules remain:

- FC Barcelona crest on left chest
- yellow Nike swoosh on right chest
- centered circular Spotify symbol
- NO written `Spotify` word
- no player name / number

Spain 2026 rules remain:

- red base
- fine yellow vertical pinstripes
- Spain crest on left chest
- star above crest
- yellow adidas logo on right chest
- no sponsor / name / number

## 4. Run ONE live smoke test only

Confirm `.env` contains `OPENAI_API_KEY`.

Then run exactly:

```bash
python scripts/mascot_auto_generate.py --pose count-3 --outfit spain-home-2026
```

Do NOT run `prepare_assets.py --prepare` yet.
Do NOT generate the other 15 outfit variants yet.

Expected pipeline:

- original `count-3` pose dimensions: 1122x1402
- API canvas padded without rescale to 1136x1408
- OpenAI Images Edit runs on padded pose + approved mask + Spain reference + canonical mascot
- output cropped back to exactly 1122x1402
- only approved clothing-mask pixels enter the outfit layer
- final outside-mask pixels are identical to the original approved pose
- deterministic QA passes
- vision QA checks Spain kit branding/details
- result becomes `approved-auto` only if both QA stages pass

## 5. Report

Return:

1. `git rev-parse --short HEAD`
2. SHA256 values written for both outfit references
3. local paths of both reference files
4. exact smoke-test result JSON
5. generated variant id/status
6. generated composite path
7. deterministic QA result
8. visual QA result
9. whether any retry occurred
10. `git status --short`

If the smoke test returns `NEEDS_REVIEW`, `ERROR`, `BLOCKED_REFERENCE*`, or branding QA fails:

- STOP;
- do not run the remaining jobs;
- preserve `.local-assets` debug artifacts;
- report the exact error/QA issues.

If the smoke test returns `GENERATED` + `approved-auto`:

- commit and push ONLY tracked metadata/code/generated channel-owned variant files;
- never commit official reference image bytes;
- STOP and report back before running the full batch.
