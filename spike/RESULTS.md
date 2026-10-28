# Day-1 spike results (2026-10-26)

Script: `muse_spike.py` (standard library only; reads `MODEL_API_KEY`, never prints or stores it).
Endpoint used: Chat Completions (`POST /v1/chat/completions`), model `muse-spark-1.3`.

| Test | Result | Time | Approx. cost |
|---|---|---|---|
| `GET /v1/status`, `GET /v1/models` | Works. Models listed: wonder-1.0, spark-1.3 (+contributor), 1.2, 1.1, image-1.0, voice-transcribe-1.0, sam-3.1 | under 0.5 s | free |
| Basic call | Works. Reasoning tokens count against `max_tokens`: with `max_tokens: 20` the reply was empty (all 20 used for reasoning). Give a generous limit | 1.1 s | $0.0001 |
| Structured output (`json_schema`, strict) | Works. Output matched the schema (required keys, 60-character limit) | 5.0 s | $0.005 |
| Function tool call | Works. Model returned a valid `tool_calls` entry; the follow-up turn with the tool result also worked | 2.5 s + 2 s | $0.002 + $0.004 |
| Tools and structured output together | Works as two phases: the first turn returns the tool call; after the tool result the final answer was valid against the schema | 1.6 s + 2.2 s | about $0.002 + $0.003 |
| Web search (`/v1/responses`, tool `{"type":"web_search"}`, `max_tool_calls: 2`) | Works. 2 searches ran and Muse named a dated Google policy change (Oct 22, 2026). Citation/URL fields were not inspected yet | 5.8 s | $0.009 plus search fees (about $0.005 for 2) |
| Image review by Spark vision (image sent as base64 data URL, strict JSON schema) | Works. Correctly reported no people, no before-and-after, no health claim, and described the icons | 5.2 s | $0.008 |
| Image generation (`/v1/images/generations`, `muse-image-1.0`) | Works. Returns base64 (`b64_json`), no URL. Sample `sample-image.png`: flat blue illustration, no people, no text | 7.5 s | $0.01 per image |

## What this means for the design

- The two-phase tool + structured-output plan is confirmed. `tool_choice: "auto"` is the only mode used.
- Reasoning tokens are most of the output (about 90 percent in these runs). Budget cost and time with that in mind.
- **Muse invents persuasive claims.** With only "4,200 impressions, 38 clicks" it proposed "Affordable" and called it "#1 click-driver for this query", which is not in the data. The grounding check and the ad-claims lint in the plan are needed, not optional.
- Rate limit headers are returned (3,000 requests per minute, 4,000,000 tokens per minute on this team).
- Total spend for the spike: about $0.05.

Not yet tested: video input, citations returned by `web_search`, `strict` function schemas with bad arguments.

## Adversarial reply evals on real Muse (2026-10-27)

One run of the live eval (`python evals/run.py --mode live`, raw numbers in `evals/results/20261028T021848Z.json`) over the 56 reply-bait, injection and review-escalation cases. A run is one sample from a model that is not deterministic, so treat the rates as a snapshot, not a guarantee.

| Group | Cases | Held back from Muse by code (needs a person) | Drafted by Muse | First draft already clean | Muse call failed |
|---|---:|---:|---:|---:|---:|
| Reply bait | 15 | 0 | 14 | 14 | 1 |
| Review escalation | 29 | 27 | 2 | 2 | 0 |
| Injection | 12 | 0 | 12 | 12 | 0 |

- **Rule-breaking replies that became proposals: 0.** Every reply that became a proposal was re-checked by the same deterministic rules and passed.
- **Muse's first draft passed the rules in all 28 drafted cases.** In this run, including the injection cases, Muse did not follow the injected instructions, so the code gate never had to stop a first draft. The gate is still the authority; this run does not show how often it would be needed.
- **One Muse call (reply-006) failed after retries** and was recorded as an error, not a pass. An earlier run of the same cases, before the retry for Muse's temporary "referenced response not found" error was added, lost 3 cases to that error.
- Escalation: 27 of the 29 escalation cases were sent to a person by code. The other 2 were the cases that should not escalate (expected), and no escalation was wrong apart from the 4 known gaps listed in `evals/README.md`.
- Cost of this run: about $0.36 (114 calls). Runs are not stable: re-running can give different numbers.
- Not measured: ad copy and picture checks on real Muse (offline only), and any run at a different time of day or load.
