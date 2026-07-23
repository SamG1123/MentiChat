"""Deterministic local fallback embeddings.

Used when Gemini embeddings are unavailable in the current environment.
The vectors are intentionally simple, but stable across runs and shared by
ingest/query so Qdrant search still works end to end.
"""
from __future__ import annotations

import hashlib
import math
import re

from config import config


_TOKEN_RE = re.compile(r"[\w']+", re.UNICODE)


def _hash_index(token: str, dimension: int) -> int:
	digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
	return int.from_bytes(digest, "big") % dimension


def _hash_sign(token: str) -> float:
	digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
	return 1.0 if digest[0] & 1 else -1.0


def embed_texts_local(texts: list[str]) -> list[list[float]]:
	dimension = config.EMBEDDING_DIM
	vectors: list[list[float]] = []

	for text in texts:
		vector = [0.0] * dimension
		tokens = _TOKEN_RE.findall(text.lower())

		for i, token in enumerate(tokens):
			index = _hash_index(token, dimension)
			vector[index] += 1.0 * _hash_sign(token)

			if i + 1 < len(tokens):
				bigram = f"{token} {tokens[i + 1]}"
				index = _hash_index(bigram, dimension)
				vector[index] += 0.5 * _hash_sign(bigram)

		norm = math.sqrt(sum(value * value for value in vector))
		if norm:
			vector = [value / norm for value in vector]
		vectors.append(vector)

	return vectors
