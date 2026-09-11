# vnfutbol_youtube

Продакшен-репозиторий YouTube-канала **ВСЕ НА ФУТБОЛ**.

Это уже не папка с картинками: канон маскота отделён от рабочей библиотеки поз, у каждого ассета есть запись в манифесте, а скрипт проверяет, что файлы не разъехались.

## Структура

```text
channel-assets/
  mascot/
    references/                 канон внешности, не рабочие позы
      mascot_reference_main.png
      mascot_reference_hips.png
    poses/                      утверждённая библиотека по категориям
      neutral/
      explain/
      count/
      point/
      ...
    poses.json                  индекс для визуального плана
    mascot_master_prompt.md
  overlays/                     будущие плашки и lower-thirds
  thumbnails/                   будущие обложки
  endcards/                     будущие концовки
scripts/
  validate_assets.py
```

## Маскот

`references/` хранит только эталоны идентичности.

- `mascot_reference_main.png` — канон: анфас, руки вдоль тела, цвета `#81162D` / `#172146`.
- `mascot_reference_hips.png` — вспомогательный эталон кистей, таза и шорт.

Все `think_*`, `count_*`, карточки, мяч и остальные жесты лежат в `poses/<category>/`.

Новые позы не генерируем, пока библиотека закрывает монтаж. Если всё же нужна новая — брать **только** `mascot_reference_main.png` как source of truth, не предыдущую позу.

## Как выбирать ассет

Не вспоминать имена файлов, а фильтровать `poses.json` по тегам.

```json
{
  "id": "count-2",
  "file": "poses/count/count_2.png",
  "category": "count",
  "tags": ["two", "list", "number", "explain"],
  "approved": true,
  "transparent": true,
  "handsVerified": true
}
```

Примеры:

- список из трёх пунктов → `count`
- «смотри повтор» → `point` + `replay` / `look`
- жёлтая / красная → `card`
- обращение в камеру → `you`

`handsVerified` — ручной QC-флаг. Скрипт пальцы не проверяет.

## Проверка

```bash
pip install -r requirements.txt
python scripts/validate_assets.py
```

Скрипт проверяет PNG, настоящий alpha-channel, допустимые размеры, отсутствие дубликатов имён и что каждый файл из `poses/` есть в `poses.json`.
