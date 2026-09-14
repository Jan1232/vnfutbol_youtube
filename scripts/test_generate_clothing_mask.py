#!/usr/bin/env python3
"""Offline regression tests for clothing-mask generation (no head Y-cutoff)."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_clothing_mask as gcm


def assert_true(cond: bool, message: str) -> None:
    if not cond:
        raise AssertionError(message)


def solid(rgb: tuple[int, int, int], size: tuple[int, int] = (1, 1)) -> Image.Image:
    return Image.new("RGBA", size, (*rgb, 255))


def test_no_head_ratio_constant() -> None:
    assert_true(not hasattr(gcm, "HEAD_RATIO"), "HEAD_RATIO must be removed")
    source = Path(gcm.__file__).read_text(encoding="utf-8")
    assert_true("head_cut" not in source, "head_cut must be removed from generator")
    assert_true("HEAD_RATIO" not in source, "HEAD_RATIO must be removed from generator")


def make_fixture() -> Image.Image:
    """Synthetic waist-up character with collar above old 30% cut."""
    img = Image.new("RGBA", (200, 300), (0, 0, 0, 0))
    px = img.load()
    # Opaque character column.
    for y in range(20, 280):
        for x in range(60, 140):
            px[x, y] = (20, 20, 20, 255)
    # Dark head/neck in top 25% of bbox (old cutoff would hide everything above ~30%).
    for y in range(20, 70):
        for x in range(70, 130):
            px[x, y] = (55, 35, 28, 255)  # dark skin
    # Collar / shoulder garment ABOVE old 30% cut of bbox height 260 → cut at ~98.
    # Place collar at y=75-95 (still above 98).
    for y in range(72, 100):
        for x in range(65, 135):
            if 70 <= x <= 130 and y < 72:
                continue
            px[x, y] = (0x81, 0x16, 0x2D, 255)  # garnet jersey
    # Shoulder caps
    for y in range(95, 120):
        for x in range(55, 145):
            if x < 70 or x > 130:
                px[x, y] = (0x81, 0x16, 0x2D, 255)
    # Torso
    for y in range(100, 200):
        for x in range(70, 130):
            px[x, y] = (0x81, 0x16, 0x2D, 255)
    # Short sleeves + adjacent dark arms/hands (must stay out of mask)
    for y in range(120, 170):
        for x in range(40, 60):
            px[x, y] = (50, 32, 26, 255)  # arm skin
        for x in range(140, 160):
            px[x, y] = (50, 32, 26, 255)
    for y in range(110, 145):
        for x in range(58, 72):
            px[x, y] = (0x81, 0x16, 0x2D, 255)  # short sleeve
        for x in range(128, 142):
            px[x, y] = (0x81, 0x16, 0x2D, 255)
    # Visible shorts
    for y in range(200, 250):
        for x in range(75, 125):
            px[x, y] = (0x17, 0x21, 0x46, 255)  # navy shorts
    return img


def test_fixture_regions() -> None:
    img = make_fixture()
    mask = gcm.build_mask(img)
    m = mask.load()
    # 1) Collar/shoulder above old 30% cutoff included
    assert_true(m[100, 80] >= 128, "collar above old cutoff must be included")
    assert_true(m[58, 110] >= 128, "left shoulder/sleeve must be included")
    # 2) Dark head/neck excluded
    assert_true(m[100, 40] < 128, "dark head/neck must be excluded")
    # 3) Dark arms/hands excluded
    assert_true(m[45, 140] < 128, "dark arm must be excluded")
    assert_true(m[150, 140] < 128, "dark arm must be excluded")
    # 4) Shorts included
    assert_true(m[100, 220] >= 128, "shorts must be included")
    # Torso included
    assert_true(m[100, 150] >= 128, "torso must be included")


def test_generated_status_not_approved(tmp: Path) -> None:
    # Ensure generate_one always writes status=generated
    pose = {
        "id": "synthetic-fixture-pose",
        "file": "poses/_test/synthetic.png",
        "sha256": "abc",
        "approved": True,
    }
    pose_dir = gcm.MASCOT / "poses" / "_test"
    pose_dir.mkdir(parents=True, exist_ok=True)
    pose_path = pose_dir / "synthetic.png"
    make_fixture().save(pose_path)
    try:
        # monkeypatch pose_path via writing expected relative file
        record = gcm.generate_one(pose)
        assert_true(record["status"] == "generated", record)
        assert_true(record["status"] != "approved", "must never auto-approve")
        mask_file = gcm.MASCOT / record["file"]
        assert_true(mask_file.exists(), mask_file)
    finally:
        mask_file = gcm.MASCOT / "pose-masks" / "synthetic-fixture-pose.png"
        if mask_file.exists():
            mask_file.unlink()
        if pose_path.exists():
            pose_path.unlink()


def white_square_with_holes() -> Image.Image:
    mask = Image.new("L", (80, 80), 0)
    px = mask.load()
    for y in range(10, 70):
        for x in range(10, 70):
            px[x, y] = 255
    # tiny enclosed hole
    px[40, 40] = 0
    px[41, 40] = 0
    px[40, 41] = 0
    # another pinhole
    px[50, 50] = 0
    # large enclosed black region (>180)
    for y in range(20, 40):
        for x in range(20, 40):
            px[x, y] = 0
    return mask


def test_fill_small_enclosed_holes() -> None:
    mask = white_square_with_holes()
    filled = gcm.fill_small_enclosed_holes(mask, max_hole_area=16)
    f = filled.load()
    assert_true(f[40, 40] >= 128, "tiny hole must be filled")
    assert_true(f[50, 50] >= 128, "pinhole must be filled")
    assert_true(f[25, 25] < 128, "large enclosed region must remain black")

    # Exterior-connected black corridor from border must remain
    mask2 = Image.new("L", (60, 60), 0)
    p = mask2.load()
    for y in range(15, 45):
        for x in range(15, 45):
            p[x, y] = 255
    # channel from left border into center (arm cutout style)
    for x in range(0, 30):
        p[x, 30] = 0
        p[x, 31] = 0
    out2 = gcm.fill_small_enclosed_holes(mask2, max_hole_area=180)
    o2 = out2.load()
    assert_true(o2[5, 30] < 128, "exterior-connected channel must stay black")
    assert_true(o2[20, 30] < 128, "narrow hand/arm channel must stay black")


def test_cleanup_never_outside_alpha() -> None:
    img = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    px = img.load()
    for y in range(20, 80):
        for x in range(20, 80):
            px[x, y] = (0x81, 0x16, 0x2D, 255)
    # transparent outside — mask must stay 0 there even after closing
    mask = gcm.build_mask(img)
    m = mask.load()
    assert_true(m[5, 5] < 128, "outside alpha must stay empty")
    assert_true(m[50, 50] >= 128, "garment inside alpha must be masked")


def main() -> int:
    failed = 0

    def run(name, fn):
        nonlocal failed
        try:
            fn()
            print(f"OK    {name}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {name}: {exc}")

    run("no_head_ratio_constant", test_no_head_ratio_constant)
    run("fixture_regions", test_fixture_regions)
    run("fill_small_enclosed_holes", test_fill_small_enclosed_holes)
    run("cleanup_never_outside_alpha", test_cleanup_never_outside_alpha)
    with tempfile.TemporaryDirectory() as tmp:
        run("generated_status_not_approved", lambda: test_generated_status_not_approved(Path(tmp)))

    if failed:
        print(f"FAIL  {failed} test(s)")
        return 1
    print("PASS  clothing mask generator tests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
