"""The words the audit log and the interface use for each kind of change."""

MUSE_UNAVAILABLE = "The drafting service is busy. Nothing was changed. Try again in a minute."
MUSE_RATE_LIMITED = "The drafting service is handling too many requests. Nothing was changed. Try again in a minute."
MUSE_REJECTED = "The drafting service could not accept the request. Nothing was changed. Please check the service settings."
MUSE_BUDGET_REACHED = "The daily drafting limit has been reached. Nothing was changed. Try again tomorrow."
MUSE_BAD_OUTPUT = "The drafting service did not return a usable draft. Nothing was changed. Try again."

MSG = {
    "reply": dict(noun="reply", approved="You approved this reply.", rejected="You said not now to this reply.",
                  start="We are posting the reply now.",
                  refused="We stopped. The review changed after you said yes, so nothing was posted.",
                  tampered="We stopped. The reply was changed after you said yes, so nothing was posted.",
                  done="We posted the reply.", detail_done="provider accepted write",
                  ok="We looked at the review again. Your reply is showing.",
                  bad="We checked and it did not match. Please look at it."),
    "ad": dict(noun="ad draft", approved="You approved this ad draft.", rejected="You said not now to this ad draft.",
               start="We are saving the ad as a paused draft.",
               refused="We stopped. Something changed after you said yes, so nothing was saved.",
               tampered="We stopped. The ad draft was changed after you said yes, so nothing was saved.",
               done="We saved the ad as a paused draft. It is not running.", detail_done="provider accepted write; status paused",
               ok="We looked at the ad again. It is saved, paused, and matches what you approved.",
               bad="We checked and the saved ad did not match. Please look at it."),
}
