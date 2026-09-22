import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List

class Settings(BaseSettings):
    # Database - defaults to SQLite for zero-setup local development
    DATABASE_URL: str = "sqlite+aiosqlite:///./storage/agent.db"
    
    # Redis - optional, set to empty string to use in-process mode
    REDIS_URL: str = ""
    
    # Qdrant - set to ":memory:" for in-process mode (no Docker needed)
    QDRANT_URL: str = ":memory:"
    QDRANT_COLLECTION: str = "agent_learnings"
    QDRANT_API_KEY: str = ""
    
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    PRIMARY_MODEL: str = "qwen3:4b"
    FAST_MODEL: str = "qwen3:4b"
    SYNTHESIS_MODEL: str = "qwen3:4b"
    DEFAULT_TEMPERATURE: float = 0.7
    
    # Cloud LLM Support (Groq, OpenAI, Gemini, OpenRouter)
    LLM_PROVIDER: str = "ollama"  # "ollama" | "groq" | "openai" | "gemini" | "openrouter"
    CLOUD_API_KEY: str = ""
    CLOUD_BASE_URL: str = ""
    CLOUD_MODEL: str = ""
    GROQ_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    OPENROUTER_API_KEY: str = ""
    
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    EMBEDDING_DIMENSION: int = 384
    
    SECRET_KEY: str = "change-me-to-a-random-secret-key-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_MINUTES: int = 1440
    
    DEFAULT_MAX_ITERATIONS: int = 100
    DEFAULT_SNAPSHOT_INTERVAL: int = 50
    DEFAULT_SYNTHESIS_INTERVAL: int = 100
    DEFAULT_TOP_K: int = 5
    DEFAULT_MIN_SIMILARITY: float = 0.65
    DEFAULT_USE_PERSISTENT_LEARNING: bool = False
    
    STORAGE_DIR: str = "./storage"
    
    TOOL_PERMISSION_PYTHON: str = "LIMITED"
    TOOL_PERMISSION_SHELL: str = "READ_ONLY"
    TOOL_PERMISSION_HTTP: str = "LIMITED"
    TOOL_PERMISSION_FILE: str = "READ_ONLY"
    
    SANDBOX_TIMEOUT_SECONDS: int = 30
    SANDBOX_MAX_MEMORY_MB: int = 512
    
    BACKEND_HOST: str = "0.0.0.0"
    BACKEND_PORT: int = 8000
    FRONTEND_URL: str = "http://localhost:5173"
    CORS_ORIGINS: List[str] = ["http://localhost:5173", "http://localhost:3000"]
    
    @property
    def use_redis(self) -> bool:
        """Check if Redis is configured."""
        return bool(self.REDIS_URL)
    
    @property
    def use_qdrant_server(self) -> bool:
        """Check if using a remote Qdrant server (vs in-memory or local disk path)."""
        return self.QDRANT_URL.startswith("http://") or self.QDRANT_URL.startswith("https://")
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
