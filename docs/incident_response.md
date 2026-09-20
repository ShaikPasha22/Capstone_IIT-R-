# Incident response: the kill switch

## When to use this
Something downstream of routing is behaving badly -- the generator is
producing unsafe drafts, the classifier was retrained on bad data, a new
policy class needs to be blocked and there isn't time to ship a code change
first, or you simply want a human confirming every response while something
is investigated. Halting automation stops new tickets from being
auto-answered; it does not touch tickets already sent.

## What actually happens
`src/route.py`'s `decide()` checks the kill switch first, before every other
rule (see [ADR-003](decisions/ADR-003-policy-before-confidence.md)). While
halted, every ticket still runs through classification and retrieval as
normal -- so the decision log still shows what the system *would* have
predicted -- but routing is forced to `escalate` with reason
`"Automation halted by operator (kill switch)."` regardless of confidence or
intent. Nothing in flight is lost: a ticket mid-processing when the switch
is flipped either completes on the old state or the new one, and either way
it is logged.

## Halting via the API
```bash
export ADMIN_TOKEN=<the value configured in .env, not the change-me default>
curl -X POST http://localhost:8000/admin/halt -H "X-Admin-Token: $ADMIN_TOKEN"
```
Confirm it took effect:
```bash
curl http://localhost:8000/admin/status
# {"halted": true}
```
The operator console (`http://localhost:8000/`) also shows a live
halted/live indicator in the header and has Halt/Resume buttons that prompt
for the token.

## Halting without the API running
If the API process itself is unresponsive, the kill switch is still just a
file:
```bash
touch storage/HALT
```
The next request that starts the process (or the next ticket, if it's still
running but the API layer is the problem) will see the file and escalate.

## Resuming
```bash
curl -X POST http://localhost:8000/admin/resume -H "X-Admin-Token: $ADMIN_TOKEN"
# or, if the API is down:
rm storage/HALT
```

## Why the token matters
`ADMIN_TOKEN` defaults to `change-me` in `.env.example` on purpose, and
`src/api.py` emits a warning at startup if it is left at that value. Anyone
who can reach `/admin/halt` with the right token can silently force every
ticket to escalate, which is itself an incident if it happens by accident or
by an attacker who found the default. Set a real value before running this
anywhere reachable by more than your own machine.

**`GET /admin/reveal-token` hands the real token back to anyone who asks.**
The console's "Show" button on the token field solves an arithmetic puzzle
before un-masking it, but that puzzle runs entirely in the browser -- it is
not an access control, and `curl http://localhost:8000/admin/reveal-token`
returns the token with no check at all beyond the `EXPOSE_ADMIN_TOKEN_ENDPOINT`
flag. This is a local-development convenience, accepted as a deliberate
trade-off. **Set `EXPOSE_ADMIN_TOKEN_ENDPOINT=false` in `.env` before running
this anywhere reachable by more than your own machine** -- otherwise the
token, and therefore the kill switch itself, has no real protection.

## After the incident
- Check `/api/stats` or run `evaluation.harness` against a recent ticket
  batch to confirm the fix behaves as expected before resuming.
- Resume, then watch the decision log (`src/logging_store.py`,
  `rows_for_ticket`) or the console for the next several tickets rather than
  assuming the fix worked from the fact that it deployed cleanly.
