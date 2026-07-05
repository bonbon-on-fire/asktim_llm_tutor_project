"""Build a per-course RAG index.

    python -m rag.ingest --course cities_and_climate_change --source local
    python -m rag.ingest --course mathematics_for_cs --source ocw
    python -m rag.ingest --course <c> --source both

Gathers course-level docs from the selected source(s), chunks them, embeds the
chunks, and writes ``curriculum/<course>/rag_index/`` (vectors.npy + chunks.jsonl
+ manifest.json). The exercise prompt and figures are never ingested.
"""

from __future__ import annotations

import argparse
import hashlib
from datetime import datetime, timezone

from dotenv import load_dotenv

from rag.chunking import chunk_document
from rag.embeddings import EMBEDDING_MODEL, embed_texts
from rag.sources import load_local_docs
from rag.store import NumpyVectorStore


def _gather(course: str, source: str) -> list[tuple[str, str]]:
    """Collect ``(label, text)`` docs for *course* from the selected source(s).

    *source* is one of ``"local"``, ``"ocw"``, or ``"both"``; the OCW loader is
    imported lazily since it needs requests + beautifulsoup4.
    """
    docs: list[tuple[str, str]] = []
    if source in ("local", "both"):
        docs += load_local_docs(course)
    if source in ("ocw", "both"):
        from rag.ocw import load_ocw_docs  # lazy (needs requests + beautifulsoup4)

        docs += load_ocw_docs(course)
    return docs


def ingest(course: str, source: str, *, target_chars: int, overlap_chars: int) -> int:
    """Build and persist the RAG index for *course*, returning the chunk count.

    Gathers docs from *source*, chunks them to roughly *target_chars* with
    *overlap_chars* overlap, embeds the chunks, and writes vectors, chunks, and a
    manifest to ``curriculum/<course>/rag_index/``. Returns 0 if no docs are found.
    """
    docs = _gather(course, source)
    if not docs:
        print(f"No source docs found for course={course!r} source={source!r}.")
        if source in ("ocw", "both"):
            print("  (OCW needs an online_link.txt and `pip install beautifulsoup4`.)")
        return 0

    chunks = []
    for source_label, text in docs:
        chunks += chunk_document(
            text, source_label, course, target_chars=target_chars, overlap_chars=overlap_chars
        )
    print(f"{len(docs)} docs -> {len(chunks)} chunks; embedding with {EMBEDDING_MODEL} ...")

    vectors = embed_texts([c.text for c in chunks])
    store = NumpyVectorStore.build(chunks, vectors)
    manifest = {
        "course": course,
        "source": source,
        "embedding_model": EMBEDDING_MODEL,
        "dim": int(vectors.shape[1]),
        "chunk_count": len(chunks),
        "doc_count": len(docs),
        "target_chars": target_chars,
        "overlap_chars": overlap_chars,
        "source_hashes": {
            label: hashlib.sha256(text.encode("utf-8")).hexdigest()[:16] for label, text in docs
        },
        "built_at": datetime.now(timezone.utc).isoformat(),
    }
    out = store.save(course, manifest)
    print(f"Wrote index ({len(chunks)} chunks, dim {vectors.shape[1]}) to {out}")
    return len(chunks)


def main() -> None:
    """Parse CLI arguments, load the environment, and run :func:`ingest`."""
    parser = argparse.ArgumentParser(description="Build a per-course RAG index.")
    parser.add_argument("--course", required=True, help="curriculum/<course> folder name")
    parser.add_argument(
        "--source",
        choices=["local", "ocw", "both"],
        default="local",
        help="where to pull course material from (default: local)",
    )
    parser.add_argument("--target-chars", type=int, default=2400)
    parser.add_argument("--overlap-chars", type=int, default=300)
    args = parser.parse_args()

    load_dotenv()  # OPENAI_API_KEY from repo .env for the embedding calls
    ingest(
        args.course,
        args.source,
        target_chars=args.target_chars,
        overlap_chars=args.overlap_chars,
    )


if __name__ == "__main__":
    main()
