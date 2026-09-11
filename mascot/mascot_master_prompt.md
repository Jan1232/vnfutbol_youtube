Mascot Master Prompt — ВСЕ НА ФУТБОЛ

Назначение

Этот файл фиксирует канонический внешний вид маскота канала «ВСЕ НА ФУТБОЛ» и правила для всех будущих генераций.

Главный принцип: маскот должен выглядеть как один и тот же персонаж во всех изображениях. Меняется поза, жест и настроение — не дизайн героя.

1. Канонический образ персонажа

Постоянный маскот футбольного YouTube-канала.

Неизменяемые черты

взрослый мужской антропоморфный персонаж;

обычное поджарое телосложение, без чрезмерной мускулатуры;

гладкая лысая голова;

всё лицо и видимая кожа покрыты единой гладкой тёмной маской / оболочкой;

маска без рта, носа, бровей и других человеческих черт;

крупные белые выразительные миндалевидные глаза с чёрной окантовкой;

пропорции головы, шеи, плеч, рук и корпуса должны оставаться одинаковыми во всех генерациях;

персонаж должен выглядеть как один и тот же герой в каждой позе.

Стиль изображения

clean 2D cartoon / anime-comic illustration;

аккуратный контур;

мягкий cel-shading;

умеренные блики;

аккуратная читаемая анатомия;

единая степень детализации;

без перехода в реализм, 3D, chibi или другой художественный стиль.

2. Базовая одежда

футбольная футболка без логотипов;

широкие вертикальные тёмно-синие и гранатовые полосы;

без текста, номеров, эмблем и спонсоров;

тёмно-синие шорты без логотипов;

если кадрирование позволяет, верх шорт должен быть виден.

3. Что можно менять

Разрешено менять только:

позу;

жесты;

положение рук;

направление взгляда;

язык тела;

настроение;

ограниченную мимику через глаза;

кадрирование;

тематическую одежду, только если это прямо запрошено для конкретного выпуска;

предметы в руках, только если они прямо запрошены.

Эмоции через глаза

Эмоцию разрешено передавать глазами, но без изменения идентичности персонажа.

Допустимо:

немного сузить глаза;

немного расширить глаза;

слегка изменить их наклон для эмоции.

Недопустимо:

радикально менять размер глаз;

менять расстояние между глазами;

менять их базовое положение на лице;

превращать глаза в другую форму;

делать глаза огромными, круглыми или стилистически отличающимися от канона.

Основную эмоцию лучше передавать позой и языком тела, а не сильной деформацией лица.

4. Что нельзя менять

Запрещено менять:

форму головы;

силуэт черепа;

форму челюсти и нижней части лица;

базовую форму и характер глаз;

расстояние между глазами;

устройство лица;

материал и цвет маски;

телосложение;

базовые пропорции;

ширину плеч;

длину рук;

общий художественный стиль;

узнаваемый дизайн персонажа.

5. STRICT IDENTITY LOCK — CRITICAL

Every new pose MUST use the original canonical mascot reference image supplied by the user as the source of truth.

Never use a previous generated pose as the identity reference.

The following geometry is locked and must not drift between generations:

exact skull silhouette and head proportions;

forehead slope;

jaw and lower-face taper;

exact length and width of the masked face;

base eye size, shape, tilt, spacing and placement;

temple shape;

neck width and connection to shoulders;

shoulder width;

overall lean body proportions.

Do not reinterpret, stylize, soften, sharpen, widen, narrow or otherwise redesign the face.

If pose generation causes identity drift, regenerate rather than accepting the drift.

6. COLOR LOCK — CRITICAL

The base jersey palette must remain visually consistent with the original canonical reference.

Reference colors:

muted dark garnet / burgundy: approximately #81162D;

deep dark navy: approximately #172146.

Rules:

never shift the garnet toward bright red, crimson, scarlet or saturated magenta;

never shift the navy toward royal blue, electric blue or bright cobalt;

