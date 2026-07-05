"""A lightweight per-course numpy vector store.

At a few hundred chunks/course, brute-force cosine similarity over an
L2-normalized matrix (one matrix-vector product) is instant and needs no extra
dependency — so we skip FAISS. The store persists three files under
``curriculum/<course>/rag_index/``:

- ``vectors.npy``  — float32 ``(N, D)``, L2-normalized (cosine == dot product)
- ``chunks.jsonl`` — one chunk per line, aligned to vector rows
- ``manifest.json``— embedding model, dims, counts, source toggle/hashes, time

The class is deliberately small and swappable; ``pgvector`` on the production
Postgres remains the eventual store (see PLANNING Phase 11).
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import numpy as np

from rag.chunking import Chunk

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CURRICULUM_ROOT = _REPO_ROOT / "curriculum"
INDEX_DIRNAME = "rag_index"


def index_dir(course: str, curriculum_root: Path | str | None = None) -> Path:
    """Return the RAG index folder path (``curriculum/<course>/rag_index/``)."""
    root = Path(curriculum_root) if curriculum_root is not None else _DEFAULT_CURRICULUM_ROOT
    return root / course / INDEX_DIRNAME


def _normalize(matrix: np.ndarray) -> np.ndarray:
    """Return *matrix* with each row L2-normalized (zero rows left unchanged) as float32."""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (matrix / norms).astype("float32")


class NumpyVectorStore:
    """In-memory cosine store backed by on-disk numpy + jsonl artifacts."""

    def __init__(self, chunks: list[Chunk], vectors: np.ndarray):
        """Store *chunks* alongside their row-aligned, already-L2-normalized *vectors*."""
        self.chunks = chunks
        self.vectors = vectors  # assumed L2-normalized

    @classmethod
    def build(cls, chunks: list[Chunk], vectors: np.ndarray) -> "NumpyVectorStore":
        """Build a store from *chunks* and raw *vectors*, L2-normalizing the vectors."""
        return cls(chunks, _normalize(np.asarray(vectors, dtype="float32")))

    def search(self, query_vec: np.ndarray, k: int) -> list[tuple[Chunk, float]]:
        """Return the top-k ``(chunk, similarity)`` pairs, best first."""
        if not self.chunks:
            return []
        q = _normalize(np.asarray(query_vec, dtype="float32").reshape(1, -1))[0]
        sims = self.vectors @ q
        k = min(k, len(sims))
        # argpartition for top-k, then sort just those by descending similarity.
        top = np.argpartition(-sims, k - 1)[:k]
        top = top[np.argsort(-sims[top])]
        return [(self.chunks[i], float(sims[i])) for i in top]

    def save(self, course: str, manifest: dict, curriculum_root: Path | str | None = None) -> Path:
        """Write vectors, chunks, and *manifest* to the course index dir, returning it."""
        out = index_dir(course, curriculum_root)
        out.mkdir(parents=True, exist_ok=True)
        np.save(out / "vectors.npy", self.vectors)
        with open(out / "chunks.jsonl", "w", encoding="utf-8") as f:
            for chunk in self.chunks:
                f.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")
        with open(out / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        return out

    @classmethod
    def load(
        cls, course: str, curriculum_root: Path | str | None = None
    ) -> "NumpyVectorStore | None":
        """Load the store for *course* from disk, or return None if no index exists."""
        directory = index_dir(course, curriculum_root)
        vectors_path = directory / "vectors.npy"
        chunks_path = directory / "chunks.jsonl"
        if not (vectors_path.exists() and chunks_path.exists()):
            return None
        vectors = np.load(vectors_path)
        chunks: list[Chunk] = []
        with open(chunks_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    chunks.append(Chunk(**json.loads(line)))
        return cls(chunks, vectors)
