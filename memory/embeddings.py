# memory/embeddings.py
"""
EmbeddingService — turn text into vectors via the active provider.

Design:
  * One instance per application, built at bootstrap.
  * Integrates with EmbeddingCache: identical text never hits the API
    twice.
  * Never raises: on any failure, returns None so the caller can fall
    back to keyword search.
  * Knows nothing about memory semantics; it just calls provider.embed().
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from applog.logger import get_logger
from providers.base.provider import AIProvider, ProviderError

log = get_logger("memory.embeddings")


@dataclass(frozen=True)
class EmbeddedVector:
    """A normalized embedding ready to store."""
    values: tuple[float, ...]
    provider: str
    model: str
    dim: int


class EmbeddingService:
    def __init__(
        self,
        *,
        provider_manager,
        config,
        cache=None,
        embed_model: Optional[str] = None,
    ) -> None:
        self._providers = provider_manager
        self._config = config
        self._embed_model = embed_model
        self._cache = cache

    # ------------------------------------------------------------------
    def is_available(self) -> bool:
        try:
            provider = self._providers.active()
        except Exception:
            return False
        return provider is not None

    # ------------------------------------------------------------------
    def embed_text(self, text: str) -> Optional[EmbeddedVector]:
        if not text or not text.strip():
            return None
        result = self.embed_texts((text,))
        if not result:
            return None
        return result[0]

    def embed_texts(self, texts: tuple[str, ...]) -> list[EmbeddedVector]:
        """
        Embed one or more texts. Uses the cache for hits; calls the
        provider only for misses (in a single batched request).
        """
        if not texts:
            return []

        try:
            provider = self._providers.active()
        except Exception as exc:
            log.info("embed: no active provider", extra={"error": str(exc)})
            return []

        provider_id = getattr(provider, "provider_id", None) or "unknown"
        model_name = self._embed_model or self._guess_default_model_name(provider_id)

        # ---- Split into cached and to-fetch -------------------------
        results: list[Optional[EmbeddedVector]] = [None] * len(texts)
        to_fetch_idx: list[int] = []

        for i, t in enumerate(texts):
            if self._cache is not None:
                try:
                    hit = self._cache.get(t, provider=provider_id)
                except Exception:
                    hit = None
                if hit is not None:
                    results[i] = EmbeddedVector(
                        values=hit.values,
                        provider=hit.provider,
                        model=hit.model,
                        dim=hit.dim,
                    )
                    continue
            to_fetch_idx.append(i)

        # ---- Fetch the misses in ONE batched call -------------------
        if to_fetch_idx:
            fetch_texts = tuple(texts[i] for i in to_fetch_idx)
            try:
                raw_vecs = provider.embed(fetch_texts, model=self._embed_model)
            except ProviderError as exc:
                log.info(
                    "embed: provider error",
                    extra={
                        "provider": provider_id,
                        "code": getattr(exc, "error_code", ""),
                    },
                )
                return _collect_partial(results)
            except NotImplementedError:
                log.info("embed: provider does not implement embed()")
                return _collect_partial(results)
            except Exception:
                log.exception("embed: unexpected error")
                return _collect_partial(results)

            if not raw_vecs or len(raw_vecs) != len(fetch_texts):
                log.info("embed: provider returned wrong number of vectors")
                return _collect_partial(results)

            for j, raw in enumerate(raw_vecs):
                original_idx = to_fetch_idx[j]
                arr = np.asarray(raw, dtype=np.float32)
                norm = float(np.linalg.norm(arr))
                if norm > 0:
                    arr = arr / norm
                values = tuple(float(x) for x in arr)
                ev = EmbeddedVector(
                    values=values,
                    provider=provider_id,
                    model=model_name,
                    dim=int(arr.shape[0]),
                )
                results[original_idx] = ev

                if self._cache is not None:
                    try:
                        self._cache.put(
                            texts[original_idx],
                            values=values,
                            provider=provider_id,
                            model=model_name,
                        )
                    except Exception:
                        pass

        # ---- Final list --------------------------------------------
        out: list[EmbeddedVector] = []
        for r in results:
            if r is not None:
                out.append(r)
        return out

    # ------------------------------------------------------------------
    @staticmethod
    def _guess_default_model_name(provider_id: str) -> str:
        pid = (provider_id or "").lower()
        if "gemini" in pid:
            return "gemini-embedding-001"
        if "openai" in pid:
            return "text-embedding-3-small"
        return pid or "unknown"


# ----------------------------------------------------------------------
# Vector math
# ----------------------------------------------------------------------
def to_blob(values: tuple[float, ...]) -> bytes:
    return np.asarray(values, dtype=np.float32).tobytes()


def from_blob(blob: bytes, dim: int) -> np.ndarray:
    arr = np.frombuffer(blob, dtype=np.float32)
    if dim > 0 and arr.shape[0] != dim:
        raise ValueError(f"embedding dim mismatch: {arr.shape[0]} != {dim}")
    return arr.astype(np.float32, copy=False)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    if a.shape != b.shape:
        return 0.0
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


# ----------------------------------------------------------------------
def _collect_partial(results: list[Optional[EmbeddedVector]]) -> list[EmbeddedVector]:
    """Return whatever we have (cache hits may still be valid)."""
    return [r for r in results if r is not None]