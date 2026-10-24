"""PDF -> chunks -> embeddings -> Qdrant.

Run via scripts/ingest_cli.py, not directly.
"""
import hashlib
import logging
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from pypdf import PdfReader
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from config import config
from rag.embeddings import embed_documents
from rag.qdrant_client import get_client

logger = logging.getLogger("ncert-tutor.ingest")

# Directory where extracted images will be stored (served via Flask static)
IMG_DIR = Path("static") / "images"
IMG_DIR.mkdir(parents=True, exist_ok=True)

# Directory where 3D model files are stored (served via Flask static)
MODELS_DIR = Path("static") / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

# Known 3D model extensions we look for
MODEL_EXTENSIONS = {".glb", ".gltf", ".obj"}


@dataclass
class Chunk:
    text: str
    subject: str
    grade: str
    source_file: str
    chapter: str
    page: int
    images: List[str]  # relative URLs to images, e.g., "/static/images/filename.png"
    models: List[str]  # relative URLs to 3D models, e.g., "/static/models/filename.glb"


def ensure_collection(client):
    existing = [c.name for c in client.get_collections().collections]
    if config.QDRANT_COLLECTION not in existing:
        client.create_collection(
            collection_name=config.QDRANT_COLLECTION,
            vectors_config=qmodels.VectorParams(
                size=config.EMBEDDING_DIM,
                distance=qmodels.Distance.COSINE,
            ),
        )
        _create_indexes(client)
    else:
        # Collection already exists (e.g. from the 11th-grade ingest run) — make sure
        # any indexes added since then (like "grade") exist too. This is a no-op if
        # they're already there, so it's safe to call every startup.
        _create_indexes(client)


def _create_indexes(client: QdrantClient):
    # Payload indexes make filtered search fast. Creating an index on a field
    # that doesn't exist on older points yet is harmless — Qdrant just won't
    # match those points against a filter on that field until they're backfilled.
    for field in ("subject", "grade"):
        try:
            client.create_payload_index(
                collection_name=config.QDRANT_COLLECTION,
                field_name=field,
                field_schema="keyword",
            )
        except Exception:
            pass  # index already exists


def _clean(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _chunk_page_text(text: str, size: int, overlap: int) -> list[str]:
    """Character-based sliding window chunker.

    Splits on paragraph boundaries where possible so chunks stay coherent
    (a formula or worked example rarely gets cut mid-sentence).
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks, current = [], ""
    for para in paragraphs:
        if len(current) + len(para) + 1 <= size:
            current = f"{current}\n{para}".strip()
        else:
            if current:
                chunks.append(current)
            if len(para) > size:
                # paragraph itself too long (e.g. a dense derivation) -> hard-split with overlap
                start = 0
                while start < len(para):
                    end = start + size
                    chunks.append(para[start:end])
                    start = end - overlap
                current = ""
            else:
                current = para
    if current:
        chunks.append(current)
    return chunks


def _get_associated_models(pdf_path: Path) -> List[str]:
    """Return a list of URLs for 3D model files associated with the given PDF.

    Looks for files in MODELS_DIR that start with the PDF's stem (without extension)
    and have a known 3D extension.
    """
    model_urls = []
    if not MODELS_DIR.exists():
        return model_urls

    stem = pdf_path.stem  # filename without extension
    for ext in MODEL_EXTENSIONS:
        # Pattern: stem_*ext or just stem+ext? We'll allow both.
        # First, try exact stem + ext
        model_path = MODELS_DIR / f"{stem}{ext}"
        if model_path.is_file():
            model_urls.append(f"/static/models/{model_path.name}")
            continue
        # Then try stem + _* + ext (e.g., stem_part1.glb)
        for model_file in MODELS_DIR.glob(f"{stem}_*{ext}"):
            if model_file.is_file():
                model_urls.append(f"/static/models/{model_file.name}")
        # Also try without underscore? Already tried exact stem.
    # Remove duplicates while preserving order
    seen = set()
    unique_urls = []
    for url in model_urls:
        if url not in seen:
            seen.add(url)
            unique_urls.append(url)
    return unique_urls


def load_pdf(path: Path, subject: str, grade: str, chapter: str | None = None) -> list[Chunk]:
    reader = PdfReader(str(path))
    chapter = chapter or path.stem
    chunks: list[Chunk] = []
    # Get associated models for this PDF (same for all chunks from this PDF)
    associated_models = _get_associated_models(path)
    for page_num, page in enumerate(reader.pages, start=1):
        raw = page.extract_text() or ""
        cleaned = _clean(raw)
        if not cleaned:
            continue

        # Extract images from the page
        page_images: List[str] = []
        try:
            page_images_iter = page.images if hasattr(page, "images") else []
            for img_idx, image_obj in enumerate(page_images_iter):
                try:
                    img_data = image_obj.data  # raw bytes
                    # Determine file extension; default to .png
                    # Try to get extension from /Name if available, but simple approach:
                    ext = ".png"
                    # Optionally, we could check for JPEG etc. based on /Subtype or data header.
                    img_filename = f"{path.stem}_page{page_num}_img{img_idx}{ext}"
                    img_path = IMG_DIR / img_filename
                    with open(img_path, "wb") as f:
                        f.write(img_data)
                    # URL path relative to static folder
                    image_url = f"/static/images/{img_filename}"
                    page_images.append(image_url)
                except Exception as e:
                    logger.warning(f"Failed to extract image {img_idx} on page {page_num} of {path.name}: {e}")
        except Exception as e:
            logger.warning(f"Skipping unsupported images on page {page_num} of {path.name}: {e}")

        # Chunk the text
        for piece in _chunk_page_text(cleaned, config.CHUNK_SIZE_CHARS, config.CHUNK_OVERLAP_CHARS):
            if len(piece) < 40:  # skip near-empty fragments (running headers, page numbers)
                continue
            chunks.append(
                Chunk(
                    text=piece,
                    subject=subject,
                    grade=grade,
                    source_file=path.name,
                    chapter=chapter,
                    page=page_num,
                    images=page_images,
                    models=associated_models,
                )
            )
    return chunks


def _point_id(chunk: Chunk) -> str:
    # Deterministic ID (includes grade) so re-ingesting the same PDF updates
    # rather than duplicates, and an 11th/12th file sharing a name can't collide.
    key = f"{chunk.grade}:{chunk.source_file}:{chunk.page}:{hashlib.sha1(chunk.text.encode()).hexdigest()}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))


def ingest_pdf(path: Path, subject: str, grade: str, chapter: str | None = None, batch_size: int | None = None) -> int:
    client = get_client()
    ensure_collection(client)
    batch_size = batch_size or config.QDRANT_BATCH_SIZE

    chunks = load_pdf(path, subject, grade, chapter)
    if not chunks:
        return 0

    total = 0
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        vectors = embed_documents([c.text for c in batch])
        points = [
            qmodels.PointStruct(
                id=_point_id(c),
                vector=vec,
                payload={
                    "text": c.text,
                    "subject": c.subject,
                    "grade": c.grade,
                    "source_file": c.source_file,
                    "chapter": c.chapter,
                    "page": c.page,
                    "images": c.images,
                    "models": c.models,
                },
            )
            for c, vec in zip(batch, vectors)
        ]
        client.upsert(collection_name=config.QDRANT_COLLECTION, points=points)
        total += len(points)
    return total