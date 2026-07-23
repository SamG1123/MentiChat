# Doubt Desk — an NCERT RAG tutor

A rebuild of the original single-prompt Gemini chatbot into a retrieval-augmented
tutor: it answers Maths/Physics/Chemistry questions grounded in your actual NCERT
textbook PDFs, with inline citations back to the exact chapter and page, streamed
token-by-token.

## What changed from the original project

| | Before | Now |
|---|---|---|
| Knowledge source | Model's own memory only | Retrieved NCERT PDF chunks (RAG) |
| API key | Hardcoded in `app.py` | `.env` file, never committed |
| Chat history | One global session for every visitor | Per-browser session |
| Response delivery | Full response after a long wait | Streamed live (SSE) |
| Citations | None | `[1] [2]` chips linking to chapter + page |
| Repo hygiene | A full `venv/` folder was committed | `.gitignore`d, `requirements.txt` instead |

## Architecture

```
PDF ──ingest_cli.py──▶ chunk (per-page, paragraph-aware) ──▶ Gemini embeddings
                                                                     │
                                                                     ▼
                                                              Qdrant collection
                                                                     ▲
                                                                     │
Browser ──/api/chat──▶ Flask ──embed question──▶ Qdrant search (top-k, subject filter)
                          │                                         │
                          └──────── retrieved chunks ◀───────────────┘
                          │
                          ▼
                 Gemini (system prompt + short rolling history + retrieved context)
                          │
                          ▼
                 SSE stream ──▶ browser (tokens, then source citations)
```

- **Embeddings & generation**: Gemini (`text-embedding-004` for vectors, `gemini-1.5-flash`
  for chat by default) — one API key, no second provider to manage.
- **Vector store**: Qdrant. Same client code works against a local Docker container,
  a persistent local `.qdrant/` directory, or a free Qdrant Cloud cluster in
  production — you're not locked into a specific host.
- **Retrieval**: cosine similarity, optional metadata filter by subject, results
  below `MIN_SCORE` are dropped so the model is told plainly "nothing relevant was
  found" instead of stretching a bad match into an answer.
- **Sessions**: a signed cookie identifies the browser session; a short rolling
  history (last 8 turns) is kept in memory to bound prompt size. This is
  process-local — fine for a single `flask run` / single Gunicorn worker demo.
  For a real multi-worker deployment, swap the `HISTORY` dict in `app.py` for
  Redis (a few lines: `get`/`setex` instead of dict access).

## Setup

### 1. Install dependencies

```bash
python -m venv venv
source venv/bin/activate        # venv\Scripts\activate on Windows
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
```

Fill in `.env`:
- `GEMINI_API_KEY` — from https://aistudio.google.com/app/apikey
- `QDRANT_URL` / `QDRANT_API_KEY` — either:
  - **Local Docker**: `docker run -p 6333:6333 qdrant/qdrant`, then `QDRANT_URL=http://localhost:6333`, leave the API key blank.
  - **Local persistent fallback**: leave `QDRANT_URL` unset or let it fail over from `localhost`, and the app will use `.qdrant/` in the project root.
  - **Cloud**: create a free cluster at https://cloud.qdrant.io, paste its URL and API key.

### 3. Ingest your NCERT PDFs

Put PDFs in `data/pdfs/` (or anywhere), then:

```bash
python scripts/ingest_cli.py --subject Mathematics data/pdfs/maths_ch7_integrals.pdf
python scripts/ingest_cli.py --subject Physics --chapter "Ch 4: Motion in a Plane" data/pdfs/physics_ch4.pdf
python scripts/ingest_cli.py --subject Chemistry data/pdfs/*.pdf
```

Re-running on the same file is safe — chunk IDs are deterministic (hashed from
file name + page + text), so it updates rather than duplicates.

### 4. Run

```bash
python app.py
```

Visit `http://localhost:5000`.

For production: `gunicorn -w 1 -k gthread -b 0.0.0.0:8000 app:app` (keep worker
count at 1 unless you've moved `HISTORY` to Redis — see above).

## Adding class 12 later

You don't need to recreate the Qdrant collection or touch anything already
ingested. `grade` is just a payload field on each point, not part of the
vector schema, so:

```bash
python scripts/ingest_cli.py --grade 12 --subject Mathematics data/pdfs/maths12_ch1.pdf
```

Then add `12` to `GRADES` in `.env` so it shows up as a tab in the UI. That's
the whole change. A few details worth knowing:

- Point IDs are hashed from `grade + filename + page + text`, so class 11 and
  class 12 PDFs that happen to share a filename (e.g. both called `ch1.pdf`)
  won't collide or overwrite each other.
- The `grade` payload index is (re)created every time `ensure_collection()`
  runs (harmless no-op if it already exists), so you never have to run a
  manual migration step.
- Chunks ingested *before* this feature existed won't have a `grade` field.
  They'll still show up when the UI filter is set to "All", just not under a
  specific class filter. If you want them properly filterable, re-run
  `ingest_cli.py --grade 11` over the original class 11 PDFs — the
  deterministic point IDs mean this updates the existing points in place
  rather than duplicating them.

## Tuning retrieval

In `.env` / `config.py`:
- `TOP_K` — how many chunks to retrieve per question (default 5).
- `CHUNK_SIZE_CHARS` / `CHUNK_OVERLAP_CHARS` — ingestion chunk size (default 1200/200).
  Larger chunks keep more context together but retrieve less precisely.
- `MIN_SCORE` — similarity floor below which a chunk is discarded (default 0.5).
  Lower it if genuinely relevant chunks are being filtered out; raise it if the
  model is citing loosely related pages.

## Project layout

```
app.py                 Flask app: routes, streaming, session/history
config.py               Env-var driven config, no secrets in code
rag/
  embeddings.py         Gemini embedding calls (with retry)
  ingest.py              PDF -> chunks -> vectors -> Qdrant
  retriever.py           question -> vector search -> scored chunks
scripts/ingest_cli.py    Command-line PDF ingestion
templates/index.html     Chat UI shell
static/style.css         Design system
static/chat.js           SSE streaming, markdown/KaTeX rendering, citations
```

## Known limitations / next steps

- Session history is in-memory (see note above on Redis for multi-worker prod).
- No auth — anyone with the URL can chat and burn API quota. Add a login or an
  API-key gate before deploying publicly.
- `extract_text()` on scanned/image-only NCERT PDFs will return empty text; run
  those through OCR first (e.g. `ocrmypdf`) before ingesting.
- The 15-word/one-quote-per-source copyright care that applies to Claude's own
  answers doesn't apply here — this app is quoting *your own* textbook content
  back to you for study purposes, which is a different situation. Still, don't
  redistribute the ingested PDFs themselves.
