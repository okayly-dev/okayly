"""Ad studio bench: run the ad drafter N times on real Muse and print each result next to the
code's verdict. Text only by default (cheap); --pictures also makes and checks one picture per run.
Usage: python bench/ad_bench.py [--runs 3] [--pictures]. Needs MODEL_API_KEY. Costs cents."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import wiring  # noqa: E402
from app.verification import policy  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--pictures", action="store_true")
    a = ap.parse_args()
    orch = wiring.build(drafter="muse")
    studio = orch.ad_studio
    for i in range(a.runs):
        d = studio.draft(f"Bench ad {i + 1}")
        issues = policy.check_ad(d.headline, d.text, orch.rt.facts)
        print(f"\n--- run {i + 1} ---\nheadline ({len(d.headline)}): {d.headline}\ntext ({len(d.text)}): {d.text}")
        print("code verdict:", [x.code for x in issues] or "clean")
        for p in d.image_prompts:
            print("  picture prompt:", p)
        if a.pictures:
            data = studio.image(d.image_prompts[0])
            chk = studio.review_image(data)
            print("  picture bytes:", len(data), "type:", policy.sniff_image(data), "check:", chk)
            Path(f"bench/out_run{i + 1}.img").write_bytes(data)
    print("\nusage:", orch.usage())


main()
