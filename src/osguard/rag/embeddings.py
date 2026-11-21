"""Lazy local Sentence Transformers adapter for LangChain and FAISS."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from langchain_core.embeddings import Embeddings


DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class LocalSentenceTransformerEmbeddings(Embeddings):
    """Generate embeddings locally; Groq is used only for language inference."""

    def __init__(self, model_name: str | None = None, *, model: Any | None = None) -> None:
        self.model_name = model_name or os.getenv("OSGUARD_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
        self._model = model

    def _get_model(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name, device="cpu")
        return self._model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._get_model().encode(
            texts,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return vectors.astype("float32", copy=False).tolist()

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


@lru_cache(maxsize=2)
def get_local_embeddings(model_name: str | None = None) -> LocalSentenceTransformerEmbeddings:
    """Reuse the local encoder across indexing and search operations."""
    return LocalSentenceTransformerEmbeddings(model_name)
