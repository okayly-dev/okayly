# Okayly

An AI assistant for a local practice's marketing that never acts without a person's OK.

It reads new customer reviews and drafts replies, and drafts ads with pictures. Every draft goes through a privacy and claims check, then waits for a person to approve the exact text. After approval, separate code does the work and reads the result back to confirm it. Each step is written to a tamper-evident log.

Built with Meta's Muse models for the Meta Global AI Developer Hackathon (Build for Your World, Indie track).

Status: work in progress. The demo uses a fictional practice and sample reviews. No real accounts are connected.

## Muse features used

- Muse Spark: tool calling, strict structured output, web search, image review
- Muse Image: ad pictures

## Layout

- `index.html`: interface prototype (open in a browser, no build step)
- `spike/`: first test script and results for the Muse API calls

## Run it

    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
    .venv/bin/python -m pytest                      # offline tests, no API calls
    DEMO_CONTROLS=1 .venv/bin/uvicorn app.main:app  # fixture drafter, no spend
    # real model: export MODEL_API_KEY=... DRAFTER=muse   (the key is read from the environment only)

## What the code does

- `app/service.py`: propose, approve, execute and verify. An approval is bound to a SHA-256 of the exact change; a stale change is refused.
- `app/audit.py`: hash-chained, append-only log.
- `app/policy.py`: rules every reply must pass (no patient confirmation, no promises, no health advice, no names).
- `app/muse/`: Muse Spark through the Responses API. Muse reads data only through three read tools and returns a structured draft.
