"""Evaluation harness: processes every ticket in --input, unattended, and
writes a metrics report to --output. Takes an input path and an output path
as arguments rather than a hardcoded filename, because it is run against a
file it has never seen (A9). No manual intervention, no restarts, no skipped
tickets -- failures on one ticket are caught and logged, not allowed to stop
the run.
"""
from __future__ import annotations
import argparse
import json
import os
import time
from collections import defaultdict
from datetime import datetime, timezone

from src.classify import Classifier
from src.retrieve import Retriever
from src.logging_store import DecisionLog
from src.pipeline import SupportPipeline


def run(input_path: str, output_dir: str, data_dir: str = "./data", confidence_threshold: float = 0.55) -> dict:
    os.makedirs(output_dir, exist_ok=True)

    classifier = Classifier().train(f"{data_dir}/development_tickets.json")
    retriever = Retriever().index(f"{data_dir}/documentation.json")
    decision_log = DecisionLog(os.path.join(output_dir, "decisions.db"))
    pipeline = SupportPipeline(classifier, retriever, decision_log, confidence_threshold=confidence_threshold)

    with open(input_path) as f:
        tickets = json.load(f)

    outcomes = []
    errors = 0
    latencies = []
    start = time.time()

    for raw in tickets:
        t0 = time.time()
        try:
            outcome = pipeline.process(raw)
            outcomes.append({"raw": raw, "outcome": outcome})
        except Exception as exc:  # A11: never let one bad ticket stop the run
            errors += 1
            outcomes.append({"raw": raw, "outcome": None, "error": str(exc)})
        latencies.append(time.time() - t0)

    total_time = time.time() - start

    # --- business metrics ---
    n = len(tickets)
    auto = sum(1 for o in outcomes if o["outcome"] and o["outcome"].action == "auto_respond")
    escalated = sum(1 for o in outcomes if o["outcome"] and o["outcome"].action == "escalate")
    blocked = sum(1 for o in outcomes if o["outcome"] and o["outcome"].blocked)

    correct_intent = 0
    labelled = 0
    correct_route = 0
    for o in outcomes:
        raw, outcome = o["raw"], o["outcome"]
        if outcome is None:
            continue
        labels = raw.get("labels")
        if labels:
            labelled += 1
            if labels.get("intent") == outcome.intent:
                correct_intent += 1
            expected_route = labels.get("expected_route")
            if expected_route and expected_route == outcome.action:
                correct_route += 1

    hit_rate = sum(1 for o in outcomes if o["outcome"] and o["outcome"].retrieved_sources) / n if n else 0
    latencies_sorted = sorted(latencies)
    p50 = latencies_sorted[len(latencies_sorted) // 2] if latencies_sorted else 0
    p95 = latencies_sorted[int(len(latencies_sorted) * 0.95) - 1] if latencies_sorted else 0

    report = {
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_file": input_path,
        "volume": {
            "tickets_processed": n,
            "auto_responded": auto,
            "escalated": escalated,
            "blocked_by_guardrail": blocked,
            "errors": errors,
        },
        "business": {
            "automation_rate": round(auto / n, 4) if n else 0,
            "escalation_rate": round(escalated / n, 4) if n else 0,
        },
        "technical": {
            "intent_accuracy_vs_labels": round(correct_intent / labelled, 4) if labelled else None,
            "routing_agreement_vs_expected": round(correct_route / labelled, 4) if labelled else None,
            "retrieval_hit_rate": round(hit_rate, 4),
            "latency_seconds_p50": round(p50, 4),
            "latency_seconds_p95": round(p95, 4),
        },
        "governance": {
            "decisions_logged": sum(decision_log.count_for_ticket(o["raw"].get("ticket_id", "UNSPECIFIED")) for o in outcomes),
            "guardrail_blocks": blocked,
        },
        "total_run_time_seconds": round(total_time, 2),
    }

    with open(os.path.join(output_dir, "metrics_report.json"), "w") as f:
        json.dump(report, f, indent=2)

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--data-dir", default="./data")
    args = parser.parse_args()
    result = run(args.input, args.output, args.data_dir)
    print(json.dumps(result, indent=2))
