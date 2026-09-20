"""FastAPI app: the interface layer. Wires the trained classifier and indexed
retriever once at startup, exposes /process_ticket for a single ticket,
/health for liveness, the operator console, and the admin kill switch.
"""
from __future__ import annotations
import glob
import json
import os
import time
import warnings
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

from src.classify import Classifier
from src.retrieve import Retriever
from src.logging_store import DecisionLog
from src.pipeline import SupportPipeline
from src.console import render_console
from src import admin as admin_module

load_dotenv()

DATA_DIR = os.getenv("DATA_DIR", "./data")
STORAGE_DIR = os.path.dirname(os.getenv("DATABASE_PATH", "./storage/decisions.db")) or "./storage"
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.55"))
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "change-me")
EXPOSE_ADMIN_TOKEN_ENDPOINT = os.getenv("EXPOSE_ADMIN_TOKEN_ENDPOINT", "true").lower() == "true"

if ADMIN_TOKEN == "change-me":
    warnings.warn(
        "ADMIN_TOKEN is left at the default 'change-me'. Set a real value before "
        "exposing /admin/halt or /admin/resume outside a local machine.",
        stacklevel=1,
    )

if EXPOSE_ADMIN_TOKEN_ENDPOINT:
    warnings.warn(
        "GET /admin/reveal-token is enabled and hands back the real ADMIN_TOKEN to "
        "anyone who requests it -- there is no server-side gate on this endpoint, "
        "only a client-side arithmetic puzzle in the console UI, which stops "
        "nothing but casual browser use. This is a local-development convenience "
        "only. Set EXPOSE_ADMIN_TOKEN_ENDPOINT=false before running this anywhere "
        "reachable by more than your own machine.",
        stacklevel=1,
    )

app = FastAPI(title="CloudServe Support Copilot")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

classifier = Classifier().train(f"{DATA_DIR}/development_tickets.json")
retriever = Retriever().index(f"{DATA_DIR}/documentation.json")
decision_log = DecisionLog(os.getenv("DATABASE_PATH", "./storage/decisions.db"))
pipeline = SupportPipeline(
    classifier, retriever, decision_log,
    confidence_threshold=CONFIDENCE_THRESHOLD, storage_dir=STORAGE_DIR,
)


def _load_tickets_by_id(*filenames: str) -> dict:
    by_id: dict = {}
    for filename in filenames:
        path = os.path.join(DATA_DIR, filename)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            for ticket in json.load(f):
                by_id[ticket["ticket_id"]] = ticket
    return by_id


