"""Retrieve: search the documentation corpus and return ranked, identifiable
passages. Returns nothing rather than something irrelevant when nothing
clears the relevance threshold.

Uses TF-IDF + cosine similarity rather than a downloaded embedding model,
because this sandbox has no route to huggingface.co. The interface
(index() / search()) is the same shape a Chroma + sentence-transformers
implementation would expose, so swapping the backend later is a
constructor-level change, not a rewrite of anything that calls this module.
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def _chunk(text: str, chunk_size: int = 800, overlap: int = 120) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= chunk_size:
        return [text]
    chunks, start = [], 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap
    return chunks


@dataclass
class Passage:
    doc_id: str
    title: str
    chunk_text: str
    score: float


class Retriever:
    def __init__(self, relevance_threshold: float = 0.12, top_k: int = 5):
        self.relevance_threshold = relevance_threshold
        self.top_k = top_k
        self.vectorizer = TfidfVectorizer(stop_words="english", max_features=20000)
        self._chunks: list[str] = []
        self._meta: list[tuple[str, str]] = []  # (doc_id, title)
        self._matrix = None

    def index(self, documentation_path: str) -> "Retriever":
        with open(documentation_path) as f:
            docs = json.load(f)
        for doc in docs:
            for chunk in _chunk(doc["content"]):
                self._chunks.append(chunk)
                self._meta.append((doc["doc_id"], doc["title"]))
        self._matrix = self.vectorizer.fit_transform(self._chunks)
        return self

    def search(self, query: str) -> list[Passage]:
        if self._matrix is None:
            raise RuntimeError("Retriever.index() must be called before search()")
        if not query.strip():
            return []
        q_vec = self.vectorizer.transform([query])
        scores = cosine_similarity(q_vec, self._matrix)[0]
        ranked_idx = scores.argsort()[::-1][: self.top_k]
        results = []
        for i in ranked_idx:
            score = float(scores[i])
            if score < self.relevance_threshold:
                continue
            doc_id, title = self._meta[i]
            results.append(Passage(doc_id=doc_id, title=title, chunk_text=self._chunks[i], score=round(score, 4)))
        return results
