#!/usr/bin/env python3
"""Print a provider-agnostic outfit-edit prompt for an external image generator."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mascot_common import (
    POLICY_MATCH_REFERENCE,
    POLICY_OMIT,
    load_json,
    outfit_by_id,
    outfit_requires_reference,
)


def render_policy(label: str, policy: str | None) -> str:
    policy = policy or POLICY_OMIT
    if policy == POLICY_MATCH_REFERENCE:
        return f"{label}: reproduce the visible element from Image C."
    if policy == POLICY_OMIT:
        return f"{label}: do not add."
    return f"{label}: follow policy `{policy}`."


def build_prompt(job: dict) -> str:
    outfit = outfit_by_id(job["outfit"]) or {}
    description = job.get("outfitDescription") or outfit.get("generationDescription", "")
    if outfit_requires_reference(outfit):
        policies = "\n".join(
            [
                render_policy("Crest", outfit.get("crestPolicy")),
                render_policy("Manufacturer mark", outfit.get("manufacturerPolicy")),
                render_policy("Sponsor / front branding", outfit.get("sponsorPolicy")),
            ]
        )
        return (
            f"""Image A: canonical mascot identity reference
channel-assets/mascot/{job['canonicalReference']}

Image B: approved base pose
channel-assets/mascot/{job['basePoseFile']}

Image C: official outfit visual reference
.local-assets/shared/mascot-outfit-references/{job['outfit']}/reference.png

Preserve exact identity from A.
Preserve exact pose, gesture, body geometry, hands and framing from B.
Change ONLY the clothing region defined by the approved mask.
Reproduce the real kit design from Image C as faithfully as possible: colors, pattern, collar, sleeve design and official visual marks according to outfit policies.
Do not invent marks or text not visible in Image C.
Do not add player name or number unless explicitly requested.
Transparent background. Same canvas/composition.

Outfit id: {job['outfit']}
Season / notes:
{description}

Policy:
{policies}

No additional props.
No background.
No lighting redesign.

Output:
PNG with true alpha. This full edit is an intermediate artifact only.
Production will extract the clothing layer through the approved clothing mask
and composite it back onto the original immutable base pose.
"""
        )

    return (
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

{render_policy("Crest", outfit.get("crestPolicy"))}
{render_policy("Manufacturer mark", outfit.get("manufacturerPolicy"))}
{render_policy("Sponsor / front branding", outfit.get("sponsorPolicy"))}
No additional props.
No background.
No lighting redesign.

Output:
PNG with true alpha. This full edit is an intermediate artifact only.
Production will extract the clothing layer through the approved clothing mask
and composite it back onto the original immutable base pose.
"""
    )


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
    print(build_prompt(job))
    return 0


if __name__ == "__main__":
    sys.exit(main())
