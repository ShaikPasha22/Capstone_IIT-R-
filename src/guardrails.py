"""Guardrails: checks that run on every generated response, before release,
and can block it. A check that only warns is not a guardrail. Records what it
checked and what it found either way.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field

PII_PATTERNS = {
    "email": re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
    "phone": re.compile(r"\b(?:\+?\d{1,2}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b"),
    "account_number": re.compile(r"\bACCT-\d{4,}\b", re.IGNORECASE),
    "api_key": re.compile(r"\b(sk|key)-[A-Za-z0-9]{16,}\b"),
}

COMMITMENT_PHRASES = [
    "refund has been issued", "refund will be issued", "we will refund",
    "guaranteed by", "we promise", "will be fixed by", "committed to a refund",
]


@dataclass
class GuardrailReport:
    passed: bool
    checks: dict = field(default_factory=dict)
    blocking_reason: str | None = None


def check_private_data(text: str) -> tuple[bool, list[str]]:
    hits = [name for name, pattern in PII_PATTERNS.items() if pattern.search(text)]
    return (len(hits) == 0, hits)


def check_grounding(citations: list[str], unsupported: bool) -> bool:
    return bool(citations) and not unsupported


def check_tone_and_scope(text: str) -> tuple[bool, list[str]]:
    lowered = text.lower()
    hits = [phrase for phrase in COMMITMENT_PHRASES if phrase in lowered]
    return (len(hits) == 0, hits)


def run_guardrails(answer_text: str, citations: list[str], unsupported: bool) -> GuardrailReport:
    pii_ok, pii_hits = check_private_data(answer_text)
    grounding_ok = check_grounding(citations, unsupported)
    tone_ok, tone_hits = check_tone_and_scope(answer_text)

    checks = {
        "private_data": "pass" if pii_ok else f"fail:{','.join(pii_hits)}",
        "grounding": "pass" if grounding_ok else "fail:no_supported_citation",
        "tone_and_scope": "pass" if tone_ok else f"fail:{','.join(tone_hits)}",
    }

    if not pii_ok:
        return GuardrailReport(False, checks, "Private data detected in outbound response.")
    if not tone_ok:
        return GuardrailReport(False, checks, "Response makes a commitment outside support scope.")
    if not grounding_ok:
        return GuardrailReport(False, checks, "Response is not grounded in a retrieved source.")

    return GuardrailReport(True, checks, None)
