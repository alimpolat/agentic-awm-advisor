"""build_index.py — AWM corpus index builder.

Orchestrates end-to-end ingestion for the Agentic AWM Advisor:
  1. Scans data/corpus/ for .html and .pdf files.
  2. Parses HTML (BeautifulSoup) and PDF (pypdf, first MAX_PDF_PAGES pages).
  3. Chunks each document with the sentence-aware chunker.
  4. Augments each chunk with Contextual Retrieval (Gemini 2.5 Flash, cached).
  5. Embeds augmented texts (RETRIEVAL_DOCUMENT task type, batched at 32).
  6. Upserts original chunks + augmented vectors into Qdrant on-disk (./qdrant_data).
  7. Builds and saves BM25 index over augmented text (./bm25.json).
  8. Runs a sanity query and gates on Bergström portfolio appearing in top-3.

Design decisions (from task spec):
  - MAX_PDF_PAGES = 12     : caps macro PDF extraction to keep chunks < 500.
  - DOC_CONTEXT_CHARS = 6000 : truncates doc context sent to Flash per chunk.
  - Embed augmented text, store original chunk text in Qdrant payload.
  - Build BM25 over augmented text (parallel Chunk objects with text=augmented).
  - Sequential contextualise per doc (avoids cache write race); batched embeds.
  - Sanity query uses a fresh HybridRetriever (avoids module-global stale cache).
"""

from __future__ import annotations

import io
import re
import sys
import time
from pathlib import Path

# Reconfigure stdout/stderr to UTF-8 on Windows (avoids cp1252 UnicodeEncodeError)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Ensure repo root is on sys.path so `app` is importable when running as a script
_REPO_ROOT_EARLY = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT_EARLY) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT_EARLY))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_PDF_PAGES = 12        # Extract at most this many pages from each PDF
DOC_CONTEXT_CHARS = 6000  # Chars of doc text sent to Flash for context
EMBED_BATCH = 32          # Max texts per embed() call

# Repo root (scripts/ lives one level below)
REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = REPO_ROOT / "data" / "corpus"
QDRANT_PATH = str(REPO_ROOT / "qdrant_data")
BM25_PATH = str(REPO_ROOT / "bm25.json")

# ---------------------------------------------------------------------------
# Doc-level metadata map (filename stem → metadata dict)
# ---------------------------------------------------------------------------

_META: dict[str, dict] = {
    "bergstrom_portfolio_q1_2026": {
        "doc_type": "portfolio",
        "asset_class": "multi_asset",
        "client_id": "bergstrom",
        "as_of_date": "2026-03-31",
        "source_uri": "data/corpus/bergstrom_portfolio_q1_2026.html",
    },
    "bergstrom_ips": {
        "doc_type": "ips",
        "asset_class": "n/a",
        "client_id": "bergstrom",
        "as_of_date": "2026-01-01",
        "source_uri": "data/corpus/bergstrom_ips.html",
    },
    "bergstrom_meeting_notes_2026-01-14": {
        "doc_type": "meeting_notes",
        "asset_class": "n/a",
        "client_id": "bergstrom",
        "as_of_date": "2026-01-14",
        "source_uri": "data/corpus/bergstrom_meeting_notes_2026-01-14.html",
    },
    "bergstrom_meeting_notes_2026-02-18": {
        "doc_type": "meeting_notes",
        "asset_class": "n/a",
        "client_id": "bergstrom",
        "as_of_date": "2026-02-18",
        "source_uri": "data/corpus/bergstrom_meeting_notes_2026-02-18.html",
    },
    "bergstrom_meeting_notes_2026-04-14": {
        "doc_type": "meeting_notes",
        "asset_class": "n/a",
        "client_id": "bergstrom",
        "as_of_date": "2026-04-14",
        "source_uri": "data/corpus/bergstrom_meeting_notes_2026-04-14.html",
    },
    "bis_quarterly_2025_q4": {
        "doc_type": "macro",
        "asset_class": "macro",
        "client_id": None,
        "as_of_date": "2025-12-31",
        "source_uri": "data/corpus/bis_quarterly_2025_q4.pdf",
    },
    "bis_quarterly_2026_q1": {
        "doc_type": "macro",
        "asset_class": "macro",
        "client_id": None,
        "as_of_date": "2026-03-31",
        "source_uri": "data/corpus/bis_quarterly_2026_q1.pdf",
    },
    "ecb_economic_bulletin_2026": {
        "doc_type": "macro",
        "asset_class": "macro",
        "client_id": None,
        "as_of_date": "2026-04-01",
        "source_uri": "data/corpus/ecb_economic_bulletin_2026.pdf",
    },
    "imf_weo_2026_04": {
        "doc_type": "macro",
        "asset_class": "macro",
        "client_id": None,
        "as_of_date": "2026-04-01",
        "source_uri": "data/corpus/imf_weo_2026_04.pdf",
    },
}


