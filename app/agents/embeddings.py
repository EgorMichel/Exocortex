"""Lightweight local embeddings for proactive graph analysis."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class LocalTextEmbeddingService:
    """Create deterministic hashed bag-of-words vectors without external services."""

    dimensions: int = 64

    def embed(self, text: str) -> list[float]:
        """Embed text into a normalized dense vector."""
        vector = [0.0] * self.dimensions
        for term in re.findall(r"\w+", text.lower(), flags=re.UNICODE):
            if len(term) <= 2:
                continue
            digest = hashlib.sha256(term.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]


def cosine_similarity(left: list[float] | None, right: list[float] | None) -> float:
    """Return cosine similarity for two vectors."""
    if not left or not right or len(left) != len(right):
        return 0.0

    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0

    dot_product = sum(left_value * right_value for left_value, right_value in zip(left, right))
    return dot_product / (left_norm * right_norm)
