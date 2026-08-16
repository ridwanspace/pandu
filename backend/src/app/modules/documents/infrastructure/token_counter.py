"""tiktoken-backed token counter.

The domain chunker receives counting as a plain callable (``TokenCounter``),
so tiktoken stays out of the domain layer. Encoders are cached per process —
loading one is expensive (BPE table download / parse).
"""

from __future__ import annotations

from functools import lru_cache

import structlog
import tiktoken

from app.modules.documents.domain.chunking import TokenCounter

logger = structlog.get_logger(__name__)

_DEFAULT_ENCODING = "cl100k_base"
_FALLBACK_ENCODING = "o200k_base"


@lru_cache(maxsize=4)
def _load_encoding(name: str) -> tiktoken.Encoding | None:
    for candidate in (name, _FALLBACK_ENCODING):
        try:
            return tiktoken.get_encoding(candidate)
        except Exception:  # loading may fail offline (BPE table fetch)
            logger.warning("tiktoken_encoding_unavailable", encoding=candidate)
    return None


def build_token_counter(encoding_name: str = _DEFAULT_ENCODING) -> TokenCounter:
    """Return a counter for ``encoding_name``.

    Falls back to ``o200k_base``, then to a chars/4 heuristic so ingestion
    keeps working in fully offline environments.
    """
    encoding = _load_encoding(encoding_name)
    if encoding is None:
        logger.warning("token_counter_heuristic_fallback")
        return _approximate_count

    def count(text: str) -> int:
        return len(encoding.encode(text, disallowed_special=()))

    return count


def _approximate_count(text: str) -> int:
    # ~4 chars per token is the usual English-text rule of thumb.
    return max(1, len(text) // 4)
