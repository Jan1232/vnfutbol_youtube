# Video folder

Один выпуск = одна папка в `videos/`. Общие ассеты канала лежат в `channel-assets/` и сюда не копируются.

## Pipeline

IDEA → RESEARCH → SCRIPT → FACTCHECK → VISUAL PLAN → ASSETS → VOICE → TIMELINE → DRAFT

1. `research/research.md` — факты, источники, спорные места.
2. `script/script.md` — текст ролика, блоки `SCRIPT-00N` ссылаются на `FACT-00N`.
3. `factcheck/factcheck.md` — проверка утверждений сценария.
4. `assets/assets.json` — что попадает в кадр. Маскот брать из библиотеки через `scripts/find_asset.py`, не генерировать новые позы.
5. `audio/voice.json` — реплики и паузы. `audio` / `duration` заполняются после TTS.
6. `scenes/timeline.json` — монтажный план для локального Remotion.
7. `renders/` — локальные черновики, в git не кладём.

Проверка папки:

```bash
python scripts/validate_video.py videos/<slug>
```
