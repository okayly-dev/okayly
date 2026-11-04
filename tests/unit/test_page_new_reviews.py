"""The page side of 'Check for new reviews' and of the saved-ad line on This week (text checks, no browser)."""
from pathlib import Path

PAGE = (Path(__file__).resolve().parents[2] / "web" / "index.html").read_text(encoding="utf-8")


def between(start: str, end: str) -> str:
    i = PAGE.index(start)
    return PAGE[i:PAGE.index(end, i)]


ANALYZE = between("async function analyze(){", "async function execute(")
CHECK_LINE = between("function checkLine(){", "function reviewsCard(){")
AD_DONE = between("function adDoneLive(){", "function adCardLive(){")


def test_live_button_calls_the_route_and_reloads_the_list_while_sample_mode_keeps_its_animation():
    live, sample = ANALYZE.split("S.tab='week';", 1)
    assert "'/reviews/check-new'" in live and "loadLive()" in live
    assert "for(let i=1;i<=4;i++)" in sample and "check-new" not in sample


def test_the_three_outcomes_have_plain_lines_and_everything_shown_is_escaped():
    for text in ("Found a new review.", "Reply to the ones waiting first.", "No new reviews right now."):
        assert text in PAGE
    assert "innerHTML" not in CHECK_LINE and "esc(n.text)" in CHECK_LINE
    assert "if(!LIVE)return ''" in CHECK_LINE   # nothing extra in the offline sample


def test_a_saved_ad_stays_on_this_week_as_a_finished_line_and_is_escaped():
    assert "esc(x.name)" in AD_DONE and "esc(x.headline)" in AD_DONE
    assert "if(!a)return adDoneLive()" in PAGE
    assert "x.state==='VERIFIED'" in PAGE   # only a saved and checked ad is kept; an unfinished one may still go away


def test_draft_another_ad_opens_the_ads_tab_on_the_live_page():
    handler = between("case 'repropose':{if(LIVE&&kind==='ad'", "break}")
    assert "S.tab='ads'" in handler and "S.acts.ad=null" in handler
