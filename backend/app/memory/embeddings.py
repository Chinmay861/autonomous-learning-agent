import asyncio
import logging
from typing import Any, List

import httpx

logger = logging.getLogger(__name__)

HF_INFERENCE_URL = "https://router.huggingface.co/hf-inference/models/{model}/pipeline/feature-extraction"
HF_MAX_RETRIES = 4


class EmbeddingService:
    """Text embeddings via a local sentence-transformer or HF Inference.

    Provider is chosen by EMBEDDING_PROVIDER ("local" | "hf"). The "hf" option
    calls Hugging Face Inference Providers (same all-MiniLM-L6-v2 weights,
    384 dims) so hosts without room for PyTorch stay lean. It needs HF_TOKEN.
    """

    def __init__(self, model_name: str | None = None, provider: str | None = None, api_key: str | None = None):
        # Imported lazily so importing this module never requires settings.
        from app.config import settings

        self.model_name = model_name or settings.EMBEDDING_MODEL
        self.provider = (provider or settings.EMBEDDING_PROVIDER or "local").lower()
        self.api_key = api_key if api_key is not None else settings.HF_TOKEN
        self._model: Any = None

    @property
    def model(self):
        if self._model is None:
            # Lazy load the model
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(self.model_name)
            except ImportError:
                raise ImportError("Please install sentence-transformers: pip install sentence-transformers")
        return self._model

    @property
    def dimension(self) -> int:
        if 'MiniLM' in self.model_name:
            return 384
        return self.model.get_sentence_embedding_dimension()

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        embeddings = self.model.encode(texts, normalize_embeddings=True)
        return embeddings.tolist()

    async def embed(self, text: str) -> list[float]:
        results = await self.embed_batch([text])
        return results[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self.provider == "hf":
            return await self._embed_hf(texts)

        # Use asyncio.to_thread to avoid blocking the event loop
        embeddings = await asyncio.to_thread(self._embed_sync, texts)
        return embeddings

    async def _embed_hf(self, texts: List[str]) -> List[List[float]]:
        if not self.api_key:
            raise RuntimeError(
                "EMBEDDING_PROVIDER=hf requires HF_TOKEN (a free Hugging Face token "
                "with Inference Providers access)."
            )
        url = HF_INFERENCE_URL.format(model=self.model_name)
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        last_error: Exception | None = None
        async with httpx.AsyncClient(timeout=60.0) as client:
            for attempt in range(HF_MAX_RETRIES):
                try:
                    response = await client.post(
                        url,
                        headers=headers,
                        json={"inputs": texts, "options": {"wait_for_model": True}},
                    )
                    if response.status_code in (429, 503):
                        wait = 2.0 * (attempt + 1)
                        try:
                            wait = min(float(response.json().get("estimated_time", wait)), 20.0)
                        except Exception:
                            pass
                        logger.warning(f"HF Inference busy ({response.status_code}); retrying in {wait:.1f}s")
                        await asyncio.sleep(wait)
                        continue
                    response.raise_for_status()
                    data = response.json()
                    return self._normalize_hf_response(data, len(texts))
                except httpx.HTTPError as exc:
                    last_error = exc
                    await asyncio.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"HF Inference embedding failed after {HF_MAX_RETRIES} attempts: {last_error}")

    @staticmethod
    def _normalize_hf_response(data: Any, expected: int) -> List[List[float]]:
        """Normalize feature-extraction output to a list of vectors.

        A single input yields one vector; a batch yields one vector per input.
        """
        if not isinstance(data, list):
            raise RuntimeError(f"Unexpected HF embedding response: {str(data)[:120]}")
        if data and isinstance(data[0], (int, float)):
            vectors = [data]
        else:
            vectors = data
        if len(vectors) != expected:
            raise RuntimeError(
                f"HF embedding count mismatch: got {len(vectors)} vectors for {expected} inputs"
            )
        return [[float(x) for x in vector] for vector in vectors]
