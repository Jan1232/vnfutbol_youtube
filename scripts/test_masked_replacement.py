#!/usr/bin/env python3
"""Regression: final composite uses masked pixel replacement, not jersey blending."""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mascot_common import compose_masked_replacement, extract_outfit_layer


def assert_true(cond: bool, message: str) -> None:
    if not cond:
        raise AssertionError(message)


def test_interior_not_blended_with_jersey() -> None:
    size = (8, 8)
    # Base jersey is bright green — must not leak into solid clothing pixels.
    base = Image.new("RGBA", size, (0, 255, 0, 255))
    full_edit = Image.new("RGBA", size, (255, 0, 0, 255))
    mask = Image.new("L", size, 0)
    mpx = mask.load()
    for y in range(2, 6):
        for x in range(2, 6):
            mpx[x, y] = 255

    layer = extract_outfit_layer(full_edit, mask, feather=0)
    composite = compose_masked_replacement(base, layer)

    # Interior clothing pixel must be pure red from full-edit.
    assert_true(composite.getpixel((3, 3)) == (255, 0, 0, 255), composite.getpixel((3, 3)))
    # Outside mask must stay exact base green.
    assert_true(composite.getpixel((0, 0)) == (0, 255, 0, 255), composite.getpixel((0, 0)))

    # Contrast with alpha_composite: if layer had partial alpha, blend would mix.
    partial = Image.new("RGBA", size, (0, 0, 0, 0))
    partial.putpixel((3, 3), (255, 0, 0, 128))
    blended = Image.alpha_composite(base, partial)
    replaced = compose_masked_replacement(base, partial)
    # Partial boundary may lerp; solid replacement path for 255 is the main contract.
    assert_true(blended.getpixel((3, 3)) != (255, 0, 0, 255), "sanity: alpha blend mixes")
    # Mid alpha lerps toward layer red (not pure base green).
    assert_true(replaced.getpixel((3, 3))[0] >= 128, replaced.getpixel((3, 3)))
    assert_true(replaced.getpixel((3, 3))[1] < 255, replaced.getpixel((3, 3)))


def test_solid_layer_matches_full_edit_rgb() -> None:
    size = (6, 6)
    base = Image.new("RGBA", size, (10, 20, 30, 255))
    full_edit = Image.new("RGBA", size, (0, 0, 0, 0))
    epx = full_edit.load()
    for y in range(size[1]):
        for x in range(size[0]):
            epx[x, y] = (40 + x, 50 + y, 60, 200)  # translucent edit alpha must not matter
    mask = Image.new("L", size, 255)
    layer = extract_outfit_layer(full_edit, mask, feather=0)
    # Layer alpha = mask coverage (255), RGB from edit ignoring edit alpha thinning.
    assert_true(layer.getpixel((2, 2)) == (42, 52, 60, 255), layer.getpixel((2, 2)))
    composite = compose_masked_replacement(base, layer)
    assert_true(composite.getpixel((2, 2)) == (42, 52, 60, 255), composite.getpixel((2, 2)))


def main() -> int:
    failed = 0
    for name, fn in [
        ("interior_not_blended_with_jersey", test_interior_not_blended_with_jersey),
        ("solid_layer_matches_full_edit_rgb", test_solid_layer_matches_full_edit_rgb),
    ]:
        try:
            fn()
            print(f"OK    {name}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {name}: {exc}")
    if failed:
        print(f"FAIL  {failed} test(s)")
        return 1
    print("PASS  masked replacement tests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
