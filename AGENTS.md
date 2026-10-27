# AGENTS.md

Okayly: an AI assistant for a local practice's marketing that never acts without a person's OK. Two loops: it reads customer reviews and drafts replies with Meta's Muse Spark; it drafts ads with Muse Spark and Muse Image and checks each picture with Spark vision. Each draft is checked against fixed rules, a person approves the exact text (and picture), a separate executor writes, and the result is read back. Ads are only ever saved paused. Built for the Meta Global AI Developer Hackathon.

This repository is **public-facing**. Keep everything in it generic.

## Layout

| Path | What |
|---|---|
| `app/service.py` | Orchestrator for both kinds of change (reply, ad draft): propose, edit, approve, reject, execute, verify |
| `app/domain.py` | The seven states and allowed moves |
| `app/policy.py` | Deterministic rules: replies (no patient confirmation, promises, health advice, names, unknown contacts), the "needs a person" rule, ad wording (`check_ad`) and the picture gate (`check_image`) |
| `app/audit.py` | Hash-chained, append-only audit log (SHA-256) |
| `app/canonical.py` | Canonical JSON and hashing |
| `app/store.py` | SQLite storage; nested transactions |
| `app/providers/sandbox.py` | Sandbox Google provider (writable), manual Yelp hand-off (read-only), sandbox ad account (paused drafts only; no activate method, no budget column) |
| `app/muse/client.py` | OpenAI SDK pointed at the Meta Model API (Responses API, image generation); records token usage and cost |
| `app/muse/loop.py` | Shared capped tool loop and argument parsing |
| `app/muse/reviews.py` | Reply drafter: tool loop, strict structured output; fixture drafter for tests |
| `app/muse/ads.py` | Ad studio: Spark writes the ad, Muse Image makes 3 pictures, Spark vision reports what each shows; fixture studio for tests |
| `app/api.py`, `app/main.py`, `app/wiring.py` | FastAPI endpoints, static files, assembly from settings |
| `app/fixtures/sample.json` | Fictional practice, reviews and canned drafts |
| `web/index.html` | The interface (single file, generated; do not hand-edit) |
| `spike/` | First Muse API tests and `RESULTS.md` |
| `tests/` | Offline tests (`test_core`, `test_api`, `test_ads`), plus opt-in live tests |

## Run and test

```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest                                # offline, free
RUN_LIVE=1 .venv/bin/python -m pytest -m live -s          # real Muse, costs cents
DEMO_CONTROLS=1 .venv/bin/uvicorn app.main:app --port 8000   # canned drafts, no spend; open http://localhost:8000
DRAFTER=muse DEMO_CONTROLS=1 .venv/bin/uvicorn app.main:app --port 8000   # real Muse; needs MODEL_API_KEY
```
Settings come from the environment: `DRAFTER` (`fixture` default, or `muse`), `MODEL_API_KEY`, `DB_PATH` (default in-memory), `DEMO_CONTROLS=1` (demo-only endpoints: edit a review behind the app's back, tamper with the log, reset).

## Safety invariants (do not weaken; tests cover each)

1. **Muse has no write tool.** It can read through three read tools and return a structured draft. Posting is done by the executor after approval.
2. **An approval is bound to a SHA-256 of the exact change.** A different hash is refused and audited. Editing a reply changes its hash.
3. **The executor re-reads before writing.** If the review changed or already has a reply, it writes nothing (`precondition_changed`).
4. **Verification is an independent read**, not the write response.
5. **Rules are code, not prompts.** A reply that fails `policy.check_reply` cannot become a proposal and cannot be saved after an edit. A second blocked draft means no proposal.
6. **Untrusted text stays out of the prompt.** Review text reaches Muse only as a tool result labelled untrusted. Tool arguments from Muse are validated in code.
7. **Reviews about legal action, billing disputes and similar get no draft** (`policy.needs_human`).
8. **The audit log is written in the same transaction as each state change**, and `GET /api/audit/verify` recomputes the chain.
9. **Yelp is never posted to.** An approved Yelp reply is a manual hand-off.
10. **This app cannot spend money or switch an ad on.** The ad account has no activate method and no budget column, and its status column only accepts `paused`.
11. **A picture is used only if code says every check passed.** Spark vision reports what it sees; `policy.check_image` decides. The picture's SHA-256 is inside the approved hash, so a different picture needs a new OK, and the executor re-checks the stored bytes before saving.
12. **Keys never leave the environment.** Do not log, print, store or commit `MODEL_API_KEY`.

## Meta Model API notes (checked against Meta's docs, Oct 2026)

- Use the **Responses API** for tool loops (it keeps reasoning across turns). Structured output is `text.format`; on Chat Completions it is `response_format`. They are not interchangeable.
- `tool_choice` supports only `"auto"`. `max_tool_calls` limits built-in tools only; cap your own loop (`MAX_ROUNDS`).
- Function tool names: letters, digits, `_`, `-`, at most one dot. Always validate generated arguments, even with `strict: true`.
- Strict schemas: object root, all properties required, `additionalProperties: false`, no recursion, no `oneOf`/`allOf`.
- The OpenAI SDK does not read `MODEL_API_KEY`; pass it explicitly.
- Reasoning tokens count toward output limits; leave `max_output_tokens` generous.
- Muse has no speech output. Video input works through the Files API or a video URL (not exercised here yet).
- Image generation (`images.generate`, `muse-image-1.0`) returns base64, and the bytes can be WebP, so detect the type from the first bytes. Vision on the Responses API takes `{"type": "input_image", "image_url": "data:..."}` (verified live).

## Conventions

- Python 3.12+, pinned dependencies in `requirements.txt`. Prefer the standard library.
- Every behaviour change needs a test. Run the offline suite before committing.
- Sample data stays fictional and labelled. No invented ratings, results or testimonials.
- All work in this repo must be new work done during the hackathon (Oct 26 to Nov 4 2026). Commit in small, dated steps so judges can see what was built when.
- Do not add anything that names a person, a client, a real practice or a private business. Do not copy planning notes, pricing or playbooks into this repo.
- Commit only when the owner asks. Do not push, add a remote, or make the repo public without the owner's explicit OK.
- Planning, design and decisions live in a separate private workspace outside this repository. If you need them, ask the owner for the location. Never copy private material here.
