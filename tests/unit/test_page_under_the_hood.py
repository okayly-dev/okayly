"""The "Under the hood" table on the page must show made-up example rows only in the offline sample.
In live mode it may show only what the audit log and the proposal really recorded."""
import re
from pathlib import Path

PAGE = (Path(__file__).resolve().parents[2] / "web" / "index.html").read_text(encoding="utf-8")

# Text that used to be typed into the page as if it had happened.
INVENTED = ["Springfield Smiles", "brief.get_competitor_changes", "creative.get_brand_rules", "creative.generate_image",
            "creative.review_image", "plan.propose_ad_draft", "plan.propose_review_reply", "reviews.get_practice_facts",
            "reviews.get_past_replies", "policy.check_reply", "3 images, $0.03", "act_9c21", "22400", "6200"]


def between(start: str, end: str) -> str:
    i = PAGE.index(start)
    return PAGE[i:PAGE.index(end, i)]


SAMPLE = between("function techSample(", "/* Under the hood, live")
LIVE = between("function techLive(", "const techDetails=")


def test_invented_rows_exist_only_in_the_offline_sample_function():
    rest = PAGE.replace(SAMPLE, "")
    for text in INVENTED:
        assert text in SAMPLE, f"{text!r} should still be in the offline sample"
        assert text not in LIVE, f"{text!r} must not be in the live table"
    for text in ("brief.get_competitor_changes", "creative.generate_image", "plan.propose_ad_draft", "plan.propose_review_reply"):
        assert text not in rest, f"{text!r} appears outside the offline sample function"


def test_sample_table_is_labelled_as_an_offline_sample():
    assert "Example steps (offline sample)" in SAMPLE
    assert "Example steps" not in LIVE


def test_live_table_uses_only_recorded_data_and_escapes_it():
    assert "innerHTML" not in LIVE
    assert not re.search(r"\d,\d{3}|\$0\.\d", LIVE)   # no typed-in token counts or dollar amounts
    for field in ("e.plain", "e.detail", "e.time", "a.hash"):
        for hit in re.finditer(re.escape(field), LIVE):
            before = LIVE[max(0, hit.start() - 12):hit.start()]
            assert "esc(" in before or "String(" in before, f"{field} is not escaped near: {before!r}"


def test_live_table_reads_the_audit_entries_of_this_proposal_only():
    assert "e.pid===a.id" in LIVE
    assert "pid:e.proposal_id" in PAGE   # the page keeps the audit entry's proposal id


def test_dispatch_uses_the_real_table_only_for_a_live_proposal():
    assert "const techDetails=key=>LIVE&&S.acts[key].live?techLive(key):techSample(key);" in PAGE
