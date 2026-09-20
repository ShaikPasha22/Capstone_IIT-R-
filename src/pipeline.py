"""Pipeline: runs one normalised ticket through classify -> retrieve -> route
-> generate -> validate, logging every decision. This is the unit both the
API and the evaluation harness call.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict

from src.ingest import normalise
from src.classify import Classifier
from src.retrieve import Retriever
from src.route import decide
from src.generate import draft_answer
from src.guardrails import run_guardrails
from src.logging_store import DecisionLog
from src.admin import is_halted
from src.tracing import traceable


@dataclass
class TicketOutcome:
    ticket_id: str
    channel: str
    intent: str
    intent_confidence: float
    intent_alternatives: list[dict]
    urgency: str
    priority: str
    retrieved_sources: list[str]
    retrieved_passages: list[dict]
    action: str
    rule: str
    reason: str
    threshold_applied: float
    answer_text: str | None
    answer_backend: str | None
    guardrail_checks: dict
    blocked: bool


class SupportPipeline:
    def __init__(self, classifier: Classifier, retriever: Retriever, decision_log: DecisionLog, confidence_threshold: float = 0.55, storage_dir: str = "./storage"):
        self.classifier = classifier
        self.retriever = retriever
        self.decision_log = decision_log
        self.confidence_threshold = confidence_threshold
        self.storage_dir = storage_dir

    @traceable(run_type="chain", name="classify")
    def _classify(self, text: str):
        return self.classifier.predict(text)

    @traceable(run_type="retriever", name="retrieve")
    def _retrieve(self, text: str):
        return self.retriever.search(text)

    @traceable(run_type="chain", name="route")
    def _route(self, **kwargs):
        return decide(**kwargs)

    @traceable(run_type="chain", name="generate_and_validate")
    def _generate_and_validate(self, ticket_text: str, passages):
        draft = draft_answer(ticket_text, passages)
        report = run_guardrails(draft.answer_text, draft.citations, draft.unsupported)
        return draft, report

    @traceable(run_type="chain", name="support_pipeline")
    def process(self, raw_ticket: dict) -> TicketOutcome:
        ticket = normalise(raw_ticket)

        classification = self._classify(ticket.text)
        self.decision_log.record(
            ticket.ticket_id, "classification", "classified",
            f"Predicted intent={classification.intent}, urgency={classification.urgency}",
            prediction=classification.intent, confidence=classification.intent_confidence,
            requirement_ids=["FR-CLASSIFY"],
        )

        passages = self._retrieve(ticket.text)
        self.decision_log.record(
            ticket.ticket_id, "retrieval", "searched",
            f"{len(passages)} passage(s) cleared the relevance threshold.",
            sources_used=[p.doc_id for p in passages],
            requirement_ids=["FR-RETRIEVE"],
        )

        routing = self._route(
            intent=classification.intent,
            intent_confidence=classification.intent_confidence,
            retrieved_any=len(passages) > 0,
            urgency=classification.urgency,
            confidence_threshold=self.confidence_threshold,
            halted=is_halted(self.storage_dir),
        )
        self.decision_log.record(
            ticket.ticket_id, "routing", routing.action, routing.reason,
            confidence=classification.intent_confidence, threshold=routing.threshold_applied,
            requirement_ids=["FR-ROUTE"],
        )

        answer_text = None
        answer_backend = None
        guardrail_checks: dict = {}
        blocked = False

        if routing.action == "auto_respond":
            draft, report = self._generate_and_validate(ticket.text, passages)
            guardrail_checks = report.checks
            answer_backend = draft.backend
            if report.passed:
                answer_text = draft.answer_text
                self.decision_log.record(
                    ticket.ticket_id, "validation", "sent", "All guardrails passed.",
                    sources_used=draft.citations, guardrails=report.checks,
                    requirement_ids=["FR-GUARDRAIL"],
                )
            else:
                blocked = True
                routing.action = "escalate"
                routing.rule = "R-05-guardrail-blocked"
                self.decision_log.record(
                    ticket.ticket_id, "validation", "blocked", report.blocking_reason or "Guardrail blocked response.",
                    sources_used=draft.citations, guardrails=report.checks,
                    requirement_ids=["FR-GUARDRAIL"],
                )

        return TicketOutcome(
            ticket_id=ticket.ticket_id,
            channel=ticket.channel,
            intent=classification.intent,
            intent_confidence=classification.intent_confidence,
            intent_alternatives=classification.alternatives,
            urgency=classification.urgency,
            priority=routing.priority,
            retrieved_sources=[p.doc_id for p in passages],
            retrieved_passages=[
                {
                    "doc_id": p.doc_id,
                    "title": p.title,
                    "score": p.score,
                    "chunk_text": p.chunk_text,
                    "used_in_answer": (i == 0 and answer_text is not None),
                }
                for i, p in enumerate(passages)
            ],
            action=routing.action,
            rule=routing.rule,
            reason=routing.reason,
            threshold_applied=routing.threshold_applied,
            answer_text=answer_text,
            answer_backend=answer_backend,
            guardrail_checks=guardrail_checks,
            blocked=blocked,
        )

    def process_dict(self, raw_ticket: dict) -> dict:
        return asdict(self.process(raw_ticket))
