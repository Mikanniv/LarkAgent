from __future__ import annotations

import hashlib
import math
import re
from typing import Iterable, List

import chromadb

from core.config import CHROMA_DIR


COLLECTION_NAME = "memory"
EMBEDDING_DIM = 384


def _tokenize(text: str) -> List[str]:
    """Lightweight local tokenizer for offline memory debugging."""
    normalized = re.sub(r"\s+", " ", (text or "").strip().lower())
    if not normalized:
        return ["<empty>"]

    tokens = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", normalized)
    grams = list(tokens)
    grams.extend("".join(tokens[index : index + 2]) for index in range(max(0, len(tokens) - 1)))
    grams.extend("".join(tokens[index : index + 3]) for index in range(max(0, len(tokens) - 2)))
    return grams or [normalized]


class LocalHashEmbeddingFunction:
    """Deterministic embedding function that keeps ChromaDB usable offline.

    It is intentionally simple: good enough for wiring and debugging the memory
    system without downloading an embedding model. A stronger Chinese embedding
    model can replace this class later without changing schema.py.
    """

    def __init__(self, dim: int = EMBEDDING_DIM) -> None:
        self.dim = dim

    def name(self) -> str:
        return "local_hash_embedding"

    def __call__(self, input: Iterable[str]) -> List[List[float]]:  # ChromaDB requires this parameter name.
        return self._embed_many(input)

    def embed_query(self, input: str | Iterable[str]) -> List[float] | List[List[float]]:
        """Compatibility hook used by newer ChromaDB query paths."""
        if isinstance(input, str):
            return self._embed(input)
        return self._embed_many(input)

    def embed_documents(self, input: str | Iterable[str]) -> List[List[float]]:
        """Compatibility hook used by newer ChromaDB document paths."""
        if isinstance(input, str):
            return [self._embed(input)]
        return self._embed_many(input)

    def _embed_many(self, input: Iterable[str]) -> List[List[float]]:
        return [self._embed(text) for text in input]

    def _embed(self, text: str) -> List[float]:
        vector = [0.0] * self.dim
        for token in _tokenize(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            value = int.from_bytes(digest, "big")
            index = value % self.dim
            sign = 1.0 if ((value >> 8) & 1) else -1.0
            vector[index] += sign

        norm = math.sqrt(sum(item * item for item in vector)) or 1.0
        return [item / norm for item in vector]


CHROMA_DIR.mkdir(parents=True, exist_ok=True)
client = chromadb.PersistentClient(path=str(CHROMA_DIR))
embedding_function = LocalHashEmbeddingFunction()
collection = client.get_or_create_collection(
    name=COLLECTION_NAME,
    embedding_function=embedding_function,
    metadata={"hnsw:space": "cosine"},
)
