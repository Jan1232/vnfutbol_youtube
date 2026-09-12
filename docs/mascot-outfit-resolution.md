# Mascot outfit resolution

The base mascot image is immutable.

```text
ORIGINAL APPROVED BASE POSE
+
APPROVED OUTFIT LAYER
=
FINAL MASCOT
```

An AI full edit is only an intermediate artifact. It is never the production source of truth. Head, eyes, hands, fingers and body geometry from a generated image must not enter the shared library.

## Who decides what

- AI visual plan picks `outfitIntent` from scene meaning.
- `videos/<slug>/context/entities.json` is the source of truth for current club and national team. It is filled at RESEARCH. Python never looks this up on the web.
- `scripts/resolve_mascot_outfit.py` only applies deterministic rules to that markup.

`outfitIntent=auto` is unresolved on purpose. Local Python must not guess.

## AI priority

1. EXPLICIT outfit
2. NATIONAL TEAM context
3. EXPLICIT CLUB context
4. FORMAL / award / ceremony
5. PLAYER CURRENT CLUB
6. DEFAULT (`default-home`)

Historical scenes must not silently use the player's current club. Old-club clothing is always `explicit`.

## Examples

| Scene meaning | outfitIntent | resolvedOutfit |
| --- | --- | --- |
| На EURO Ямаль... | `national-team` | `spain-home` |
| В составе Barcelona... | `explicit` or `current-club` | `barcelona-home` |
| Сегодня Ямаль считается... | `current-club` | `barcelona-home` |
| На вручении Ballon d'Or... | `formal` | `suit-navy` |
| Почему современные нападающие... | `default` | `default-home` |

`default-home` has no overlay. Production uses the approved base pose as-is.

## Pipeline

```text
AI VISUAL PLAN
→ outfitIntent
→ entities.json
→ resolvedOutfit
→ variant lookup
→ REUSE if the approved layer exists
→ GENERATION JOB if missing or stale
→ external AI full edit
→ mask extraction
→ outfit layer
→ approval
→ promote to channel-assets/mascot
→ reuse forever
```

## Remotion contract

Do not create a Remotion project in this repository. Future timeline visuals may store:

```json
{
  "visual": {
    "type": "MASCOT",
    "pose": "argument",
    "outfit": "spain-home"
  }
}
```

A renderer should:

1. load the immutable pose PNG from `poses.json`;
2. if outfit is `default-home`, draw only that pose;
3. otherwise load the approved layer from `variants.json`;
4. alpha-composite layer over pose.

Same canvas. No identity rewrite.