never progressively brighten or increase saturation from one generation to another;

do not use previous generated images as color references;

always compare perceived jersey color to the original canonical reference;

lighting may create local highlights and shadows, but the underlying fabric colors must remain unchanged;

do not apply a global brightening effect to the jersey.

If the jersey becomes visibly brighter, redder or bluer than the canonical reference, regenerate.

7. HAND ACCURACY LOCK — CRITICAL

Hands are a production-critical part of the asset.

Mandatory anatomy rules

each hand must have exactly five fingers total;

one thumb + four fingers;

no extra fingers;

no missing fingers;

no duplicated thumbs;

no fused fingers;

no split fingertips;

no extra phalanges;

no impossible joints;

no malformed palms;

no fingers growing from incorrect locations;

no accidental overlap that visually reads as a sixth finger.

Gesture quality

For gestures such as:

count-1;

count-2;

count-3;

stop;

point-left;

point-right;

thumbs-up;

thumbs-down;

calm-down;

what-the-hell;

the number and position of visible fingers must be especially clear.

If a hand is anatomically wrong, do not accept the image into the library — regenerate it.

Prefer a slightly simpler gesture over an anatomically broken hand.

8. Фон — CRITICAL

Во всех библиотечных генерациях:

фон должен быть полностью прозрачным;

нужен настоящий alpha channel;

без белого фона;

без чёрного фона;

без шахматной сетки как части изображения;

без стены;

без пола;

без окружения;

без декоративных элементов;

без фоновой тени;

без цветного glow / halo вокруг персонажа.

Персонаж должен быть чисто изолирован для дальнейшего монтажа.

9. Кадрирование — CRITICAL

Стандарт для библиотеки поз

По умолчанию использовать:

waist-up;

upper-thigh crop;

при эмоциональном крупном плане допустим chest-up.

Для большинства поз предпочтительно кадрирование до середины бедра, чтобы был виден верх шорт.

Нельзя

не обрезать изображение ровно по нижнему краю футболки;

не делать полный рост по умолчанию;

не обрезать кисти, локти или важные части жеста;

не прижимать руки к краям изображения;

не делать случайное тесное кадрирование.

Полный рост

Full-body разрешён только если пользователь прямо попросил полный рост.

10. Правила композиции

персонаж должен полностью помещаться в пределах выбранного кадрирования;

важные части тела не должны быть случайно обрезаны;

руки и жесты должны хорошо читаться;

силуэт должен быть понятным;

оставлять небольшой запас пространства вокруг рук;

поза должна быть пригодна для монтажа поверх видео;

не добавлять лишние предметы;

не добавлять текст;

не добавлять символы, вопросительные знаки, восклицательные знаки или comic effects, если они не запрошены.

11. ONE POSE PER IMAGE — CRITICAL

Одна генерация библиотеки = один персонаж в одной позе на одном изображении.

Никогда не создавать:

contact sheet;

sprite sheet;

коллаж из нескольких поз;

несколько копий маскота в одном изображении;

если пользователь прямо не попросил такой формат.

Если запрошены несколько поз, каждая должна быть отдельным изображением.

12. Базовый master prompt

Use the provided ORIGINAL canonical reference image as the sole identity and color source of truth for the mascot.

Generate the same recurring mascot character with strict consistency.

The character is an adult male humanoid football-channel mascot with a lean, average build, a smooth bald head, and a fully covered dark-black face and visible body surface that looks like a sleek matte/satin mask or skin.

The face has no mouth, no visible nose, no eyebrows, and no visible human facial features other than large expressive white almond-shaped eyes outlined in black.

Preserve the exact character identity from the reference:

skull silhouette;

head proportions;

forehead slope;

jaw taper;

masked-face length and width;

eye placement, spacing and base shape;

temples;

neck width;

shoulders;

lean body proportions.

Do not redesign or reinterpret the face.

