from evals.run import GROUPS, load_cases, run_offline


def test_eval_case_schema_and_coverage():
    cases = load_cases()
    assert len(cases) >= 60
    assert len({case["id"] for case in cases}) == len(cases)

    counts = {group: 0 for group in GROUPS}
    for case in cases:
        assert set(case) <= {"id", "group", "input", "expected", "known_gap", "note"}
        assert isinstance(case["id"], str) and case["id"]
        assert case["group"] in GROUPS
        assert isinstance(case["input"], dict)
        assert set(case["expected"]) <= {"outcome", "issue_codes"}
        assert case["expected"]["outcome"] in {"blocked", "needs_human", "passes"}
        if case["expected"]["outcome"] == "blocked":
            assert isinstance(case["expected"].get("issue_codes"), list)
            assert case["expected"]["issue_codes"]
            assert all(isinstance(code, str) and code for code in case["expected"]["issue_codes"])
        else:
            assert "issue_codes" not in case["expected"]
        if case.get("known_gap"):
            assert case["known_gap"] is True
            assert isinstance(case.get("note"), str) and case["note"]

        data = case["input"]
        if case["group"] in {"reply_bait", "injection"}:
            assert isinstance(data.get("review"), str)
            assert isinstance(data.get("draft"), str)
        elif case["group"] == "review_escalation":
            assert isinstance(data.get("review"), str)
        elif case["group"] == "ad_claims":
            assert isinstance(data.get("headline"), str)
            assert isinstance(data.get("text"), str)
        else:
            assert isinstance(data.get("bytes"), dict)
            assert isinstance(data["bytes"].get("hex"), str)
            bytes.fromhex(data["bytes"]["hex"])
        counts[case["group"]] += 1

    assert all(count >= 10 for count in counts.values())


def test_offline_evals_have_no_unexpected_failures():
    result = run_offline()
    assert result["missed"] == 0
    assert result["wrongly_blocked"] == 0

