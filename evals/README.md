# Adversarial policy evaluations

These fictional, brand-free cases exercise the same deterministic checks used by the application. They cover reply privacy and claims, reviews that require a person, prompt-injection attempts, ad wording, and picture gates.

## Run

Run the offline suite without any model calls:

```sh
python evals/run.py --mode offline
```

The command prints counts by group and exits with status 1 for any unexpected miss or wrongly blocked case. Declared known gaps are shown in a separate column. The live mode exists for an explicitly authorized evaluation session, writes timestamped output under `evals/results/`, and can incur model cost. It is not part of the offline test run.

To inspect command options without making a model call:

```sh
python evals/run.py --help
```

## Add a case

Add a uniquely identified object to the matching JSON file in `evals/cases/`. Every case has `id`, `group`, `input`, and `expected`. A blocked expectation also has the exact `issue_codes` expected from the policy check. A case that demonstrates a current policy limitation has `known_gap: true` and a precise `note`; it remains visible in results without failing the offline suite.

Keep all examples fictional and generic. Then run the eval test and the full offline test suite.

## Muse versus code

“Caught by Muse itself” means Muse's first draft avoided the adversarial instruction and already satisfied the deterministic rules. “Caught by code” means either the application refused a review before drafting because it required a person, or Muse returned a rule-breaking first draft and the deterministic policy gate stopped it. The code gate remains authoritative in both cases.
