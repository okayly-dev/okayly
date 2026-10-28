# Okayly

An AI assistant for a local practice's marketing that never acts without a person's OK.

It reads new customer reviews and drafts replies, and drafts ads with pictures. Every draft goes through a privacy and claims check, then waits for a person to approve the exact text. After approval, separate code does the work and reads the result back to confirm it. Each step is written to a tamper-evident log.

Built with Meta's Muse models for the Meta Global AI Developer Hackathon (Build for Your World, Indie track).

Status: work in progress. The demo uses a fictional practice and sample reviews. No real accounts are connected.

## Muse features used

- Muse Spark: tool calling, strict structured output, picture review (vision)
- Muse Image: ad pictures

## Layout

- `web/index.html`: the interface (single file, served by the app)
- `spike/`: first test script and results for the Muse API calls

## Run it

    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
    .venv/bin/python -m pytest                      # offline tests, no API calls
    DEMO_CONTROLS=1 .venv/bin/uvicorn app.main:app  # fixture drafter, no spend
    # real model: export MODEL_API_KEY=... DRAFTER=muse   (the key is read from the environment only)

## What the code does

Code is in layers, and imports only go downward (checked by a test):

- `app/core/`: states, canonical hashing, the hash-chained audit log, SQLite storage.
- `app/providers/`: a read-only view of reviews and ads, and the sandbox write side that only the executor uses.
- `app/verification/`: fixed rules every reply, ad and picture must pass, and pure read-back comparisons.
- `app/agents/`: Muse Spark through the Responses API. Muse reads data only through read tools and returns a structured draft.
- `app/workflows/`: propose, edit, reject, and the approval gate. An approval is bound to a SHA-256 of the exact change; a stale change is refused.
- `app/executors/`: the only code that writes. It recomputes the content hash from what is stored and refuses if it differs from what was approved, re-reads before writing, then reads back to verify.
- `app/api.py`, `app/wiring.py`, `app/service.py`: HTTP endpoints, assembly, and a thin facade.
