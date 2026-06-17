"""Text embeddings for the text tower (blueprint §5.2).

Runnable default: TF-IDF -> Truncated SVD (LSA) dense embeddings, fit on the filing-section
corpus. This is dependency-light and CPU-only. The production upgrade is a FinBERT / financial
LLM embedding model (noted; swap `TextEmbedder` without changing the tower interface).

Persists the fitted vectorizer+SVD and a vector store (id -> dense vector) under data/vectors/.
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import Optional

import numpy as np

from ..config import DATA_DIR
from .text import LM_LITIGIOUS, LM_NEGATIVE, LM_UNCERTAINTY, _tokens, fog_index, hedging_score, lm_density

VEC_DIR = DATA_DIR / "vectors"
VEC_DIR.mkdir(parents=True, exist_ok=True)


class TextEmbedder:
    def __init__(self, dim: int = 64):
        self.dim = dim
        self.vectorizer = None
        self.svd = None

    def fit(self, texts: list[str]) -> "TextEmbedder":
        from sklearn.decomposition import TruncatedSVD
        from sklearn.feature_extraction.text import TfidfVectorizer
        self.vectorizer = TfidfVectorizer(max_features=8000, stop_words="english",
                                          ngram_range=(1, 2), min_df=2)
        X = self.vectorizer.fit_transform(texts)
        k = min(self.dim, max(2, min(X.shape) - 1))
        self.svd = TruncatedSVD(n_components=k, random_state=0)
        self.svd.fit(X)
        return self

    def transform(self, texts: list[str]) -> np.ndarray:
        X = self.vectorizer.transform(texts)
        return self.svd.transform(X)

    def save(self, name: str = "filing_lsa") -> None:
        with open(VEC_DIR / f"{name}.pkl", "wb") as f:
            pickle.dump({"dim": self.dim, "vectorizer": self.vectorizer, "svd": self.svd}, f)

    @classmethod
    def load(cls, name: str = "filing_lsa") -> Optional["TextEmbedder"]:
        p = VEC_DIR / f"{name}.pkl"
        if not p.exists():
            return None
        with open(p, "rb") as f:
            d = pickle.load(f)
        e = cls(dim=d["dim"])
        e.vectorizer, e.svd = d["vectorizer"], d["svd"]
        return e


def lexical_features(text: str) -> dict:
    """Interpretable LM + readability features (used alongside embeddings in the text tower)."""
    toks = _tokens(text)
    return {
        "lm_negativity": lm_density(toks, LM_NEGATIVE),
        "lm_uncertainty": lm_density(toks, LM_UNCERTAINTY),
        "lm_litigious": lm_density(toks, LM_LITIGIOUS),
        "fog_index": fog_index(text) or 0.0,
        "hedging_score": hedging_score(text),
        "doc_len": float(len(toks)),
    }