Style: clean high-quality 2D anime/comic illustration, polished linework, soft cel shading, subtle highlights, consistent cartoon rendering.

Base outfit:

football jersey with wide vertical dark navy and muted garnet stripes;

muted dark garnet approximately #81162D;

deep dark navy approximately #172146;

no logo;

no sponsor;

no text;

no crest;

no number;

dark navy shorts without logos.

COLOR LOCK:
Do not brighten or oversaturate the jersey.
Do not shift garnet toward bright red/crimson.
Do not shift navy toward royal/electric blue.
Always match the perceived base colors of the original canonical reference.

HAND ACCURACY LOCK:
Every hand must have exactly five fingers total: one thumb and four fingers.
No extra fingers, missing fingers, duplicated thumbs, fused fingers, malformed palms or impossible joints.
If the requested gesture makes hand anatomy unreliable, simplify the gesture while preserving its meaning.

Only change:

pose;

gesture;

limited eye expression;

body language;

explicitly requested objects or clothing.

Default framing:

waist-up or upper-thigh crop;

preferably show the top of the dark navy shorts;

do not crop exactly at the jersey hem;

do not generate full-body unless explicitly requested.

Composition:

one mascot only;

one pose only;

no contact sheet;

no text;

no extra symbols;

no scenery;

enough margin around hands and elbows.

Output:
PNG with a fully transparent background and true alpha transparency.
No white or black background, no checkerboard baked into the image, no floor, no scenery, no cast shadow, no glow or halo.

Keep the mascot cleanly isolated for compositing in video editing.

If identity, jersey colors or hand anatomy drift from the canonical reference, regenerate instead of accepting the result.

13. Короткая формула для новых поз

Сгенерируй этого же канонического маскота, используя только оригинальный референс как источник внешности и цвета.

Сохрани:

точную форму головы и лица;

базовую геометрию глаз;

пропорции тела;

чёрную гладкую маску / кожу;

поджарое телосложение;

единый 2D anime/comic стиль;

тёмно-гранатовый #81162D;

глубокий тёмно-синий #172146.

Меняй только позу, жест, язык тела и ограниченную эмоцию глаз.

На каждой руке строго пять пальцев: один большой + четыре остальных.

По умолчанию кадрирование по пояс / до середины бедра с видимым верхом шорт. Не полный рост.

Один персонаж, одна поза, одно изображение.

Фон полностью прозрачный, настоящий alpha channel.

14. Контроль перед добавлением изображения в библиотеку

Перед тем как считать позу готовой, проверить:

Совпадает ли форма головы с каноническим референсом?

Совпадает ли расположение и базовая форма глаз?

Не изменилось ли телосложение?

Не стала ли футболка ярче или насыщеннее?

Сохранились ли тёмный гранатовый и глубокий navy?

Ровно ли пять пальцев на каждой видимой руке?

Нет ли сросшихся или лишних пальцев?

Не обрезаны ли кисти или локти?

Видны ли шорты при стандартном кадрировании?

Есть ли настоящий прозрачный фон?

Нет ли фонового glow / halo?

Это один персонаж в одной позе?

Нет ли лишних предметов, текста или символов?

Если хотя бы один критический пункт нарушен — перегенерировать изображение.

15. Рекомендуемая структура в проекте

channel-assets/
  mascot/
    mascot_master_prompt.md
    references/
      mascot_reference_main.png
    poses/
      neutral/
      explain/
      point-left/
      point-right/
      think/
      confused/
      laugh/
      aggressive/
      shock/
      facepalm/
      count-1/
      count-2/
      count-3/
      celebrate/
      disappointed/
      sad/
      suspicious/
      argument/
      what-the-hell/
      calm-down/

16. Примечание

Если в будущем появится более удачный официальный референс, его можно назначить основным только после явного решения пользователя.

Новый референс не должен автоматически заменять текущий канонический образ.

При любых сомнениях приоритет:

ORIGINAL REFERENCE → IDENTITY → HAND ANA