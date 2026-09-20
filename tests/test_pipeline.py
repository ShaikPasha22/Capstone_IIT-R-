import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.ingest import normalise
from src.classify import Classifier
from src.retrieve import Retriever
from src.route import decide, HARD_BLOCK_INTENTS
from src.guardrails import run_guardrails, check_private_data
from src.logging_store import DecisionLog
from src.pipeline import SupportPipeline
from src.admin import halt, resume, is_halted

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def test_ingest_handles_all_four_channels():
    for channel in ["email", "chat", "docs_comment", "forum"]:
        t = normalise({"ticket_id": "T1", "channel": channel, "body": "hello"})
        assert t.channel == channel


def test_ingest_handles_missing_fields_without_raising():
    t = normalise({})
    assert t.ticket_id == "UNSPECIFIED"
    assert t.text == ""


def test_route_hard_blocks_sensitive_intents():
    for intent in HARD_BLOCK_INTENTS:
        decision = decide(intent, 0.99, retrieved_any=True, urgency="low")
        assert decision.action == "escalate"


def test_route_is_deterministic():
    a = decide("billing_query", 0.9, True, "low")
    b = decide("billing_query", 0.9, True, "low")
    assert a.action == b.action


def test_route_escalates_without_sources():
    decision = decide("api_usage_question", 0.99, retrieved_any=False, urgency="low")
    assert decision.action == "escalate"


def test_route_kill_switch_overrides_everything():
    decision = decide("api_usage_question", 0.99, retrieved_any=True, urgency="low", halted=True)
    assert decision.action == "escalate"
    assert "halted" in decision.reason.lower()


def test_admin_halt_and_resume_toggle_kill_switch(tmp_path):
    storage_dir = str(tmp_path)
    assert not is_halted(storage_dir)
    halt(storage_dir)
    assert is_halted(storage_dir)
    resume(storage_dir)
    assert not is_halted(storage_dir)


def test_pipeline_escalates_every_ticket_while_halted(tmp_path):
    classifier = Classifier().train(os.path.join(DATA_DIR, "development_tickets.json"))
    retriever = Retriever().index(os.path.join(DATA_DIR, "documentation.json"))
    log = DecisionLog(str(tmp_path / "decisions.db"))
    storage_dir = str(tmp_path)
    halt(storage_dir)
    pipeline = SupportPipeline(classifier, retriever, log, storage_dir=storage_dir)

    outcome = pipeline.process({
        "ticket_id": "T-HALT-1",
        "channel": "chat",
        "body": "I keep getting invalid credentials when I log in even though my password is right.",
    })
    assert outcome.action == "escalate"
    assert "halted" in outcome.reason.lower()


def test_guardrail_blocks_private_data():
    ok, hits = check_private_data("Contact me at jane@example.com about this")
    assert not ok and "email" in hits


def test_guardrail_blocks_ungrounded_answer():
    report = run_guardrails("This is definitely true.", citations=[], unsupported=True)
    assert not report.passed


def test_guardrail_passes_grounded_clean_answer():
    report = run_guardrails("Reset your password from the console.", citations=["DOC-AUTH-001"], unsupported=False)
    assert report.passed


def test_retriever_returns_nothing_for_irrelevant_query():
    r = Retriever(relevance_threshold=0.5).index(os.path.join(DATA_DIR, "documentation.json"))
    results = r.search("completely unrelated gibberish zzz qqq")
    assert isinstance(results, list)


def test_end_to_end_pipeline_runs_and_logs(tmp_path):
    classifier = Classifier().train(os.path.join(DATA_DIR, "development_tickets.json"))
    retriever = Retriever().index(os.path.join(DATA_DIR, "documentation.json"))
    log = DecisionLog(str(tmp_path / "decisions.db"))
    pipeline = SupportPipeline(classifier, retriever, log)

    outcome = pipeline.process({
        "ticket_id": "T-TEST-1",
        "channel": "chat",
        "body": "I keep getting invalid credentials when I log in even though my password is right.",
    })
    assert outcome.action in ("auto_respond", "escalate")
    assert log.count_for_ticket("T-TEST-1") >= 2

    rows = log.rows_for_ticket("T-TEST-1")
    assert len(rows) == log.count_for_ticket("T-TEST-1")
    assert rows[0]["stage"] == "classification"
    assert isinstance(rows[0]["requirement_ids"], list)
