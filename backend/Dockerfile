FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# NOTE: no local embedding model is baked in. The app uses Hugging Face
# Inference (EMBEDDING_PROVIDER=hf + HF_TOKEN) so the image stays small and
# fits low-RAM hosts. For on-device embeddings, uncomment torch +
# sentence-transformers in requirements.txt and pre-download the model here:
# RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Copy application code
COPY . .

# Create storage directory
RUN mkdir -p /app/storage

EXPOSE 8000

# Default: run the API server (binds Render's $PORT when provided)
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
