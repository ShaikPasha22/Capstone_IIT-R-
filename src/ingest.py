"""Ingest: normalise tickets from email, chat, docs_comment and forum into one
internal representation. Preserves original text and channel. Never raises on
missing fields, unusual characters or empty bodies.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


VALID_CHANNELS = {"email", "chat", "docs_comment", "forum"}


@dataclass
class NormalisedTicket:
    ticket_id: str
    channel: str
    subject: str
    body: str
    customer_id: str
    customer_tier: str
    customer_region: str
    language_fluency: str
    received_at: str
    raw: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        """The single string downstream components search and classify on."""
        parts = [p for p in (self.subject, self.body) if p]
        return "\n".join(parts).strip()


def normalise(raw_ticket: dict[str, Any]) -> NormalisedTicket:
    """Turn a raw ticket dict (whatever shape the channel produced) into a
    NormalisedTicket. Missing or malformed fields degrade to safe defaults
    rather than raising, per acceptance criterion A2.
    """
    channel = str(raw_ticket.get("channel", "unknown")).strip().lower()
    if channel not in VALID_CHANNELS:
        channel = "unknown"

    ticket_id = str(raw_ticket.get("ticket_id") or raw_ticket.get("id") or "UNSPECIFIED")
    subject = str(raw_ticket.get("subject") or "").strip()
    body = str(raw_ticket.get("body") or "").strip()

    return NormalisedTicket(
        ticket_id=ticket_id,
        channel=channel,
        subject=subject,
        body=body,
        customer_id=str(raw_ticket.get("customer_id") or "UNKNOWN"),
        customer_tier=str(raw_ticket.get("customer_tier") or "standard"),
        customer_region=str(raw_ticket.get("customer_region") or "unknown"),
        language_fluency=str(raw_ticket.get("language_fluency") or "unknown"),
        received_at=str(raw_ticket.get("received_at") or ""),
        raw=raw_ticket,
    )
