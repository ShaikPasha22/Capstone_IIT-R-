"""Classify: predict intent and urgency with a confidence score that reflects
actual accuracy (calibrated, not just the model's raw softmax). Falls back to
a defined low-confidence result rather than raising when it cannot classify.
Records the alternatives it considered, not only the winner.
"""
from __future__ import annotations
import json
import numpy as np
from dataclasses import dataclass, field
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.calibration import CalibratedClassifierCV

FALLBACK_INTENT = "unclear_request"
FALLBACK_URGENCY = "medium"


@dataclass
class ClassificationResult:
    intent: str
    intent_confidence: float
    urgency: str
    urgency_confidence: float
    alternatives: list[dict] = field(default_factory=list)


class Classifier:
    """One shared TF-IDF vectoriser, two calibrated logistic regression heads
    (intent, urgency), trained on development_tickets.json. Small, fast, and
    entirely free -- deliberately not an LLM call, since intent/urgency
    classification from ~500 labelled examples is exactly the kind of task a
    classical model handles well without spending API budget on it.
    """

    def __init__(self):
        self.vectorizer = TfidfVectorizer(stop_words="english", max_features=8000, ngram_range=(1, 2))
        self.intent_model: CalibratedClassifierCV | None = None
        self.urgency_model: CalibratedClassifierCV | None = None

    def train(self, development_tickets_path: str) -> "Classifier":
        with open(development_tickets_path) as f:
            tickets = json.load(f)

        texts = [f"{t.get('subject', '')} {t.get('body', '')}".strip() for t in tickets]
        # CalibratedClassifierCV's per-class-count check compares y == class_
        # element-wise; a plain Python list of str against a numpy string
        # scalar does not broadcast the way a numpy array does, and silently
        # reports zero examples for every class. Arrays avoid that.
        intents = np.array([t["labels"]["intent"] for t in tickets])
        urgencies = np.array([t["labels"]["urgency"] for t in tickets])

        X = self.vectorizer.fit_transform(texts)

        base_intent = LogisticRegression(max_iter=1000, class_weight="balanced")
        self.intent_model = CalibratedClassifierCV(base_intent, cv=3)
        self.intent_model.fit(X, intents)

        base_urgency = LogisticRegression(max_iter=1000, class_weight="balanced")
        self.urgency_model = CalibratedClassifierCV(base_urgency, cv=3)
        self.urgency_model.fit(X, urgencies)
        return self

    def predict(self, text: str) -> ClassificationResult:
        if self.intent_model is None or self.urgency_model is None:
            raise RuntimeError("Classifier.train() must be called before predict()")
        if not text.strip():
            return ClassificationResult(FALLBACK_INTENT, 0.0, FALLBACK_URGENCY, 0.0)

        X = self.vectorizer.transform([text])

        intent_probs = self.intent_model.predict_proba(X)[0]
        intent_classes = self.intent_model.classes_
        intent_ranked = sorted(zip(intent_classes, intent_probs), key=lambda p: -p[1])

        urgency_probs = self.urgency_model.predict_proba(X)[0]
        urgency_classes = self.urgency_model.classes_
        urgency_top_idx = urgency_probs.argmax()

        alternatives = [
            {"value": cls, "confidence": round(float(p), 4)} for cls, p in intent_ranked[1:4]
        ]

        return ClassificationResult(
            intent=intent_ranked[0][0],
            intent_confidence=round(float(intent_ranked[0][1]), 4),
            urgency=urgency_classes[urgency_top_idx],
            urgency_confidence=round(float(urgency_probs[urgency_top_idx]), 4),
            alternatives=alternatives,
        )