def _load_docs_by_id() -> dict:
    path = os.path.join(DATA_DIR, "documentation.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return {doc["doc_id"]: doc for doc in json.load(f)}


TICKETS_BY_ID = _load_tickets_by_id("validation_tickets.json", "development_tickets.json")
DOCS_BY_ID = _load_docs_by_id()


def _load_validation_tickets() -> list[dict]:
    path = os.path.join(DATA_DIR, "validation_tickets.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _curate_sample_tickets(tickets: list[dict], per_bucket: int = 3) -> list[dict]:
    """A handful of validation tickets picked to demonstrate a different
    outcome each, rather than the whole set -- bucketed by label alone (no
    pipeline run needed to pick them), then the real outcome is computed once
    at startup so the console's sidebar badges reflect an actual routing
    decision, not a guess at one.
    """
    buckets: dict[str, list[dict]] = {"policy_block": [], "no_grounding": [], "answerable": [], "other": []}
    for t in tickets:
        labels = t.get("labels") or {}
        if not labels:
            continue
        if labels.get("must_not_auto_respond"):
            buckets["policy_block"].append(t)
        elif not labels.get("answerable_from_docs", True):
            buckets["no_grounding"].append(t)
        elif labels.get("expected_route") == "auto_respond":
            buckets["answerable"].append(t)
        else:
            buckets["other"].append(t)

    curated: list[dict] = []
    for bucket in buckets.values():
        curated.extend(bucket[:per_bucket])
    return curated


def _build_sample_previews() -> dict[str, dict]:
    previews = {}
    for ticket in _curate_sample_tickets(_load_validation_tickets()):
        outcome = pipeline.process_dict(ticket)
        previews[ticket["ticket_id"]] = {
            "ticket_id": ticket["ticket_id"],
            "channel": ticket.get("channel"),
            "customer_tier": ticket.get("customer_tier"),
            "language_fluency": ticket.get("language_fluency"),
            "subject": ticket.get("subject") or ticket.get("body", "")[:60],
            "action": outcome["action"],
            "rule": outcome["rule"],
            "reason": outcome["reason"],
        }
    return previews


SAMPLE_PREVIEWS = _build_sample_previews()


class TicketIn(BaseModel):
    ticket_id: str
    channel: str
    subject: str | None = ""
    body: str
    customer_id: str | None = None
    customer_tier: str | None = "standard"
    customer_region: str | None = None
    language_fluency: str | None = None
    received_at: str | None = None


def _require_admin(x_admin_token: str | None) -> None:
    if not x_admin_token or x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Missing or incorrect X-Admin-Token header.")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/process_ticket")
def process_ticket(ticket: TicketIn):
    return pipeline.process_dict(ticket.model_dump())


@app.get("/")
def console():
    return render_console()


@app.get("/api/samples")
def samples():
    """A curated handful of validation tickets, one per outcome bucket, each
    with its real precomputed routing badge -- not the full 580-ticket set,
    so picking one is browsing a demo, not a database.
    """
    return list(SAMPLE_PREVIEWS.values())


@app.get("/api/ticket/{ticket_id}")
def ticket_decision(ticket_id: str):
    raw = TICKETS_BY_ID.get(ticket_id)
    if raw is None:
        raise HTTPException(status_code=404, detail=f"No ticket '{ticket_id}' in the sample data.")
    started = time.perf_counter()
    outcome = pipeline.process_dict(raw)
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    return {
        "ticket": raw,
        "outcome": outcome,
        "trace": decision_log.rows_for_ticket(ticket_id),
        "latency_ms": latency_ms,
    }


@app.get("/api/corpus/{doc_id}")
def corpus_article(doc_id: str):
    doc = DOCS_BY_ID.get(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"No article '{doc_id}' in the corpus.")
    return doc


@app.get("/api/stats")
def stats():
    """The headline figures from the most recent evaluation harness run, if
    one has been done. Read from disk, not recomputed, so this stays cheap.
    corpus_size and decisions_logged_total are always available -- they don't
    need a harness run, just the corpus file and the live decision log.
    """
    base = {
        "corpus_size": len(DOCS_BY_ID),
        "decisions_logged_total": decision_log.count_all(),
    }
    candidates = sorted(
        glob.glob(os.path.join("evaluation", "results", "**", "metrics_report.json"), recursive=True),
        key=os.path.getmtime,
        reverse=True,
    )
    if not candidates:
        return {**base, "available": False, "message": "No evaluation run found. Run evaluation.harness first."}
    with open(candidates[0], encoding="utf-8") as f:
        report = json.load(f)
    return {**base, "available": True, "source": candidates[0], "report": report}


@app.get("/admin/status")
def admin_status():
    return {"halted": admin_module.is_halted(STORAGE_DIR)}


@app.get("/admin/reveal-token")
def admin_reveal_token():
    """Local-dev convenience: hands back the real ADMIN_TOKEN.

    There is deliberately no server-side check here beyond the
    EXPOSE_ADMIN_TOKEN_ENDPOINT flag -- the arithmetic puzzle in the console
    UI is a client-side speed bump, not authentication. Anyone who can reach
    this URL at all gets the token, same as anyone who can read .env on this
    machine. Set EXPOSE_ADMIN_TOKEN_ENDPOINT=false before running this
    anywhere reachable by more than your own machine.
    """
    if not EXPOSE_ADMIN_TOKEN_ENDPOINT:
        raise HTTPException(status_code=404, detail="Disabled (EXPOSE_ADMIN_TOKEN_ENDPOINT=false).")
    return {"token": ADMIN_TOKEN}


@app.post("/admin/halt")
def admin_halt(x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    admin_module.halt(STORAGE_DIR)
    return {"halted": True}


@app.post("/admin/resume")
def admin_resume(x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    admin_module.resume(STORAGE_DIR)
    return {"halted": False}
