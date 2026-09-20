# ADR-004: Guardrails block the response, they do not try to fix it

## Status
Accepted

## Context
`src/guardrails.py` runs three checks on every drafted answer before it is
released: private data (`check_private_data`), grounding
(`check_grounding`), and tone/scope (`check_tone_and_scope`). A tempting
alternative, once a problem is detected, is to *repair* the response instead
of discarding it — strip the email address the regex found, delete the
sentence that made a refund commitment, and send what's left.

## Decision
`run_guardrails()` returns a `GuardrailReport` that is either fully passed
or fully failed (`GuardrailReport.passed: bool`), with a single
`blocking_reason`. There is no partial-pass, redacted-output path anywhere
in `guardrails.py` or in how `pipeline.py` consumes the report: a failure
sets `blocked = True` and forces `routing.action = "escalate"`, the response
text is discarded, not edited and resent.

The reasoning is about what a single regex hit implies. A private-data
pattern matching once tells us the check found *one* thing it recognizes —
it says nothing about whether the same generation also contains a different
kind of sensitive data the check does not have a pattern for. Redacting the
match we found and sending the rest treats "no more hits" as "nothing else
is wrong," which is not something the check actually established.

## Consequences
- Every guardrail failure becomes a human escalation, with the failing
  draft and the reason recorded in the decision log
  (`stage="validation"`, `action_taken="blocked"`) — nothing unsafe is
  auto-corrected and sent.
- This makes guardrail failures more expensive (a full escalation instead of
  a quick edit) in exchange for not shipping a response whose safety rests
  on the assumption that a regex found everything.
- `tests/test_pipeline.py::test_guardrail_blocks_private_data` and
  `test_guardrail_blocks_ungrounded_answer` assert on the boolean
  pass/fail, not on any modified output, which is deliberate: there should
  never be a "cleaned" response to assert against.
