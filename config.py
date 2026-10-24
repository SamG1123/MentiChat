"""Centralized configuration, loaded from environment variables / .env.

Nothing secret lives in source code. Copy .env.example to .env and fill it in.
"""
import os
import secrets
from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.environ.get(name, "")
    return value


class Config:
    GEMINI_API_KEY = _require("GEMINI_API_KEY")
    GEMINI_CHAT_MODEL = os.environ.get("GEMINI_CHAT_MODEL", "gemini-3.5-flash")
    GEMINI_EMBEDDING_MODEL = os.environ.get("GEMINI_EMBEDDING_MODEL", "models/embedding-001")

    QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
    QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY") or None
    QDRANT_TIMEOUT = float(os.environ.get("QDRANT_TIMEOUT", "120"))
    QDRANT_BATCH_SIZE = int(os.environ.get("QDRANT_BATCH_SIZE", "16"))
    QDRANT_PATH = os.environ.get("QDRANT_PATH", ".qdrant")
    QDRANT_COLLECTION = os.environ.get("QDRANT_COLLECTION", "ncert_chunks")
    EMBEDDING_DIM = 768  # embedding-001 / text-embedding-004 output size

    MONGODB_URI = _require("MONGODB_URI")
    MONGODB_DATABASE = os.environ.get("MONGODB_DATABASE", "mentichat")

    FLASK_SECRET_KEY = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)
    SUBJECTS = [s.strip() for s in os.environ.get("SUBJECTS", "Mathematics,Physics,Chemistry").split(",") if s.strip()]
    GRADES = [g.strip() for g in os.environ.get("GRADES", "11,12").split(",") if g.strip()]

    # Retrieval tuning
    TOP_K = int(os.environ.get("TOP_K", "5"))
    CHUNK_SIZE_CHARS = int(os.environ.get("CHUNK_SIZE_CHARS", "1200"))
    CHUNK_OVERLAP_CHARS = int(os.environ.get("CHUNK_OVERLAP_CHARS", "200"))
    MIN_SCORE = float(os.environ.get("MIN_SCORE", "0.5"))  # below this, treat as "not found in textbook"

    def validate(self):
        missing = []
        if not self.GEMINI_API_KEY:
            missing.append("GEMINI_API_KEY")
        return missing


config = Config()
