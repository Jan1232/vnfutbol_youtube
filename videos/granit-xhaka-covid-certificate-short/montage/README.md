# Montage package — granit-xhaka-covid-certificate-short

READY FOR EDITING. No final MP4 render in this package.

- Canvas: 1080x1920 @ 30 fps
- Duration: 67.801 sec
- Draft: False
- Scenes: 8

## File map

| Slot | Put this file |
|---|---|
| `audio/narration.wav` | Full assembled narration |
| `mascot/scene-01.png` | Approved identity-lock mascot for scene-01 |
| `mascot/scene-02.png` | Approved identity-lock mascot for scene-02 |
| `mascot/scene-03.png` | Approved identity-lock mascot for scene-03 |
| `mascot/scene-04.png` | Approved identity-lock mascot for scene-04 |
| `mascot/scene-06.png` | Approved identity-lock mascot for scene-06 |
| `mascot/scene-07.png` | Approved identity-lock mascot for scene-07 |
| `mascot/scene-08.png` | Approved identity-lock mascot for scene-08 |
| `photos/xhaka-switzerland.path.txt` | Pointer to local prepared Switzerland photo (binary not in git) |
| `photos/xhaka-sunderland.path.txt` | Pointer to local prepared Sunderland photo (binary not in git) |
| `graphics/scene-03.png` | Rendered `stat-xhaka-spokesman-date-correction` 1080x1920 |
| `graphics/scene-04.png` | Rendered `stat-xhaka-nov-6-8-9-chronology` 1080x1920 |
| `graphics/scene-05.png` | Rendered `stat-xhaka-nov-6-8-9-route` 1080x1920 |
| `graphics/scene-06.png` | Rendered `text-doctor-lawyer-statement` 1080x1920 |
| `graphics/scene-07.png` | Rendered `text-presumption-of-innocence` 1080x1920 |
| `timeline.json` | Final edit timeline |
| `paths.json` | Source path manifest (hardlink/symlink/copy mode) |

## Scenes

### scene-01

- **start:** 0.0s
- **duration:** 7.262s
- **voice:** У Гранита Джаки — уголовное расследование из-за возможного поддельного COVID-сертификата.
- **main visual:** mascot-shock-one__switzerland-home-current
- **supporting visual:** player-xhaka-switzerland
- **overlay text:** РАССЛЕДОВАНИЕ
- **animation:** shake

### scene-02

- **start:** 7.262s
- **duration:** 8.028s
- **voice:** Прокуратура Люцерна проверяет, мог ли капитан Швейцарии получить ложное подтверждение вакцинации. Вина не доказана.
- **main visual:** mascot-point-left-one__sunderland-home-current
- **supporting visual:** player-xhaka-sunderland
- **overlay text:** ВИНА НЕ ДОКАЗАНА
- **animation:** panLeft

### scene-03

- **start:** 15.29s
- **duration:** 11.813s
- **voice:** Самая странная деталь — дата второй прививки. Сначала представитель Джаки назвал 11 ноября 2022-го, потом исправил дату на 8-е и назвал первое число своей ошибкой.
- **main visual:** mascot-think-one__sunderland-home-current
- **supporting visual:** stat-xhaka-spokesman-date-correction
- **overlay text:** 11 → 8 НОЯБРЯ
- **animation:** fade

### scene-04

- **start:** 27.103s
- **duration:** 11.796s
- **voice:** И вот тут становится интереснее. 6 ноября Джака играл за «Арсенал» в Лондоне. 8-го, согласно документу, должен был быть у врача в Люцерне. / А 9-го снова вышел на поле в Лондоне.
- **main visual:** mascot-explain-two__sunderland-home-current
- **supporting visual:** stat-xhaka-nov-6-8-9-chronology
- **overlay text:** 6 → 8 → 9 НОЯБРЯ
- **animation:** slideUp

### scene-05

- **start:** 38.899s
- **duration:** 6.96s
- **voice:** Такой маршрут физически возможен — Blick это отдельно подчёркивает. Но для следствия эти даты важны.
- **main visual:** stat-xhaka-nov-6-8-9-route
- **supporting visual:** —
- **overlay text:** 6 → 8 → 9 · ВОЗМОЖНО
- **animation:** hardCut

### scene-06

- **start:** 45.859s
- **duration:** 10.292s
- **voice:** Представитель Джаки говорит, что у него есть подтверждение двух прививок и он полностью сотрудничает. Адвокат врача утверждает: она действительно его вакцинировала.
- **main visual:** mascot-suspicious__sunderland-home-current
- **supporting visual:** text-doctor-lawyer-statement
- **overlay text:** ВРАЧ: «Я ПРИВИЛА»
- **animation:** fade

### scene-07

- **start:** 56.151s
- **duration:** 5.346s
- **voice:** Пока это только расследование. Ни Джака, ни врач не признаны виновными.
- **main visual:** mascot-stop__switzerland-home-current
- **supporting visual:** text-presumption-of-innocence
- **overlay text:** ПРЕЗУМПЦИЯ НЕВИНОВНОСТИ
- **animation:** hardCut

### scene-08

- **start:** 61.497s
- **duration:** 6.304s
- **voice:** Теперь прокуратуре предстоит выяснить, была ли вакцинация на самом деле — или сертификат оказался фиктивным.
- **main visual:** mascot-point-right-one__sunderland-home-current
- **supporting visual:** player-xhaka-sunderland
- **overlay text:** СЛЕДСТВИЕ ИДЁТ
- **animation:** panRight

## Photo provenance

### player-xhaka-switzerland
- source URL: `https://upload.wikimedia.org/wikipedia/commons/5/5c/Granit_Xhaka_05092026_%282%29.jpg`
- local path: `.local-assets/granit-xhaka-covid-certificate-short/source/player-xhaka-switzerland.jpg`
- sha256: `068377c858629cbf76f83a906423e5fe8b988ac4a57aa898c7a28d458dac7271`
- dimensions: 5184x3888
- note: official SFV page blocked by Cloudflare; Wikimedia Commons NT photo used

### player-xhaka-sunderland
- source URL: `https://images.gc.safcservices.com/fit-in/1600x1600/4eb034e0-78e5-11f0-a7ed-a1588243ae5b.webp`
- page: `https://www.safc.com/news/2025/august/14/xhaka-te/`
- local path: `.local-assets/granit-xhaka-covid-certificate-short/source/player-xhaka-sunderland.webp`
- sha256: `8ac831593aa780d700ef3a24950c9ab12ac17ee4cb60db71b600e541456ccf89`
- dimensions: 1600x900
- note: official SAFC captain announcement hero image

## Editor notes

- Do not commit third-party photos from `.local-assets/`.
- Mascot variants are approved identity-lock finals in `channel-assets/mascot/variants/`.
- Graphics live under `assets/rendered/`; montage slots hardlink/copy them.

## Local-only photos

Player photo binaries live under `.local-assets/granit-xhaka-covid-certificate-short/` and are gitignored. Copy from the path pointers into your editor timeline as needed.
