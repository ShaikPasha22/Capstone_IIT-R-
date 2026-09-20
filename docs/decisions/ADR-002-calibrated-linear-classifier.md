# ADR-002: A calibrated linear classifier, not an LLM call, for intent and urgency

## Status
Accepted

## Context
Intent and urgency need to be predicted for every incoming ticket, and the
routing decision in `src/route.py` depends on the predicted intent's
**confidence**, not just its label — `RoutingDecision` only auto-responds
above a numeric threshold. `src/classify.py` is trained on the 500 labelled
tickets in `data/development_tickets.json`, which is a standard supervised
text-classification problem: a fixed label set, hundreds of labelled
examples, and a need for the confidence score to actually mean something
(a routing threshold is only meaningful if "0.7" corresponds to roughly 70%
correctness).

## Decision
`Classifier` is a single shared `TfidfVectorizer` feeding two
`CalibratedClassifierCV`-wrapped `LogisticRegression` heads (one for intent,
one for urgency), trained directly on the labelled development set — not an
LLM prompt.

Two properties of this choice matter more than raw accuracy:
- **Determinism.** The same ticket text always produces the same
  prediction. A support manager auditing a routing decision six months
  later gets the same answer re-running it that the system gave at the
  time.
- **Calibration.** `CalibratedClassifierCV` is used specifically so that
  `intent_confidence` approximates the model's true accuracy at that
  confidence level, because `route.py`'s threshold check
  (`intent_confidence >= confidence_threshold`) is only a meaningful safety
  control if the number it compares against is calibrated rather than a raw,
  usually overconfident, softmax output.

## Consequences
- Training and inference cost nothing and require no network call — an LLM
  is not on the critical path for a decision this frequent (every ticket,
  every stage).
- The classifier is only as good as the 500 labelled examples it is trained
  on; it will not generalize to intents that never appeared in
  `development_tickets.json`.
- Because confidence is calibrated, the threshold in `CONFIDENCE_THRESHOLD`
  is tunable against measured precision (see
  [ADR-003](ADR-003-policy-before-confidence.md) and
  `scripts/tune_threshold.py`) rather than picked arbitrarily.
