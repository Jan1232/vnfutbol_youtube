# vnfutbol_youtube

Production-репозиторий YouTube-канала **ВСЕ НА ФУТБОЛ**.

Один ролик живёт в своей папке в `videos/`. Общие ассеты канала лежат в `channel-assets/` и переиспользуются. Итог выпуска — `scenes/timeline.json` для локального Remotion. Сам Remotion в этот репозиторий не входит.

Библиотека маскота **закрыта**. Новые позы не генерируем.

## Что где лежит

| Путь | Зачем |
| --- | --- |
| `channel-assets/` | Общая библиотека канала: маскот, будущие фото, звук, шрифты, шаблоны |
| `channel-assets/mascot/poses/` | Утверждённые позы. Конечный набор |
| `channel-assets/mascot/references/` | Только канон внешности, не рабочие жесты |
| `channel-assets/mascot/poses.json` | Индекс поз: теги, кадрирование, hash, QC |
| `videos/_template/` | Заготовка нового выпуска |
| `videos/<slug>/scenes/timeline.json` | Монтажный план сцены для Remotion |
| `scripts/` | Поиск ассета, создание папки выпуска, валидация |

## Pipeline

```text
IDEA → RESEARCH → SCRIPT → FACTCHECK → VISUAL PLAN → ASSETS → VOICE → TIMELINE → DRAFT
```

Как брать картинку в кадр:

```text
REUSE  →  SEARCH  →  GENERATE
```

1. **REUSE** — сначала готовое из `channel-assets/`.
2. **SEARCH** — для маскота `scripts/find_asset.py`, для остального запись в `assets.json` со `sourceUrl` / `license` / `author`.
3. **GENERATE** — только если библиотека и поиск не закрыли задачу. Новые позы маскота не генерируем. Новую форму собираем как слой одежды поверх неизменяемой позы.

Этапы выпуска:

- **IDEA** — папка `videos/<slug>/`, статус в `metadata.json`
- **RESEARCH** — факты, источники, спорные места
- **SCRIPT** — блоки `SCRIPT-00N`, связанные с `FACT-00N`
- **FACTCHECK** — `CHECK-00N` против сценария
- **VISUAL PLAN** — какие кадры нужны
- **ASSETS** — `assets.json`, маскот только из библиотеки
- **VOICE** — `voice.json` + MiniMax TTS (`scripts/generate_voice.py`)
- **TIMELINE** — `timeline.json`
- **DRAFT** — локальный render, не в git

## Voice Generation

Production TTS — официальный MiniMax HTTP T2A (`speech-2.8-hd`).

Ключ только из environment или локального `.env` (gitignored):

```bash
MINIMAX_API_KEY=<secret>
```

Никогда не коммитьте ключ, `.env` или `*.secret`.

Конфиг канала: `channel-assets/voice/minimax.json`  
Speed `1.16`, pitch `0`, volume `1`, format `wav`. Настройки не менять автоматически.

`text` в `voice.json` — текст сценария. MiniMax получает только `ttsText`  
(после `normalize_russian_tts` + `audio/voice-overrides.json`).

```bash
# Offline contract tests (без API)
python scripts/test_minimax_tts.py
python scripts/test_voice_normalizer.py

# План генерации без запросов
python scripts/generate_voice.py videos/lamine-yamal-new-messi --dry-run

# Inspect одного сегмента
python scripts/generate_voice.py videos/lamine-yamal-new-messi \
  --source-key SCRIPT-011:000 --show

# Точечная перегенерация
python scripts/generate_voice.py videos/lamine-yamal-new-messi \
  --source-key SCRIPT-011:000 --force

# Синтез missing/stale + assemble narration.wav
python scripts/generate_voice.py videos/lamine-yamal-new-messi

python scripts/validate_voice.py videos/lamine-yamal-new-messi
```

Идемпотентность: повторный запуск не перегенерирует сегмент, если совпадают
`textSha256`, `ttsTextSha256`, `settingsSha256`, `renderSha256` и WAV hash.

## Mascot Outfit System

```text
POSE + OUTFIT LAYER = FINAL MASCOT
```

Базовая поза неизменяема. В общей библиотеке хранится только слой одежды с прозрачностью. Полный AI-edit — промежуточный файл, не source of truth.

```text
AI VISUAL PLAN
→ outfitIntent
→ entities.json
→ resolvedOutfit
→ variant lookup
→ REUSE if exists
→ GENERATION JOB if missing
→ AI full edit
→ mask extraction
→ outfit layer
→ approval
→ promote to shared library
→ reuse forever
```

`default-home` — без overlay, берётся исходная поза. Текущий клуб не угадывается из интернета: он приходит из `context/entities.json`.

Правила для visual plan: `docs/mascot-outfit-resolution.md`.

```bash
python scripts/generate_clothing_mask.py --all
python scripts/validate_mascot_masks.py
python scripts/resolve_mascot_outfit.py videos/<slug> --all
python scripts/ensure_mascot_variants.py videos/<slug>
python scripts/find_mascot_variant.py --pose argument --outfit spain-home
python scripts/compose_mascot.py --pose argument --outfit spain-home --output preview.png
```

## Quick Start

```bash
pip install -r requirements.txt

python scripts/validate_assets.py
python scripts/find_asset.py --tag explain
python scripts/create_video.py test-video
python scripts/validate_video.py videos/test-video
```

Другие поиски:

```bash
python scripts/find_asset.py --tag suspicious
python scripts/find_asset.py --category point
python scripts/find_asset.py --prop yellow-card
python scripts/find_asset.py --tag explain --direction right --json
```

## Структура

```text
channel-assets/
  mascot/
    references/
    poses/
    poses.json
    outfits.json
    pose-masks.json
    variants.json
    pose-masks/
    clubs/ national-teams/ formal/
    mascot_master_prompt.md
  players/ coaches/ clubs/ trophies/ stadiums/
  memes/ sounds/ music/ fonts/ templates/
  overlays/ thumbnails/ endcards/
videos/
  _template/
  <slug>/
    research/research.md
    script/script.md
    factcheck/factcheck.md
    assets/assets.json
    audio/voice.json
    scenes/timeline.json
    renders/
scripts/
  validate_assets.py
  find_asset.py
  create_video.py
  validate_video.py
  minimax_tts.py
  generate_voice.py
  assemble_voice.py
  validate_voice.py
  test_minimax_tts.py
channel-assets/voice/minimax.json
```
