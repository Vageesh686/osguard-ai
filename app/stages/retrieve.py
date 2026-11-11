"""Stage 2: hybrid retrieval = BM25 (exact error codes / command names) + dense vectors
(meaning), fused with Reciprocal Rank Fusion, then boosted for matching category / error codes."""
from __future__ import annotations

import json
import re
from typing import Optional

from app.config import CHROMA_DIR, CHUNKS_PATH, COLLECTION, EMBED_MODEL, TOP_K
from app.schemas import Chunk, Extraction

RRF_K = 60
POOL = 25
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
TOKEN_RE = re.compile(r"0x[0-9a-f]+|[a-z0-9_\-]+")

_state: Optional[dict] = None


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def rrf_fuse(rankings: list[list[str]], k: int = RRF_K) -> dict[str, float]:
    """rankings: list of ranked id lists (best first). Returns id -> fused score."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, cid in enumerate(ranking):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
    return scores


def _load() -> dict:
    global _state
    if _state is not None:
        return _state
    if not CHUNKS_PATH.exists():
        raise FileNotFoundError(
            f"{CHUNKS_PATH} not found. Build the knowledge base first:  python -m kb.build_index"
        )
    from rank_bm25 import BM25Okapi
    import chromadb
    from sentence_transformers import SentenceTransformer

    chunks = [Chunk(**json.loads(line)) for line in CHUNKS_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    bm25 = BM25Okapi([tokenize(c.title + " " + c.text) for c in chunks])
    collection = chromadb.PersistentClient(path=str(CHROMA_DIR)).get_collection(COLLECTION)
    model = SentenceTransformer(EMBED_MODEL)
    _state = {"chunks": chunks, "by_id": {c.id: c for c in chunks}, "bm25": bm25,
              "collection": collection, "model": model}
    return _state


def build_query(user_text: str, extraction: Optional[Extraction]) -> str:
    parts = [user_text.strip()[:1000]]
    if extraction:
        parts += extraction.error_codes
        if extraction.component:
            parts.append(extraction.component)
    return " ".join(parts)


def retrieve_ranked(query: str, extraction: Optional[Extraction], k: int = TOP_K) -> list[Chunk]:
    s = _load()
    chunks: list[Chunk] = s["chunks"]

    # lexical ranking
    scores = s["bm25"].get_scores(tokenize(query))
    bm25_rank = [chunks[i].id for i in sorted(range(len(chunks)), key=lambda i: -scores[i])[:POOL] if scores[i] > 0]

    # dense ranking
    emb = s["model"].encode([BGE_QUERY_PREFIX + query], normalize_embeddings=True).tolist()
    res = s["collection"].query(query_embeddings=emb, n_results=min(POOL, len(chunks)))
    dense_rank = res["ids"][0]

    fused = rrf_fuse([bm25_rank, dense_rank])

    codes = [c.lower() for c in (extraction.error_codes if extraction else [])]
    for cid in list(fused):
        c = s["by_id"][cid]
        if extraction and c.category in (extraction.category, "general"):
            fused[cid] *= 1.25
        if codes and any(code in c.text.lower() for code in codes):
            fused[cid] += 0.05                      # exact error-code hit
    top = sorted(fused, key=fused.get, reverse=True)[:k]
    return [s["by_id"][cid] for cid in top]


def retrieve(user_text: str, extraction: Optional[Extraction] = None, k: int = TOP_K) -> list[Chunk]:
    return retrieve_ranked(build_query(user_text, extraction), extraction, k)
