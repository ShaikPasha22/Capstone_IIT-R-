"""Tracing: optional LangSmith visibility into each pipeline stage.

Off by default and with zero effect on the offline/no-API-key guarantee
described in the README -- this follows the same optional-enhancement
pattern as `OPENROUTER_API_KEY` in src/generate.py. Only if LANGSMITH_API_KEY
is set (and the `langsmith` package is installed) do pipeline stages get
wrapped and sent to smith.langchain.com; otherwise `traceable` is a plain
identity decorator and every call is exactly as fast and as local as before.
"""
from __future__ import annotations
import os


def _resolve_traceable():
    if not os.getenv("LANGSMITH_API_KEY"):
        return None
    try:
        from langsmith import traceable as _langsmith_traceable
        return _langsmith_traceable
    except ImportError:
        return None


_real_traceable = _resolve_traceable()
TRACING_ENABLED = _real_traceable is not None


def _noop_traceable(*_args, **_kwargs):
    def decorator(fn):
        return fn
    return decorator


traceable = _real_traceable if _real_traceable is not None else _noop_traceable
