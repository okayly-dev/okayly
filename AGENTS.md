# AGENTS.md

Okayly: an AI assistant for a local practice's marketing that never acts without a person's OK. Two loops: it reads customer reviews and drafts replies with Meta's Muse Spark; it drafts ads with Muse Spark and Muse Image and checks each picture with Spark vision. Each draft is checked against fixed rules, a person approves the exact text (and picture), a separate executor writes, and the result is read back. Ads are only ever saved paused. Built for the Meta Global AI Developer Hackathon.

This repository is **public-facing**. Keep everything in it generic.

## Layout

Code is in layers. Imports go only downward: a layer may import itself and any layer with a lower number, never a higher one. `tests/architecture/test_layers.py` checks this from the source (with `ast`) and fails the build on a violation.

| # | Layer | Package | What it does |
|---|---|---|---|
| 1 | core | `app/core/` | `domain` (the seven states and allowed moves), `errors`, `canonical` (canonical JSON, SHA-256), `payload` (the exact content of a change and its hash), `audit` (hash-chained, append-only log), `store` (SQLite, nested transactions), `proposals` (read and move proposal rows), `messages` (plain-language wording) |
| 2 | providers | `app/providers/` | `read.py`: `SandboxReader`, the read-only view (read and list reviews and ads). `sandbox.py`: the write side (Google writable, Yelp a manual hand-off, the sandbox ad account with no activate method and no budget column). `seed.py`: sample-data loaders; `feeds.py` reads public News feeds. |
| 3 | verification | `app/verification/` | `policy.py`: deterministic rules for replies, the "needs a person" rule, ad wording, the picture gate. `readback.py`: pure comparisons (approved content equals stored content, preconditions, read-back). Pure; never imports agents; `news.py` checks News items and summaries. |
| 4 | agents | `app/agents/` | The Muse client (`client.py`), the capped tool loop (`loop.py`), the reply drafter (`reviews.py`), the ad studio (`ads.py`), their fixture versions for tests, and `context.py`, the read-only context Muse reads through. Agents get no provider write side and never import providers or executors; `news.py` summarises News, `tools/` holds each read tool and the shared router, `prompts/` holds system instructions. |
| 5 | workflows | `app/workflows/` | `propose`, `edit`, `reject`, `queries`, `demo`, `new_reviews` (hands out the next made-up review from `app/fixtures/new_reviews.json` for `POST /api/reviews/check-new`: one per call, none if 3 are waiting or the pool is used up, audited in the same transaction, no Muse call), and `approval_gate` (the only place an `ApprovedAction` is made). `runtime.py` holds shared state: a read-only provider view, never a write handle; `news.py` runs the News check. |
| 6 | executors | `app/executors/` | `executor.py`: the only code that holds a provider write handle. Takes an `ApprovedAction`, recomputes the content hash, re-reads the world, writes, reads back |
| 7 | api | `app/api.py`, `app/main.py`, `app/wiring.py`, `app/service.py` | FastAPI endpoints, static files, assembly from settings. `service.py` is a thin `Orchestrator` facade that only delegates to workflows and the executor |

Other paths: `app/fixtures/sample.json` (fictional practice, reviews and canned drafts), `app/fixtures/new_reviews.json` (six made-up reviews for "Check for new reviews"; their offline replies are in `sample.json`), `app/fixtures/news_sources.json` (approved feeds), `app/fixtures/news_sample.json` (sample News), `app/agents/tools/` (one file per read tool, with a shared router), `app/agents/prompts/` (Markdown system instructions and their loader), `app/agents/fixture_image.py` (offline PNG maker), `web/index.html` (the interface; single file, generated; do not hand-edit), `spike/` (first Muse API tests and `RESULTS.md`).

Extra import rules (each is a test): agents do not import providers or executors; verification does not import agents; workflows import executors only through the approval gate module; only `app/providers/` and `app/executors/` name `post_reply` or `create_paused_draft`.

Tests: `tests/unit/` (rules, hashing, audit, store, drafters with fakes, pure read-back), `tests/integration/` (reply and ad flows, approval gate, HTTP), `tests/architecture/` (layer rules), `tests/live/` (opt-in, real Muse).

## Run and test

```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest                                # offline, free
RUN_LIVE=1 .venv/bin/python -m pytest -m live -s          # real Muse, costs cents
DEMO_CONTROLS=1 .venv/bin/uvicorn app.main:app --port 8000   # canned drafts, no spend; open http://localhost:8000
DRAFTER=muse DEMO_CONTROLS=1 .venv/bin/uvicorn app.main:app --port 8000   # real Muse; needs MODEL_API_KEY
```
Settings come from the environment: `DRAFTER` (`fixture` default, or `muse`), `MODEL_API_KEY`, `DB_PATH` (default in-memory), `DEMO_CONTROLS=1` (demo-only endpoints: edit a review behind the app's back, tamper with the log, reset). `DAILY_SPEND_CAP_USD` sets the daily model spend cap (default 2.00).

## Safety invariants (do not weaken; tests cover each)

1. **Muse has no write tool.** It can read through three read tools (the ad agent has three of its own, including `ads.get_ad_brief`) and return a structured draft. Posting is done by the executor after approval. Agents are handed a read-only context and never import the provider write side.
2. **An approval is bound to a SHA-256 of the exact change.** A different hash is refused and audited. Editing a reply changes its hash.
3. **The executor re-reads before writing.** If the review changed or already has a reply, it writes nothing (`precondition_changed`).
4. **Verification is an independent read**, not the write response.
5. **Rules are code, not prompts.** A reply that fails `policy.check_reply` cannot become a proposal and cannot be saved after an edit. A second blocked draft means no proposal.
6. **Untrusted text stays out of the prompt.** Review text reaches Muse only as a tool result labelled untrusted. So does an ad brief (`headline_wish`, `picture_request`, `picture_count` on `POST /api/ads/propose`): it is read through `ads.get_ad_brief`, checked by `policy.read_ad_brief` before anything is drafted or spent, and the picture count is enforced in `workflows/propose.py`, not by Muse. Tool arguments from Muse are validated in code.
7. **Reviews about legal action, billing disputes and similar get no draft** (`policy.needs_human`).
8. **The audit log is written in the same transaction as each state change**, and `GET /api/audit/verify` recomputes the chain.
9. **Yelp is never posted to.** An approved Yelp reply is a manual hand-off.
10. **This app cannot spend money or switch an ad on.** The ad account has no activate method and no budget column, and its status column only accepts `paused`.
11. **A picture is used only if code says every check passed.** Spark vision reports what it sees; `policy.check_image` decides. The picture's SHA-256 is inside the approved hash, so a different picture needs a new OK, and the executor re-checks the stored bytes before saving.
12. **Keys never leave the environment.** Do not log, print, store or commit `MODEL_API_KEY`.
13. **Writes happen only through the approval gate: the executor recomputes the content hash and refuses on any difference.** Only `workflows/approval_gate.py` can make an `ApprovedAction`; the executor takes nothing else. Before it writes, it rebuilds the stored change, hashes it, and compares with the approved hash and the stored hash. A difference means `FAILED` with reason `approved_content_changed`, an `execution.refused` audit entry, and nothing written.

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