def _metadata_for(stem: str, filepath: Path) -> dict:
    """Return metadata dict for the given doc stem, with sensible defaults."""
    if stem in _META:
        return _META[stem]
    # Warn about unmapped stems before applying the generic fallback
    print(f"  WARNING: stem '{stem}' not in _META map — applying generic fallback metadata")
    suffix = filepath.suffix.lower()
    return {
        "doc_type": "macro",
        "asset_class": "macro",
        "client_id": None,
        "as_of_date": None,
        "source_uri": str(filepath.relative_to(REPO_ROOT)),
    }


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_html(path: Path) -> str:
    """Extract clean text from an HTML file using BeautifulSoup."""
    from bs4 import BeautifulSoup
    raw = path.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(raw, "html.parser")
    text = soup.get_text(separator=" ")
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_pdf_pages(path: Path) -> list[tuple[int, str]]:
    """Extract text from the first MAX_PDF_PAGES pages of a PDF.

    Returns list of (page_number, page_text) tuples (1-indexed page numbers).
    Pages with empty/whitespace-only text are skipped.
    """
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    pages = []
    for i, page in enumerate(reader.pages[:MAX_PDF_PAGES]):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            pages.append((i + 1, text))  # 1-indexed
    return pages


# ---------------------------------------------------------------------------
# Main build function
# ---------------------------------------------------------------------------

