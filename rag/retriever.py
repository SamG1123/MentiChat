"""Query-time retrieval: embed the question, search Qdrant, return scored chunks."""
from dataclasses import dataclass
from typing import List, Optional

from qdrant_client.http import models as qmodels

from config import config
from rag.embeddings import embed_query, using_local_embeddings
from rag.qdrant_client import get_client


@dataclass
class RetrievedChunk:
    text: str
    subject: str
    grade: str
    source_file: str
    chapter: str
    page: int
    score: float
    images: List[str]  # list of image URLs associated with this chunk


def retrieve(query: str, subject: str | None = None, grade: str | None = None,
             top_k: int | None = None) -> list[RetrievedChunk]:
    top_k = top_k or config.TOP_K
    client = get_client()

    conditions = []
    if subject and subject.lower() != "all":
        conditions.append(qmodels.FieldCondition(key="subject", match=qmodels.MatchValue(value=subject)))
    if grade and str(grade).lower() != "all":
        conditions.append(qmodels.FieldCondition(key="grade", match=qmodels.MatchValue(value=str(grade))))
    query_filter = qmodels.Filter(must=conditions) if conditions else None

    vector = embed_query(query)
    score_floor = 0.03 if using_local_embeddings() else config.MIN_SCORE
    hits = client.search(
        collection_name=config.QDRANT_COLLECTION,
        query_vector=vector,
        query_filter=query_filter,
        limit=top_k,
    )

    results = []
    for hit in hits:
        if hit.score < score_floor:
            continue
        p = hit.payload
        results.append(RetrievedChunk(
            text=p["text"],
            subject=p["subject"],
            grade=p.get("grade", "?"),
            source_file=p["source_file"],
            chapter=p["chapter"],
            page=p["page"],
            score=hit.score,
            images=p.get("images", []),
        ))
    return results


def format_context(chunks: list[RetrievedChunk]) -> str:
    """Render retrieved chunks into a numbered context block the model can cite by index."""
    if not chunks:
        return ""
    parts = []
    for i, c in enumerate(chunks, start=1):
        parts.append(f"[{i}] (Class {c.grade} {c.subject} — {c.chapter}, p.{c.page})\n{c.text}")
    return "\n\n".join(parts)