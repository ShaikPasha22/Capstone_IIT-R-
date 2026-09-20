"""Route: decide between answering automatically and escalating. Deterministic
-- the same input always yields the same decision. Records the reason in
language a support manager could read.

Threshold and the hard-block category list are informed by discovery
evidence, not guessed:
  - 17.4% of dev tickets are labelled must_not_auto_respond, concentrated in
    security_incident, compliance_request, feature_request and
    unclear_request -- this matches Daniel's (tier-two engineer) list almost
    exactly, so those categories are blocked before confidence is even
    checked.
  - The confidence threshold itself should be swept against the dev set and
    set from measured precision, not assumed at 0.80. See evaluation/harness.py.
"""
from __future__ import annotations
from dataclasses import dataclass

HARD_BLOCK_INTENTS = {"security_incident", "compliance_request", "feature_request", "unclear_request"}


@dataclass
class RoutingDecision:
    action: str  # "auto_respond" | "escalate"
    rule: str
    reason: str
    threshold_applied: float
    priority: str


def decide(
    intent: str,
    intent_confidence: float,
    retrieved_any: bool,
    urgency: str,
    confidence_threshold: float = 0.80,
    halted: bool = False,
) -> RoutingDecision:
    priority = "urgent" if urgency == "high" else ("standard" if urgency == "medium" else "low")

    if halted:
        return RoutingDecision(
            action="escalate",
            rule="R-00-kill-switch",
            reason="Automation halted by operator (kill switch).",
            threshold_applied=confidence_threshold,
            priority=priority,
        )

    if intent in HARD_BLOCK_INTENTS:
        return RoutingDecision(
            action="escalate",
            rule="R-01-policy-class",
            reason=f"Intent '{intent}' is on the hard-block list regardless of confidence.",
            threshold_applied=confidence_threshold,
            priority=priority,
        )

    if not retrieved_any:
        return RoutingDecision(
            action="escalate",
            rule="R-02-no-grounding",
            reason="No documentation passage cleared the relevance threshold; nothing to ground an answer in.",
            threshold_applied=confidence_threshold,
            priority=priority,
        )

    if intent_confidence >= confidence_threshold:
        return RoutingDecision(
            action="auto_respond",
            rule="R-04-auto-respond",
            reason=f"Intent confidence {intent_confidence:.2f} meets the {confidence_threshold:.2f} threshold and sources were found.",
            threshold_applied=confidence_threshold,
            priority=priority,
        )

    return RoutingDecision(
        action="escalate",
        rule="R-03-below-threshold",
        reason=f"Intent confidence {intent_confidence:.2f} is below the {confidence_threshold:.2f} threshold.",
        threshold_applied=confidence_threshold,
        priority=priority,
    )
