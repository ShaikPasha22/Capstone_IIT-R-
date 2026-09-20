# ADR-001: TF-IDF retrieval instead of embeddings

## Status
Accepted

## Context
The originally specified retrieval stack was a vector store (Chroma) over
sentence-transformer embeddings (`all-MiniLM-L6-v2`). That model has to be
downloaded from huggingface.co on first use. Several environments this
system needs to run in — CI runners, sandboxed evaluation environments,
offline demos — do not have a route to that host, and the system's own
design goal is to run with **no network connection required** (see the
README). A retrieval backend that hard-fails without internet access is not
acceptable for a component this central.

## Decision
`src/retrieve.py` implements `Retriever` with scikit-learn's
`TfidfVectorizer` + cosine similarity over chunked documentation text,
instead of a downloaded embedding model.

The interface is written to be backend-agnostic: `Retriever.index(path)` and
`Retriever.search(query) -> list[Passage]` are the only two methods anything
else in the codebase calls. Swapping in an embedding-based implementation
later — in an environment that does have model access — is a constructor
change behind the same interface, not a rewrite of `pipeline.py`,
`route.py`, or anything downstream.

## Consequences
- No network access or GPU is required to run the system at all, including
  in CI.
- Retrieval quality is bounded by lexical overlap: a customer's phrasing has
  to share vocabulary with the documentation, not just meaning. This is a
  real limitation for paraphrased questions and is worth re-measuring if the
  system is ever given model access.
- Because the interface is stable, this decision is reversible without
  touching any calling code — only `src/retrieve.py`'s internals and the
  constructor call in `src/api.py` / `evaluation/harness.py` would change.
