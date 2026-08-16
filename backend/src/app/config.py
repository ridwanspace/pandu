"""Application settings — 12-factor env config, validated at startup.

Every variable here is documented in the repo-root ``.env.example``.
Model identifiers follow the ``provider/model`` convention (e.g. ``openai/gpt-4o-mini``)
and are resolved by the provider factory at call time.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── App ──────────────────────────────────────────────────────────────
    app_name: str = "pandu"
    environment: str = "dev"
    log_level: str = "INFO"

    # ── Persistence ──────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://pandu:pandu@localhost:5432/pandu"
    redis_url: str = "redis://localhost:6379/0"

    # ── Auth & limits ────────────────────────────────────────────────────
    # Comma-separated list of accepted API keys (clients send X-API-Key).
    api_keys: str = ""
    # Comma-separated browser origins allowed to call the API (CORS).
    cors_origins: str = "http://localhost:3000"
    rate_limit_requests: int = 60
    rate_limit_window_seconds: int = 60
    max_upload_bytes: int = 25 * 1024 * 1024
    max_question_chars: int = 4_000

    # ── AI models (provider/model strings) ───────────────────────────────
    ai_chat_model: str = "openai/gpt-4o-mini"
    ai_fallback_model: str = ""  # empty = no fallback
    ai_embed_model: str = "openai/text-embedding-3-small"
    ai_judge_model: str = ""  # empty = reuse ai_chat_model

    # ── Provider credentials ─────────────────────────────────────────────
    openai_api_key: str = ""
    gemini_api_key: str = ""
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    # Any OpenAI-compatible endpoint (Ollama, vLLM, Groq, ...):
    openai_compatible_base_url: str = ""
    openai_compatible_api_key: str = ""
    cohere_api_key: str = ""
    jina_api_key: str = ""

    # ── Retrieval pipeline (all knobs are config; see ADR-002/ADR-010) ───
    embedding_dimensions: int = 1536
    retrieval_candidates: int = 20  # per arm (dense + lexical), pre-fusion
    retrieval_top_k: int = 5  # contexts sent to the LLM
    rrf_k: int = 60
    reranker: str = Field(default="none", pattern="^(none|cohere|jina|local)$")
    local_reranker_model: str = "BAAI/bge-reranker-v2-m3"

    # ── Ingestion ────────────────────────────────────────────────────────
    chunk_max_tokens: int = 512
    chunk_overlap_tokens: int = 64
    embed_batch_size: int = 64

    # ── Observability ────────────────────────────────────────────────────
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "http://localhost:3001"

    @property
    def api_key_list(self) -> list[str]:
        return [k.strip() for k in self.api_keys.split(",") if k.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Read settings lazily (never at import time) so tests can override env."""
    return Settings()
