"""Ingest NCERT PDFs into the vector store.

Usage:
    python scripts/ingest_cli.py --grade 11 --subject Mathematics data/pdfs/math_chapter6_integration.pdf
    python scripts/ingest_cli.py --grade 11 --subject Physics --chapter "Ch 4: Motion in a Plane" data/pdfs/phy_ch4.pdf
    python scripts/ingest_cli.py --grade 12 --subject Chemistry data/pdfs/*.pdf   # shell-expanded glob works too

Adding a new grade later (e.g. class 12) does NOT require recreating the Qdrant
collection or re-ingesting anything already loaded — just run this script again
with --grade 12 against the new PDFs. The collection's vector config is shared
across all grades/subjects; grade is just a payload field used to filter results.

Run from the project root (so `config` and `rag` are importable).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag.ingest import ingest_pdf  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Ingest NCERT PDF(s) into Qdrant")
    parser.add_argument("files", nargs="+", help="Path(s) to PDF file(s)")
    parser.add_argument("--grade", required=True, help="e.g. 11, 12")
    parser.add_argument("--subject", required=True, help="e.g. Mathematics, Physics, Chemistry")
    parser.add_argument("--chapter", default=None, help="Optional chapter label; defaults to filename")
    args = parser.parse_args()

    for f in args.files:
        path = Path(f)
        if not path.exists():
            print(f"  skip (not found): {path}")
            continue
        print(f"Ingesting {path.name} [grade {args.grade} · {args.subject}] ...")
        n = ingest_pdf(path, subject=args.subject, grade=args.grade, chapter=args.chapter)
        print(f"  -> {n} chunks upserted")


if __name__ == "__main__":
    main()
