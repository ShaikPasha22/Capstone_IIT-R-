# ADR-003: Policy checks run before the confidence check, and before the kill switch check nothing else does

## Status
Accepted

## Context
`src/route.py`'s `decide()` function evaluates several conditions in a fixed
order and returns on the first match. The order is not incidental — it
encodes a claim about which failure mode is worse. A classifier can be
*confident* about an intent and still be the wrong thing to auto-respond to:
a security-incident ticket phrased clearly enough to get a 0.98 confidence
score is not therefore safe to answer automatically. High confidence in the
wrong action is more dangerous than low confidence, because low confidence
already routes to a human by default.

## Decision
`decide()` checks conditions in this order, first match wins:

1. **Kill switch** (`halted`) — an operator has manually halted all
   automation. Nothing below this line is even considered.
2. **Hard-block intents** (`HARD_BLOCK_INTENTS`) — regardless of confidence.
3. **No retrieval** — nothing to ground an answer in, regardless of
   confidence.
4. **Confidence threshold** — only reached once the above have all passed.

`HARD_BLOCK_INTENTS` is checked with no confidence exception: the loop in
`tests/test_pipeline.py::test_route_hard_blocks_sensitive_intents` asserts
this holds even at `intent_confidence=0.99`, on purpose.

## Consequences
- A ticket can be classified with high confidence and still never be
  auto-answered, if its intent is on the hard-block list or the kill switch
  is engaged. This is intentional and should not be "fixed" by moving the
  confidence check earlier.
- Tuning `CONFIDENCE_THRESHOLD` (see `scripts/tune_threshold.py`) only
  affects the boundary case where policy and retrieval have already passed
  — it cannot cause a hard-blocked intent to be auto-answered no matter how
  it is set.
- Adding a new policy class only requires adding it to
  `HARD_BLOCK_INTENTS`; it does not require touching the confidence logic at
  all.
