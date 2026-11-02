# Okayly

An AI marketing assistant for a local practice that never acts without a person's OK.

A small practice gets reviews it should answer and ads it should run, and it has no time to do either well. A wrong reply can also do real harm: it can confirm that someone was a patient, or promise a result. Okayly drafts the work and leaves the decision to a person. It reads new reviews and drafts replies, and it drafts ads with pictures. Fixed rules in code check every draft. A person approves the exact text, and separate code does the work and reads the result back.

Built with Meta's Muse models for the Meta Global AI Developer Hackathon (Build for Your World, Indie track).

**The demo uses a fictional practice and sample data. No real Google, Yelp or ad account is connected.**

## What it does

| Screen | What happens |
|---|---|
| **Reviews** | New reviews come in. Muse Spark drafts a reply from the review, the practice's facts and past replies. Code checks the reply for privacy and claims. A person edits or approves it. The executor posts it to a sandbox Google profile and reads it back. A Yelp reply stops as a hand-off, because we found no way for an app to post one. |
| **Ads** | Muse Spark drafts the ad text, Muse Image draws the picture, and Muse Spark vision checks the picture. The person approves the exact text and picture. The ad is saved **paused** in a sandbox ad account. The code has no way to switch it on or set a budget. |
| **News** | Code reads three approved public feeds (Google Ads blog, Google Maps blog, Google Search Central), keeps recent and on-topic items, and shows up to three. Muse writes a one-line summary. The link, date and source always come from the feed. |
| **Audit** | Every step goes into an append-only log where each entry carries the hash of the one before. One call checks that the chain is intact. |

## The part that matters: code decides, not the model

Muse drafts. It does not decide what goes out.

- Muse reads data only through read-only tools. It has **no write tool**.
- A person's approval is tied to a SHA-256 hash of the exact change. If the text changes after approval, the executor recomputes the hash and refuses.
- The privacy and claims rules are code, not prompt text. A reply that confirms a visit, promises a result or names a patient is refused, even if the person typed it.
- Reviews that mention legal action, billing disputes or a regulator get no draft. They go to a person.
- Review text never goes into the prompt as an instruction. It reaches Muse only as labelled data in a tool result.
- Ads are only ever saved paused.
- Keys are read from the environment and never stored. A daily spend cap (default $2) stops the model calls.

All 13 safety rules are listed in [`AGENTS.md`](AGENTS.md), and the layout is in [`docs/architecture.md`](docs/architecture.md) with diagrams and the table of API endpoints. A test fails the build if the code layers import in the wrong direction.

## Muse features used

| Muse piece | Used for |
|---|---|
| Muse Spark (`muse-spark-1.3`), Responses API | Reply and ad drafts through a tool-calling loop with 3 read tools for reviews and 2 for ads, capped at 5 rounds |
| Strict structured output | Every draft, picture check and news summary must match a fixed schema |
| Muse Spark vision | Checks each ad picture (no people, no before-and-after, no health claims) |
| Muse Image (`muse-image-1.0`) | Ad pictures |

Muse's built-in web search is not used. In our test it returned no sources, so News reads approved feeds instead.

## What we measured

On real Muse, one run of 56 adversarial cases (`evals/`, raw numbers in `evals/results/`):

- Muse drafted 28 of them: 14 reviews that bait it into breaking a rule, 12 that carry injected instructions, and 2 ordinary reviews. Its first draft already passed the rules in all 28.
- 29 of the cases tested whether code holds back reviews that need a person. 23 of them did need one, and code held back all 23. The other 6 were ordinary reviews that should get a draft: Muse drafted 2, and code held back 4 anyway (a known over-caution, listed in the eval cases). A person still sees those 4.
- No rule-breaking reply became a proposal.
- One Muse call failed after retries and is recorded as an error, not a pass.
- Muse not breaking the rules in this run does not mean it never will. That is why the rules are in code, and the offline suite checks them against known bad replies on every run.

Known gaps in the rules are listed in the eval cases (`known_gap`), not hidden.

## What it costs

Real costs from our own test runs, not estimates. Nothing here is a price list.

| What we ran | Cost |
|---|---|
| 3 real replies (12 model calls) | about $0.03 |
| 3 ad drafts with pictures | about $0.05 |
| One News check (3 summaries) | about $0.02 |
| Full real-model walk-through, reply and ad approved through the screen (43 calls) | about $0.26 |
| The 56-case real-model eval (114 calls) | about $0.36 |
| All testing so far | about $1.70 |

Only the 56-case eval has its result file in this repo (`evals/results/`). The other rows come from the usage records of our own runs, rounded.

With the default settings the demo uses canned sample drafts and spends nothing.

## Run it

Python 3.12 or newer.

    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
    .venv/bin/python -m pytest -q                   # offline tests, no API calls
    DEMO_CONTROLS=1 .venv/bin/uvicorn app.main:app  # sample drafts, no spend; open http://127.0.0.1:8000

For the real model:

    export MODEL_API_KEY=...                        # read from the environment only
    DRAFTER=muse DEMO_CONTROLS=1 .venv/bin/uvicorn app.main:app

Real Muse calls cost money (see above). `DAILY_SPEND_CAP_USD` changes the daily cap. To run the real-model checks: `RUN_LIVE=1 .venv/bin/python -m pytest tests/live` and `.venv/bin/python evals/run.py --mode live`.

To run it on a server with Docker and HTTPS, see [`deploy/README.md`](deploy/README.md).

## Where things are

- `app/`: the code, in seven layers (core, providers, verification, agents, workflows, executors, api). See [`docs/architecture.md`](docs/architecture.md).
- `web/index.html`: the interface (one file, served by the app).
- `tests/`: unit, integration, architecture and opt-in live tests.
- `evals/`: the adversarial cases and their runner. `bench/`: small real-model checks for reply wording and ads.
- `spike/`: our first Muse API tests and what they showed ([`spike/RESULTS.md`](spike/RESULTS.md)).
- `deploy/`: Docker and HTTPS files.

Licensed under the GNU Affero General Public License v3.0 (see `LICENSE`).
