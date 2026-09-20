# CloudServe support copilot

A retrieval-first support pipeline: ingest -> classify -> retrieve -> route -> generate -> validate,
with a decision log and an unattended evaluation harness. Built from the discovery finding that
71% of incoming tickets already have a correct answer in the documentation -- the system's job is
mostly to find it reliably and know when not to answer, not to write fluent prose.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate          # .venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env                # optional: add OPENROUTER_API_KEY for LLM-drafted answers
```

No API key is required to run the system. Without one, `generate.py` falls back to an extractive
answer built directly from the retrieved passage, which keeps every response grounded even with
no model call at all.

## Run it

```bash
# start the API + operator console
python -m uvicorn src.api:app --reload
# then open http://127.0.0.1:8000 for the console, /docs for the API

# run the full evaluation harness, unattended, against any ticket file
python -m evaluation.harness --input data/validation_tickets.json --output evaluation/results

# run the tests
python -m pytest tests/ -v
```

`evaluation/harness.py` takes `--input` and `--output` as arguments rather than a hardcoded path,
because the graded run points it at a ticket file it has never seen.

## The operator console

`http://127.0.0.1:8000/` shows one ticket at a time: the predicted intent and confidence, the
passages retrieved and their scores, which routing rule fired and why, the guardrail checks, and
either the final answer or the escalation reason -- everything `/api/ticket/{id}` returns, read off
the same decision log every stage already writes to (`src/logging_store.py`). Pick a ticket from the
dropdown, or open `?ticket=VAL-0043` directly to link someone straight to one decision. The header
shows whether automation is currently halted (see below) and has Halt/Resume buttons.

## The kill switch

Automation can be halted without a deployment:

```bash
export ADMIN_TOKEN=<your value from .env, not the change-me default>
curl -X POST localhost:8000/admin/halt -H "X-Admin-Token: $ADMIN_TOKEN"
```

Every ticket then routes on rule R-00 (see `src/route.py`) and escalates, regardless of confidence.
`POST /admin/resume`, or deleting `storage/HALT` directly if the API itself is down, turns it back
on. See `docs/incident_response.md` for the full runbook.

**`GET /admin/reveal-token`** backs the console's "Show" button on the token field (gated by a
client-side puzzle, not real authentication) and returns the actual `ADMIN_TOKEN` to anyone who
requests it. It's a local-dev convenience -- set `EXPOSE_ADMIN_TOKEN_ENDPOINT=false` in `.env`
before running this anywhere reachable by more than your own machine, or the kill switch's token
has no real protection.

## Reproducing the numbers

| Command | What it establishes |
| --- | --- |
| `python -m scripts.tune_threshold` | Sweeps `CONFIDENCE_THRESHOLD` against `data/development_tickets.json`'s labels and reports precision/recall/cost per value, writing `evaluation/results/threshold_sweep.json` -- the measured justification the placeholder 0.55 didn't have. |
| `python -m scripts.fairness_audit` | Groups the development tickets' historical outcomes (CSAT, resolution time, escalation rate) by channel, tier, fluency and region, and writes `docs/fairness_audit.md`. |

## Optional: tracing

If `LANGSMITH_API_KEY` is set and `langsmith` is installed (`pip install langsmith`, commented out
in `requirements.txt` by default), each pipeline stage is traced to LangSmith. Unset, `src/tracing.py`
makes `traceable` a no-op decorator -- zero behavioural or performance difference, and the
no-network-required guarantee above is not affected.

## Design notes worth knowing before reading the code

- **Retrieval uses TF-IDF, not sentence-transformer embeddings.** The originally specified stack
  (Chroma + `all-MiniLM-L6-v2`) needs a route to huggingface.co to download the model, which isn't
  available in every environment. TF-IDF is a same-interface, dependency-light substitute --
  `Retriever.index()` / `.search()` -- so swapping in the embedding version later is a constructor
  change, not a rewrite. Document this trade-off in your build log if you keep it, or swap it back
  in once you have full network access.
- **Classification is a calibrated TF-IDF + logistic regression model trained on the 500 dev
  tickets**, not an LLM call. Intent classification from labelled examples is a classical-ML
  problem; spending API budget on it would be the wrong engineering call.
- **The confidence threshold (0.55) and the hard-block intent list are set from the discovery
  evidence**, not the illustrative 0.80 in the brief. See `src/route.py` for the reasoning and
  `evaluation/harness.py`'s `routing_agreement_vs_expected` metric for how to re-tune it against
  your own threshold sweep.
- **Guardrails run only on the auto-respond path** and force a re-route to escalate on failure --
  see `src/pipeline.py`. `tests/test_pipeline.py` demonstrates a guardrail actually blocking, not
  just warning.

## Project structure

```
src/
  ingest.py          normalise tickets from all four channels
  classify.py         intent + urgency with calibrated confidence
  retrieve.py          TF-IDF search over the documentation corpus
  route.py             the escalation decision, its threshold, and the kill switch check
  generate.py          answer drafting, LLM-optional with extractive fallback
  guardrails.py        checks that can block a response
  logging_store.py     the decision log (SQLite)
  admin.py             the kill switch (storage/HALT)
  tracing.py           optional LangSmith tracing, no-op without a key
  pipeline.py          orchestrates one ticket through all six stages
  api.py               the FastAPI application + admin + console endpoints
  console.py           serves static/console.html
static/
  console.html          the operator console (self-contained, no build step)
evaluation/
  harness.py           runs the hidden evaluation set end to end
  results/             dated output from each run
scripts/
  tune_threshold.py     sweeps CONFIDENCE_THRESHOLD against measured precision/recall/cost
  fairness_audit.py     segment-level outcome comparison from real ticket history
docs/
  decisions/            architecture decision records (ADR-001..004)
  incident_response.md  the kill switch runbook
  fairness_audit.md     generated by scripts/fairness_audit.py
tests/
  test_pipeline.py
  test_api.py
data/                  development/validation tickets, docs corpus (small samples)
storage/               generated at runtime, never committed
.github/workflows/     CI: pytest on every push/PR
```

## What's not done yet

This is a working skeleton proving the architecture end to end -- not the finished capstone
submission. Still needed: Prometheus/Grafana wiring, the discovery/PRD/prompt-library workbooks, a
risk register, and a real hallucination-rate assessment by two independent reviewers rather than a
single grounding-check proxy.
