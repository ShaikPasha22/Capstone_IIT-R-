"""Threshold sweep: CONFIDENCE_THRESHOLD (0.55 by default, see .env.example)
was a placeholder, not a measured value. This sweeps it against
data/development_tickets.json, which carries expected_route and
must_not_auto_respond labels, and reports precision/recall/cost at each
candidate value so the default can be justified rather than assumed.

Reuses the same Classifier, Retriever and route.decide() the live pipeline
uses -- this is not a separate model, it is the same routing logic run
across a range of thresholds instead of one.

Run with `python -m scripts.tune_threshold`.
"""
from __future__ import annotations
import json
import os

from src.classify import Classifier
from src.retrieve import Retriever
from src.route import decide

DATA_DIR = os.getenv("DATA_DIR", "./data")
OUTPUT_PATH = os.path.join("evaluation", "results", "threshold_sweep.json")

THRESHOLDS = [round(0.30 + 0.05 * i, 2) for i in range(13)]  # 0.30 .. 0.90

# A ticket that should never be auto-answered but is, is worse than one that
# should be auto-answered but gets escalated: the second just costs an agent's
# time, the first is the failure mode the hard-block list and this threshold
# exist to prevent. Weighted accordingly in the cost score below.
COST_FALSE_AUTO_RESPOND = 5
COST_FALSE_ESCALATE = 1


def _predict_all(tickets: list[dict], classifier: Classifier, retriever: Retriever) -> list[dict]:
    """Classify and retrieve once per ticket -- independent of threshold --
    so the sweep below only re-runs the cheap routing decision, not the
    classifier or retriever, for every candidate threshold.
    """
    predictions = []
    for t in tickets:
        text = f"{t.get('subject', '')} {t.get('body', '')}".strip()
        classification = classifier.predict(text)
        passages = retriever.search(text)
        predictions.append({
            "labels": t.get("labels") or {},
            "intent": classification.intent,
            "intent_confidence": classification.intent_confidence,
            "urgency": classification.urgency,
            "retrieved_any": len(passages) > 0,
        })
    return predictions


def _evaluate_threshold(predictions: list[dict], threshold: float) -> dict:
    tp = fp = tn = fn = 0
    cost = 0
    labelled = 0

    for p in predictions:
        labels = p["labels"]
        expected_route = labels.get("expected_route")
        if not expected_route:
            continue
        labelled += 1

        routing = decide(
            intent=p["intent"],
            intent_confidence=p["intent_confidence"],
            retrieved_any=p["retrieved_any"],
            urgency=p["urgency"],
            confidence_threshold=threshold,
        )
        predicted_auto = routing.action == "auto_respond"
        expected_auto = expected_route == "auto_respond"
        must_not = bool(labels.get("must_not_auto_respond"))

        if predicted_auto and expected_auto:
            tp += 1
        elif predicted_auto and not expected_auto:
            fp += 1
            cost += COST_FALSE_AUTO_RESPOND if must_not else COST_FALSE_ESCALATE
        elif not predicted_auto and not expected_auto:
            tn += 1
        else:
            fn += 1
            cost += COST_FALSE_ESCALATE

    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    accuracy = (tp + tn) / labelled if labelled else None

    return {
        "threshold": threshold,
        "labelled_tickets": labelled,
        "true_positive_auto_respond": tp,
        "false_positive_auto_respond": fp,
        "true_negative_escalate": tn,
        "false_negative_escalate": fn,
        "precision": round(precision, 4) if precision is not None else None,
        "recall": round(recall, 4) if recall is not None else None,
        "accuracy": round(accuracy, 4) if accuracy is not None else None,
        "cost": cost,
    }


def sweep(tickets_path: str) -> dict:
    with open(tickets_path, encoding="utf-8") as f:
        tickets = json.load(f)

    classifier = Classifier().train(tickets_path)
    retriever = Retriever().index(os.path.join(DATA_DIR, "documentation.json"))
    predictions = _predict_all(tickets, classifier, retriever)

    results = [_evaluate_threshold(predictions, t) for t in THRESHOLDS]
    best_by_cost = min(results, key=lambda r: r["cost"])

    return {
        "tickets_file": tickets_path,
        "results": results,
        "recommended_threshold": best_by_cost["threshold"],
        "recommended_reason": (
            f"Lowest weighted cost ({best_by_cost['cost']}) across the swept range, "
            f"where an auto-response on a must_not_auto_respond ticket costs "
            f"{COST_FALSE_AUTO_RESPOND}x a false escalation."
        ),
    }


def main() -> None:
    report = sweep(os.path.join(DATA_DIR, "development_tickets.json"))

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"{'threshold':>10} {'precision':>10} {'recall':>8} {'accuracy':>9} {'cost':>6}")
    for r in report["results"]:
        print(
            f"{r['threshold']:>10.2f} "
            f"{r['precision'] if r['precision'] is not None else float('nan'):>10.4f} "
            f"{r['recall'] if r['recall'] is not None else float('nan'):>8.4f} "
            f"{r['accuracy'] if r['accuracy'] is not None else float('nan'):>9.4f} "
            f"{r['cost']:>6}"
        )
    print(f"\nRecommended: {report['recommended_threshold']} -- {report['recommended_reason']}")
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
