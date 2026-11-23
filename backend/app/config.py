from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- Database: SQLite by default, Postgres URLs (Render/Heroku/Neon) accepted as-is.
    DATABASE_URL: str = "sqlite+aiosqlite:///./storage/agent.db"

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _normalize_database_url(cls, value):
        """Convert libpq-style Postgres URLs to SQLAlchemy's asyncpg driver."""
        if not isinstance(value, str):
            return value
        if value.startswith("postgres://"):
            value = "postgresql+asyncpg://" + value[len("postgres://"):]
        elif value.startswith("postgresql://"):
            value = "postgresql+asyncpg://" + value[len("postgresql://"):]
        if value.startswith("postgresql+asyncpg://") and "sslmode=" in value:
            value = value.replace("sslmode=require", "ssl=require").replace("sslmode=prefer", "ssl=prefer")
        return value

    # --- LLM
    # Provider used when a model string has no "<provider>:" prefix.
    LLM_PROVIDER: str = "ollama"  # ollama | groq | openai | gemini | openrouter | custom
    PRIMARY_MODEL: str = "qwen3:4b"
    CLOUD_MODEL: str = ""  # legacy alias: used as the default model when set
    DEFAULT_TEMPERATURE: float = 0.3
    LLM_MAX_TOKENS: int = 2048
    LLM_TIMEOUT_SECONDS: float = 90.0
    # Optional reasoning effort for reasoning models (e.g. "low" for gpt-oss). Empty = provider default.
    LLM_REASONING_EFFORT: str = ""

    OLLAMA_BASE_URL: str = "http://localhost:11434"
    CLOUD_API_KEY: str = ""
    CLOUD_BASE_URL: str = ""
    GROQ_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    OPENROUTER_API_KEY: str = ""

    # --- Auth
    SECRET_KEY: str = "change-me-to-a-random-secret-key-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_MINUTES: int = 1440

    # --- Agents
    # Experiments use the code-only learning agents (no LLM). The LLM agents are kept in the
    # codebase but disabled; set ENABLE_LLM_AGENTS=true to allow agent_type="llm" again.
    ENABLE_LLM_AGENTS: bool = False
    # Pause between move rounds in "watch" speed, so a person can follow the boards.
    WATCH_MOVE_DELAY_MS: int = 350
    # After a restart, continue code-only experiments that were running (instead of waiting for Continue).
    AUTO_RESUME_INTERRUPTED: bool = True
    # While an experiment runs, request this URL every KEEP_ALIVE_SECONDS so free hosting does not put the
    # service to sleep mid-run. Empty = use RENDER_EXTERNAL_URL (set by Render automatically); unset locally.
    KEEP_ALIVE_URL: str = ""
    KEEP_ALIVE_SECONDS: int = 300

    # --- Experiment defaults and limits
    DEFAULT_NUM_GAMES: int = 500
    MAX_NUM_GAMES: int = 5000
    # How many playbook lessons the memory agent sees in each move prompt.
    PLAYBOOK_PROMPT_LIMIT: int = 12
    # Active lessons kept per user; the weakest are retired beyond this.
    PLAYBOOK_MAX_ACTIVE: int = 40
    # Optional pause between moves (seconds) to stay under provider rate limits.
    MOVE_DELAY_SECONDS: float = 0.0
    # Consecutive LLM failures before an agent's run is aborted.
    MAX_CONSECUTIVE_LLM_ERRORS: int = 5
    # Moves the agent may play from one LLM call when it is certain of them (1 = one call per move).
    MAX_MOVES_PER_TURN: int = 8

    # --- Server
    # Comma-separated list of allowed browser origins, or "*".
    CORS_ORIGINS: str = "*"

    @property
    def default_model(self) -> str:
        return self.CLOUD_MODEL or self.PRIMARY_MODEL

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()] or ["*"]

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