def build_index() -> int:
    """Run the full corpus ingestion pipeline."""
    from app.retrieval.chunker import Chunk, chunk_document
    from app.retrieval.contextual import contextualize
    from app.retrieval.embedder import embed
    from app.retrieval.qdrant_store import Store, point_from_chunk
    from app.retrieval.bm25 import BM25Index

    t_start = time.perf_counter()

    # Discover corpus files — skip SOURCES.html and non-html/pdf
    all_files = sorted(CORPUS_DIR.iterdir())
    corpus_files = [
        f for f in all_files
        if f.suffix.lower() in (".html", ".pdf") and f.stem != "SOURCES"
    ]
    print(f"Found {len(corpus_files)} corpus files in {CORPUS_DIR}")

    # Initialise Qdrant store (fresh collection)
    print(f"\nInitialising Qdrant store at {QDRANT_PATH} ...")
    store = Store(path=QDRANT_PATH)
    store.create()

    # Collect all (original chunk, augmented text) pairs for embedding+upsert
    all_original_chunks: list[Chunk] = []   # stored in Qdrant payload
    all_augmented_texts: list[str] = []      # embedded for the dense vector
    all_augmented_chunks: list[Chunk] = []   # for BM25 (text=augmented)

    global_idx = 0  # running Qdrant point ID

    for filepath in corpus_files:
        stem = filepath.stem
        meta = _metadata_for(stem, filepath)
        suffix = filepath.suffix.lower()

        print(f"\n-- {stem}{suffix} (doc_type={meta.get('doc_type')}) --")

        doc_original_chunks: list[Chunk] = []
        doc_augmented_texts: list[str] = []

        if suffix == ".html":
            # --- HTML: parse full text, chunk once ---
            full_text = _parse_html(filepath)
            doc_text_ctx = full_text[:DOC_CONTEXT_CHARS]
            chunks = chunk_document(full_text, stem, metadata=meta)
            print(f"  Parsed HTML: {len(full_text)} chars -> {len(chunks)} chunks")

            for chunk in chunks:
                augmented = contextualize(chunk, doc_text_ctx)
                doc_original_chunks.append(chunk)
                doc_augmented_texts.append(augmented)

        elif suffix == ".pdf":
            # --- PDF: extract page by page (capped at MAX_PDF_PAGES) ---
            pages = _parse_pdf_pages(filepath)
            print(f"  Parsed PDF: {len(pages)} non-empty pages (cap={MAX_PDF_PAGES})")

            # Build a doc-level context from the first page text (or all pages concat)
            all_page_texts = " ".join(pt for _, pt in pages)
            doc_text_ctx = all_page_texts[:DOC_CONTEXT_CHARS]

            for page_num, page_text in pages:
                page_chunks = chunk_document(page_text, stem, page=page_num, metadata=meta)
                for c in page_chunks:
                    local = c.chunk_id.split("::")[-1]          # 4-digit per-page index
                    c.chunk_id = f"{stem}::p{page_num:03d}::{local}"  # e.g. bis_q4::p005::0000
                    augmented = contextualize(c, doc_text_ctx)
                    doc_original_chunks.append(c)
                    doc_augmented_texts.append(augmented)

        doc_chunk_count = len(doc_original_chunks)
        print(f"  Chunks: {doc_chunk_count} | Contextualising done (cached after first run)")

        # Batch embed all augmented texts for this doc
        if not doc_augmented_texts:
            continue

        doc_vectors: list[list[float]] = []
        for batch_start in range(0, len(doc_augmented_texts), EMBED_BATCH):
            batch = doc_augmented_texts[batch_start : batch_start + EMBED_BATCH]
            vecs = embed(batch, "RETRIEVAL_DOCUMENT")
            doc_vectors.extend(vecs)
        print(f"  Embedded {len(doc_vectors)} vectors")

        # Upsert: original chunk stored in payload, augmented vector as dense index
        points = []
        for orig_chunk, vec in zip(doc_original_chunks, doc_vectors):
            pt = point_from_chunk(global_idx, orig_chunk, vec)
            points.append(pt)
            global_idx += 1

        store.upsert(points)

        # Accumulate for BM25 (augmented text chunks)
        for orig_chunk, aug_text in zip(doc_original_chunks, doc_augmented_texts):
            all_augmented_chunks.append(
                Chunk(
                    doc_id=orig_chunk.doc_id,
                    chunk_id=orig_chunk.chunk_id,
                    text=aug_text,
                    page=orig_chunk.page,
                    char_start=orig_chunk.char_start,
                    char_end=orig_chunk.char_end,
                    metadata=orig_chunk.metadata,
                )
            )

        all_original_chunks.extend(doc_original_chunks)

    total_chunks = global_idx
    print(f"\n{'='*60}")
    print(f"Total chunks indexed: {total_chunks}")

    # Verify no chunk_id collisions
    all_chunk_ids = [c.chunk_id for c in all_original_chunks]
    unique_count = len(set(all_chunk_ids))
    print(f"Unique chunk_ids: {unique_count} / {total_chunks}")
    if unique_count != total_chunks:
        raise RuntimeError(
            f"CHUNK_ID COLLISION: {total_chunks - unique_count} duplicate chunk_ids detected! "
            "Fix the chunking pipeline before committing."
        )

    if total_chunks >= 500:
        raise RuntimeError(
            f"EXCEEDED 500-chunk budget: {total_chunks} chunks indexed! "
            "Reduce MAX_PDF_PAGES or corpus scope."
        )

    # Build and save BM25 index (over augmented text)
    print(f"\nBuilding BM25 index over {len(all_augmented_chunks)} augmented chunks ...")
    bm25 = BM25Index()
    bm25.build(all_augmented_chunks)
    bm25.save(BM25_PATH)
    print(f"BM25 saved to {BM25_PATH}")

    # Flush/close Qdrant so data is written to disk
    store.client.close()
    print(f"Qdrant data flushed and closed.")

    elapsed = time.perf_counter() - t_start
    print(f"\nTotal elapsed: {elapsed:.1f}s")
    if elapsed >= 600:
        raise RuntimeError(f"Exceeded 10-min budget: {elapsed:.0f}s")

    return total_chunks


