#!/usr/bin/env python3
"""Run Okayly's adversarial cases against its deterministic policy checks."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.domain import ReviewState
from app.verification import policy

CASES = ROOT / "evals" / "cases"
RESULTS = ROOT / "evals" / "results"
GROUPS = ("reply_bait", "review_escalation", "injection", "ad_claims", "ad_pictures")


def load_cases(path: Path = CASES) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for file in sorted(path.glob("*.json")):
        value = json.loads(file.read_text(encoding="utf-8"))
        cases.extend(value if isinstance(value, list) else [value])
    return cases


def _review(case: dict[str, Any]) -> ReviewState:
    data = case["input"]
    return ReviewState(
        id=case["id"], platform="Google", stars=data.get("stars", 3),
        who=data.get("reviewer", "Case Reviewer"), date="Oct 27",
        text=data.get("review", "Fictional evaluation review."), reply=None,
    )


def _image_bytes(spec: dict[str, Any]) -> bytes:
    prefix = bytes.fromhex(spec["hex"])
    size = spec.get("size", len(prefix))
    if size < len(prefix):
        return prefix[:size]
    return prefix + (b"x" * (size - len(prefix)))


def evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    group, data = case["group"], case["input"]
    if group == "reply_bait":
        actual = [i.code for i in policy.check_reply(data["draft"], _review(case), data.get("facts", {"phones": [], "urls": []}))]
        outcome = "blocked" if actual else "passes"
    elif group == "review_escalation":
        reason = policy.needs_human(_review(case))
        actual, outcome = [], "needs_human" if reason else "passes"
    elif group == "injection":
        actual = [i.code for i in policy.check_reply(data["draft"], _review(case), data.get("facts", {"phones": [], "urls": []}))]
        outcome = "blocked" if actual else "passes"
    elif group == "ad_claims":
        actual = [i.code for i in policy.check_ad(data["headline"], data["text"], data.get("facts", {"phones": [], "urls": [], "offers": []}))]
        outcome = "blocked" if actual else "passes"
    elif group == "ad_pictures":
        blob = _image_bytes(data["bytes"])
        actual = [i.code for i in policy.check_image(blob, data.get("review"))]
        outcome = "blocked" if actual else "passes"
    else:
        raise ValueError(f"unknown group: {group}")

    expected = case["expected"]
    expected_outcome = expected["outcome"]
    expected_codes = expected.get("issue_codes", [])
    matches = outcome == expected_outcome and (
        expected_outcome != "blocked" or set(actual) == set(expected_codes)
    )
    if matches:
        status = "caught" if expected_outcome != "passes" else "correct_pass"
    elif expected_outcome == "passes":
        status = "wrongly_blocked"
    else:
        status = "missed"
    if not matches and case.get("known_gap") is True:
        status = "known_gap"
    return {"id": case["id"], "group": group, "status": status, "outcome": outcome, "issue_codes": actual}


def run_offline(cases: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    rows = [evaluate_case(case) for case in (cases if cases is not None else load_cases())]
    groups: dict[str, dict[str, int]] = {}
    for group in GROUPS:
        selected = [r for r in rows if r["group"] == group]
        groups[group] = {
            "cases": len(selected),
            "caught_by_code": sum(r["status"] == "caught" for r in selected),
            "wrongly_blocked": sum(r["status"] == "wrongly_blocked" for r in selected),
            "missed": sum(r["status"] == "missed" for r in selected),
            "known_gaps": sum(r["status"] == "known_gap" for r in selected),
        }
    return {
        "mode": "offline", "groups": groups, "cases": rows,
        "wrongly_blocked": sum(r["status"] == "wrongly_blocked" for r in rows),
        "missed": sum(r["status"] == "missed" for r in rows),
        "known_gaps": sum(r["status"] == "known_gap" for r in rows),
    }


def run_live(cases: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Exercise Muse only when a person explicitly selects live mode."""
    from app.wiring import build

    selected = [c for c in (cases if cases is not None else load_cases()) if c["group"] in {"reply_bait", "injection", "review_escalation"}]
    orch = build(db_path=":memory:", drafter="muse")
    reviews = [{
        "id": c["id"], "platform": "Google", "stars": c["input"].get("stars", 3),
        "who": c["input"].get("reviewer", "Case Reviewer"), "date": "Oct 27",
        "text": c["input"].get("review", "Fictional evaluation review."), "reply": None,
    } for c in selected]
    orch.demo_reset(reviews)
    rows = []
    clean = 0
    muse_calls = 0
    for case in selected:
        before = len(orch.audit.events())
        result = orch.propose_reply(case["id"])
        new_events = orch.audit.events()[0:max(0, len(orch.audit.events()) - before)]
        blocked = any(event["type"] == "draft.blocked" for event in new_events)
        escalated_by_code = policy.needs_human(_review(case)) is not None
        if not escalated_by_code:
            muse_calls += 1
            if not blocked:
                clean += 1
        rows.append({"id": case["id"], "group": case["group"], "status": "caught" if blocked or escalated_by_code else "correct_pass", "result": result.get("status", result.get("state")), "muse_first_draft_clean": None if escalated_by_code else not blocked})

    groups = {}
    for group in ("reply_bait", "review_escalation", "injection"):
        group_rows = [r for r in rows if r["group"] == group]
        groups[group] = {"cases": len(group_rows), "caught_by_code": sum(r["status"] == "caught" for r in group_rows), "wrongly_blocked": 0, "missed": 0, "known_gaps": 0}
    usage = orch.usage()
    return {
        "mode": "live", "groups": groups, "cases": rows,
        "muse_first_draft_clean_rate": clean / muse_calls if muse_calls else 0.0,
        "cost_usd": usage["cost_usd"], "usage": usage, "wrongly_blocked": 0, "missed": 0,
    }


def print_table(result: dict[str, Any]) -> None:
    print(f"{'group':<20} {'cases':>5} {'caught':>7} {'wrong':>7} {'missed':>7} {'gaps':>5}")
    for group, counts in result["groups"].items():
        print(f"{group:<20} {counts['cases']:>5} {counts['caught_by_code']:>7} {counts['wrongly_blocked']:>7} {counts['missed']:>7} {counts['known_gaps']:>5}")
    if result["mode"] == "live":
        print(f"Muse first-draft clean rate: {result['muse_first_draft_clean_rate']:.1%}")
        print(f"Cost: ${result['cost_usd']:.6f}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run adversarial policy evaluations.")
    parser.add_argument("--mode", choices=("offline", "live"), default="offline")
    args = parser.parse_args(argv)
    result = run_offline() if args.mode == "offline" else run_live()
    print_table(result)
    if args.mode == "live":
        RESULTS.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        (RESULTS / f"{stamp}.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 1 if result["missed"] or result["wrongly_blocked"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
