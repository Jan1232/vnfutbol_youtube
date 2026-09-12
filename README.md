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
3. **GENERATE** — только если библиотека и поиск не закрыли задачу. Для маскота этот шаг закрыт.

Этапы выпуска:

- **IDEA** — папка `videos/<slug>/`, статус в `metadata.json`
- **RESEARCH** — факты, источники, спорные места
- **SCRIPT** — блоки `SCRIPT-00N`, связанные с `FACT-00N`
- **FACTCHECK** — `CHECK-00N` против сценария
- **VISUAL PLAN** — какие кадры нужны
- **ASSETS** — `assets.json`, маскот только из библиотеки
- **VOICE** — `voice.json`, TTS позже
- **TIMELINE** — `timeline.json`
- **DRAFT** — локальный render, не в git

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
```
