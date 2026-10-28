"""Reply bench: draft each sample review on real Muse, then once more after the reviewer edits
the first review, and report the code's verdict and whether the reply copies a past reply.
Usage: python bench/reply_bench.py [--runs 1]. Needs MODEL_API_KEY. Costs cents."""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import wiring  # noqa: E402
from app.verification import policy  # noqa: E402

EDIT = " (Edit: the wait was closer to an hour.)"


def sentences(text: str) -> set[str]:
    return {s.strip().lower() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) > 15}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1)
    a = ap.parse_args()
    orch = wiring.build(drafter="muse")
    past = {s for p in orch.rt.past for s in sentences(p)}
    jobs = [(r.id, r.stars, r.text) for r in orch.rt.reader.list_reviews() if r.reply is None]
    copies = total = 0
    for _ in range(a.runs):
        for rid, stars, text in jobs:
            try:
                d = orch.drafter.draft(rid)
            except Exception as e:
                print(f"{rid} ({stars}*): MUSE ERROR {type(e).__name__}", flush=True)
                continue
            if d.escalate:
                print(f"{rid} ({stars}*): ESCALATED by Muse: {d.escalate_reason}", flush=True)
                continue
            review = orch.rt.reader.read_review(rid)
            issues = [i.code for i in policy.check_reply(d.reply, review, orch.rt.facts)]
            copied = sentences(d.reply) & past
            total += 1
            copies += bool(copied)
            print(f"{rid} ({stars}*) review: {text[:70]!r}\n   reply: {d.reply}\n"
                  f"   code: {issues or 'clean'}; copies a past-reply sentence: {bool(copied)}", flush=True)
    if jobs:
        rid = jobs[0][0]
        orch.providers["Google"].edit_text(rid, EDIT)
        try:
            d = orch.drafter.draft(rid)
        except Exception as e:
            print(f"\nAFTER EDIT {rid}: MUSE ERROR {type(e).__name__}")
            d = None
    if jobs and d is not None:
        print(f"\nAFTER EDIT {rid}: {d.reply or 'ESCALATED: ' + d.escalate_reason}", flush=True)
    print(f"\nreplies that copy a past-reply sentence: {copies} of {total}\nusage: {orch.usage()}", flush=True)


main()
