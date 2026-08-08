"""
Application configuration using Pydantic Settings.
"""
import secrets
from functools import lru_cache
from typing import List, Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )
    
    # Application
    APP_NAME: str = "Nova AI"
    APP_VERSION: str = "1.0.0"
    APP_DESCRIPTION: str = "Next Generation AI Workspace"
    DEBUG: bool = False
    TESTING: bool = False
    ENVIRONMENT: str = "development"
    
    # API
    API_V1_PREFIX: str = "/api/v1"
    API_DOCS_URL: str = "/docs"
    API_REDOC_URL: str = "/redoc"
    API_OPENAPI_URL: str = "/openapi.json"
    
    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    WORKERS: int = 4
    
    # Security
    SECRET_KEY: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    ALGORITHM: str = "HS256"
    FIELD_ENCRYPTION_KEY: Optional[str] = None
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    DB_ECHO: bool = False
    PASSWORD_RESET_TOKEN_EXPIRE_HOURS: int = 1
    EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS: int = 24
    
    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:3001"]
    CORS_ALLOW_CREDENTIALS: bool = True
    CORS_ALLOW_METHODS: List[str] = ["*"]
    CORS_ALLOW_HEADERS: List[str] = ["*"]
    
    # CSRF
    CSRF_SECRET: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    CSRF_COOKIE_NAME: str = "csrf_token"
    CSRF_HEADER_NAME: str = "X-CSRF-Token"
    
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/nova_ai"
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 3600
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_MAX_CONNECTIONS: int = 50
    REDIS_SOCKET_TIMEOUT: int = 5
    REDIS_SOCKET_CONNECT_TIMEOUT: int = 5
    
    # Qdrant Vector Database
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: Optional[str] = None
    QDRANT_COLLECTION_PREFIX: str = "nova_ai"
    # Fall back to a Postgres-backed vector store when Qdrant is unreachable
    QDRANT_AUTO_FALLBACK: bool = True
    
    # Storage (S3/MinIO)
    STORAGE_ENDPOINT: str = "http://localhost:9000"
    STORAGE_ACCESS_KEY: str = "minioadmin"
    STORAGE_SECRET_KEY: str = "minioadmin"
    STORAGE_BUCKET: str = "nova-ai"
    STORAGE_REGION: str = "us-east-1"
    STORAGE_SECURE: bool = False
    STORAGE_PUBLIC_URL: Optional[str] = None
    # Fall back to local disk when MinIO/S3 is unreachable
    STORAGE_AUTO_FALLBACK: bool = True
    STORAGE_LOCAL_DIR: str = "storage_local"
    
    # AI Providers
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_ORG_ID: Optional[str] = None
    OPENAI_BASE_URL: Optional[str] = None
    
    ANTHROPIC_API_KEY: Optional[str] = None
    ANTHROPIC_BASE_URL: Optional[str] = None
    
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_BASE_URL: Optional[str] = None
    GEMINI_EMBEDDING_MODEL: str = "gemini-embedding-001"
    GEMINI_EMBEDDING_DIMENSION: int = 1536
    
    OPENROUTER_API_KEY: Optional[str] = None
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"

    GROQ_API_KEY: Optional[str] = None
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
    GROQ_MODEL: str = "openai/gpt-oss-120b"
    GROQ_VISION_MODEL: str = "qwen/qwen3.6-27b"
    GROQ_EMBEDDING_MODEL: str = "nomic-embed-text-v1.5"
    GROQ_EMBEDDING_DIMENSION: int = 768
    
    # Embedding Models
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIMENSION: int = 1536
    EMBEDDING_BATCH_SIZE: int = 100
    
    # RAG Settings
    RAG_CHUNK_SIZE: int = 1000
    RAG_CHUNK_OVERLAP: int = 200
    RAG_TOP_K: int = 5
    RAG_SIMILARITY_THRESHOLD: float = 0.45
    RAG_RERANK_TOP_K: int = 10
    RAG_RERANK_MODEL: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    
    # Web Search
    SEARCH_API_KEY: Optional[str] = None
    SEARCH_ENGINE: str = "serpapi"  # serpapi, google, bing, duckduckgo
    SEARCH_MAX_RESULTS: int = 10
    
    # Email
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_TLS: bool = True
    SMTP_SSL: bool = False
    EMAIL_FROM: str = "noreply@nova-ai.com"
    EMAIL_FROM_NAME: str = "Nova AI"
    DEV_EMAIL_DIR: str = "var/emails"
    
    # OAuth
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_REDIRECT_URI: str = "http://localhost:3000/auth/callback/google"
    
    GITHUB_CLIENT_ID: Optional[str] = None
    GITHUB_CLIENT_SECRET: Optional[str] = None
    GITHUB_REDIRECT_URI: str = "http://localhost:3000/auth/callback/github"
    
    # First Superuser
    FIRST_SUPERUSER_EMAIL: str = "admin@nova-ai.com"
    FIRST_SUPERUSER_PASSWORD: str = "changeme123"
    FIRST_SUPERUSER_USERNAME: str = "admin"
    
    # Rate Limiting
    RATE_LIMIT_ENABLED: bool = False
    RATE_LIMIT_REQUESTS: int = 100
    RATE_LIMIT_WINDOW: int = 60  # seconds
    RATE_LIMIT_LOGIN_REQUESTS: int = 5
    RATE_LIMIT_LOGIN_WINDOW: int = 300  # 5 minutes
    RATE_LIMIT_REGISTER_REQUESTS: int = 100
    RATE_LIMIT_REGISTER_WINDOW: int = 60  # 1 hour
    
    # File Upload
    MAX_FILE_SIZE: int = 100 * 1024 * 1024  # 100MB
    ALLOWED_FILE_TYPES: List[str] = [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/plain",
        "text/markdown",
        "text/csv",
        "application/json",
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
        "audio/mpeg",
        "audio/wav",
        "audio/ogg",
        "video/mp4",
        "video/webm",
    ]
    ALLOWED_IMAGE_TYPES: List[str] = [
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
    ]
    
    # WebSocket
    WS_HEARTBEAT_INTERVAL: int = 30
    WS_MAX_MESSAGE_SIZE: int = 1024 * 1024  # 1MB
    
    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
    CELERY_TASK_TRACK_STARTED: bool = True
    CELERY_TASK_TIME_LIMIT: int = 3600
    CELERY_WORKER_PREFETCH_MULTIPLIER: int = 4
    CELERY_WORKER_CONCURRENCY: int = 8
    CELERY_BEAT_SCHEDULE_ENABLED: bool = True
    
    # Frontend
    FRONTEND_URL: str = "http://localhost:3000"
    
    # Voice (Speech-to-Text / Text-to-Speech)
    STT_PROVIDER: str = "openai"  # openai, whisper-local
    STT_MODEL: str = "whisper-1"
    TTS_PROVIDER: str = "edge"  # openai, elevenlabs, edge
    TTS_MODEL: str = "tts-1"
    TTS_VOICE: str = "alloy"
    ELEVENLABS_API_KEY: Optional[str] = None
    ELEVENLABS_VOICE_ID: str = "21m00Tcm4TlvDq8ikWAM"
    TTS_EDGE_VOICE: str = "en-US-JennyNeural"
    
    # Browser automation (Playwright)
    BROWSER_HEADLESS: bool = True
    BROWSER_TIMEOUT_MS: int = 30000
    BROWSER_MAX_NAVIGATIONS: int = 5
    
    # MCP (Model Context Protocol)
    MCP_ENABLED: bool = True
    MCP_SERVERS: dict = {
        "filesystem": {"transport": "stdio", "command": "mcp-server-filesystem"},
    }
    
    # Analytics
    POSTHOG_API_KEY: Optional[str] = None
    POSTHOG_HOST: Optional[str] = None
    MIXPANEL_TOKEN: Optional[str] = None
    
    # Stripe
    STRIPE_SECRET_KEY: Optional[str] = None
    STRIPE_PUBLISHABLE_KEY: Optional[str] = None
    STRIPE_WEBHOOK_SECRET: Optional[str] = None
    STRIPE_BILLING_PORTAL_URL: Optional[str] = None
    
    # Plugins sandbox
    PLUGIN_SANDBOX_TIMEOUT: int = 30
    PLUGIN_MAX_PAYLOAD_SIZE: int = 2 * 1024 * 1024
    
    # Monitoring
    OTEL_ENABLED: bool = False
    OTEL_EXPORTER_ENDPOINT: Optional[str] = None
    SENTRY_DSN: Optional[str] = None
    SENTRY_TRACES_SAMPLE_RATE: float = 0.1
    SENTRY_PROFILES_SAMPLE_RATE: float = 0.1
    
    PROMETHEUS_ENABLED: bool = True
    PROMETHEUS_PORT: int = 9090
    
    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"
    LOG_FILE: Optional[str] = None
    
    # Feature Flags
    FEATURE_WEB_SEARCH: bool = True
    FEATURE_VOICE: bool = True
    FEATURE_VISION: bool = True
    VISION_MAX_TOKENS: int = 1024
    FEATURE_AGENTS: bool = True
    FEATURE_WORKFLOWS: bool = True
    FEATURE_MARKETPLACE: bool = True
    FEATURE_API_KEYS: bool = True
    FEATURE_WEBHOOKS: bool = True
    FEATURE_AUDIT_LOGS: bool = True
    FEATURE_BILLING: bool = True
    
    # Pagination
    DEFAULT_PAGE_SIZE: int = 20
    MAX_PAGE_SIZE: int = 100
    
    # Cache
    CACHE_TTL: int = 300  # 5 minutes
    CACHE_PREFIX: str = "nova_ai:"
    
    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str | List[str]) -> List[str]:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def normalize_database_url(cls, v: str) -> str:
        """Add the asyncpg driver so plain postgres:// URLs (e.g. Render) work."""
        if v.startswith("postgresql://") and "+asyncpg" not in v:
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v
    
    @field_validator("ALLOWED_FILE_TYPES", mode="before")
    @classmethod
    def parse_allowed_file_types(cls, v: str | List[str]) -> List[str]:
        if isinstance(v, str):
            return [t.strip() for t in v.split(",")]
        return v
    
    @property
    def DATABASE_URL_SYNC(self) -> str:
        """Get synchronous database URL for Alembic."""
        return self.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    
    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT == "development"
    
    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"
    
    @property
    def is_testing(self) -> bool:
        return self.TESTING or self.ENVIRONMENT == "testing"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
print("=" * 60)
print("DATABASE_URL =", settings.DATABASE_URL)
print("DB_ECHO =", settings.DB_ECHO)
print("ENVIRONMENT =", settings.ENVIRONMENT)
print("=" * 60)