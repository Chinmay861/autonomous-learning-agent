import asyncio
from typing import Any

class EmbeddingService:
    def __init__(self, model_name: str = 'all-MiniLM-L6-v2'):
        self.model_name = model_name
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
        
        # Use asyncio.to_thread to avoid blocking the event loop
        embeddings = await asyncio.to_thread(self._embed_sync, texts)
        return embeddings