# ---------------------------------------------------------------------------
# Sanity check
# ---------------------------------------------------------------------------

TARGET_DOC_ID = "bergstrom_portfolio_q1_2026"
SANITY_QUERY = "what is Bergström's Gulf exposure"


def run_sanity_check() -> bool:
    """Run the sanity query via a fresh HybridRetriever and gate on result.

    Returns True if the gate passes (portfolio doc in top-3), False otherwise.
    """
    from app.retrieval.qdrant_store import Store
    from app.retrieval.bm25 import BM25Index
    from app.retrieval.hybrid import HybridRetriever

    print(f"\n{'='*60}")
    print(f"SANITY CHECK: '{SANITY_QUERY}'")
    print(f"Gate: '{TARGET_DOC_ID}' must appear in top-3 results\n")

    store = Store(path=QDRANT_PATH)
    try:
        bm25 = BM25Index.load(BM25_PATH)
        retriever = HybridRetriever(store=store, bm25=bm25)

        results = retriever.retrieve(SANITY_QUERY, top_k=5)

        print("Top-5 results:")
        print(f"{'Rank':<5} {'doc_id':<40} {'Score':<8} {'Snippet'}")
        print("-" * 100)

        target_in_top3 = False
        for rank, chunk in enumerate(results, start=1):
            score_str = f"{chunk.metadata.get('score', 'n/a')}"
            snippet = chunk.text[:80].replace("\n", " ")
            marker = " <<< TARGET" if chunk.doc_id == TARGET_DOC_ID else ""
            print(f"{rank:<5} {chunk.doc_id:<40} {score_str:<8} {snippet}...{marker}")
            if rank <= 3 and chunk.doc_id == TARGET_DOC_ID:
                target_in_top3 = True

        print()
        if target_in_top3:
            print("PASS — Bergström portfolio in top-3 for Gulf exposure query.")
            return True
        else:
            print(f"FAIL — '{TARGET_DOC_ID}' was NOT in top-3 results.")
            return False
    finally:
        store.client.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("AWM Corpus Index Builder")
    print("=" * 60)

    # Step 1+2: Build the index
    total = build_index()

    # Step 3: Sanity check (fresh retriever, no stale module-global cache)
    passed = run_sanity_check()

    import os
    # Report artifact sizes
    qdrant_dir = Path(QDRANT_PATH)
    bm25_file = Path(BM25_PATH)
    if qdrant_dir.exists():
        qdrant_size = sum(f.stat().st_size for f in qdrant_dir.rglob("*") if f.is_file())
        print(f"\nqdrant_data/ size: {qdrant_size / 1024:.1f} KB")
    if bm25_file.exists():
        bm25_size = bm25_file.stat().st_size
        print(f"bm25.json size: {bm25_size / 1024:.1f} KB")

    if not passed:
        print("\nBuild FAILED — sanity gate not met. Do NOT commit.")
        sys.exit(1)

    print(f"\nBuild COMPLETE. {total} chunks indexed. Sanity gate PASSED.")
    sys.exit(0)
