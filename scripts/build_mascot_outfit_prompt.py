#!/usr/bin/env python3
"""Print a provider-agnostic outfit-edit prompt for an external image generator."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mascot_common import load_json, outfit_by_id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video")
    parser.add_argument("job")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    video_dir = Path(args.video)
    if not video_dir.is_absolute():
        video_dir = (Path.cwd() / video_dir).resolve()
    jobs = load_json(video_dir / "assets" / "mascot-generation.json").get("jobs", [])
    job = next((item for item in jobs if item.get("id") == args.job), None)
    if job is None:
        print(f"ERROR unknown job `{args.job}`")
        return 1
    outfit = outfit_by_id(job["outfit"]) or {}
    description = job.get("outfitDescription") or outfit.get("generationDescription", "")

    print(
        f"""Image A:
canonical mascot reference
channel-assets/mascot/{job['canonicalReference']}

Image B:
approved base pose
channel-assets/mascot/{job['basePoseFile']}

Task:
preserve exact identity from Image A;
preserve exact pose, gesture, body geometry and framing from Image B;
change ONLY clothing to specified outfit;
keep hands, eyes, head, body and pose unchanged;
transparent background;
same canvas and composition.

Outfit:
{description}

No sponsor text.
No manufacturer text/logo.
No additional props.
No background.
No lighting redesign.

Output:
PNG with true alpha. This full edit is an intermediate artifact only.
Production will extract the clothing layer through the approved clothing mask
and composite it back onto the original immutable base pose.
"""
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
