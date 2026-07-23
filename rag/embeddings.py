"""Thin wrapper around Gemini's embedding API.

Separated from retriever/ingest so both share one retry-hardened code path.
"""
import google.generativeai as genai
from tenacity import retry, stop_after_attempt, wait_exponential

from config import config
from rag.embeddings_open import embed_texts_local

genai.configure(api_key=config.GEMINI_API_KEY)
_FALLBACK_EMBEDDING_MODEL = "models/embedding-001"
_USE_LOCAL_EMBEDDINGS = False


def _embed_with_model(texts: list[str], task_type: str, model_name: str) -> list[list[float]]:
    result = genai.embed_content(
        model=model_name,
        content=texts,
        task_type=task_type,
    )
    return result["embedding"]


def _should_fallback(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        config.GEMINI_EMBEDDING_MODEL != _FALLBACK_EMBEDDING_MODEL
        and "embed" in message
        and ("not found" in message or "not supported" in message)
    )


def using_local_embeddings() -> bool:
    return _USE_LOCAL_EMBEDDINGS


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=2, max=20))
def embed_texts(texts: list[str], task_type: str) -> list[list[float]]:
    """Embed a batch of strings.

    task_type: "RETRIEVAL_DOCUMENT" when embedding textbook chunks for storage,
               "RETRIEVAL_QUERY" when embedding a user's question.
    """
    if not texts:
        return []
    try:
        return _embed_with_model(texts, task_type, config.GEMINI_EMBEDDING_MODEL)
    except Exception as exc:
        try:
            if _should_fallback(exc):
                global _USE_LOCAL_EMBEDDINGS
                _USE_LOCAL_EMBEDDINGS = True
                return _embed_with_model(texts, task_type, _FALLBACK_EMBEDDING_MODEL)
        except Exception:
            pass
        _USE_LOCAL_EMBEDDINGS = True
        return embed_texts_local(texts)


def embed_query(text: str) -> list[float]:
    return embed_texts([text], task_type="RETRIEVAL_QUERY")[0]


def embed_documents(texts: list[str]) -> list[list[float]]:
    # Gemini's batch embedding endpoint caps around 100 items per call.
    out = []
    batch_size = 90
    for i in range(0, len(texts), batch_size):
        out.extend(embed_texts(texts[i:i + batch_size], task_type="RETRIEVAL_DOCUMENT"))
    return out
