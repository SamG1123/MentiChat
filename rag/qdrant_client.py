"""Qdrant client selection and fallback helpers."""
from __future__ import annotations

from urllib.parse import urlparse

from qdrant_client import QdrantClient

from config import config


_client: QdrantClient | None = None


def _is_loopback_url(url: str) -> bool:
    hostname = urlparse(url).hostname or ""
    return hostname in {"localhost", "127.0.0.1", "::1"}


def _build_client() -> QdrantClient:
    if config.QDRANT_URL:
        remote_client = QdrantClient(url=config.QDRANT_URL, api_key=config.QDRANT_API_KEY)
        try:
            remote_client.get_collections()
        except Exception:
            if _is_loopback_url(config.QDRANT_URL):
                return QdrantClient(path=config.QDRANT_PATH)
            raise
        return remote_client

    return QdrantClient(path=config.QDRANT_PATH)


def get_client() -> QdrantClient:
    global _client
    if _client is None:
        _client = _build_client()
    return _client