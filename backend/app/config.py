"""Runtime settings, all from environment variables."""
import os
from dataclasses import dataclass, field


def _list(name: str, default: str) -> list[str]:
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


# Groq rate limits are per organisation *per model*, so spreading work across
# several models multiplies throughput. Each entry: model_id:requests_per_minute:weight
# Weight = preference (higher = picked more often, e.g. better writers).
DEFAULT_MODELS = (
    "openai/gpt-oss-120b:30:5,"
    "llama-3.3-70b-versatile:30:4,"
    "qwen/qwen3-32b:60:3,"
    "openai/gpt-oss-20b:30:3,"
    "meta-llama/llama-4-scout-17b-16e-instruct:30:2,"
    "llama-3.1-8b-instant:30:1"
)


@dataclass(frozen=True)
class ModelSpec:
    model: str
    rpm: int
    weight: int


def _models() -> list[ModelSpec]:
    out = []
    for item in _list("GROQ_MODELS", DEFAULT_MODELS):
        parts = item.split(":")
        rpm = int(parts[1]) if len(parts) > 1 else 30
        weight = int(parts[2]) if len(parts) > 2 else 1
        out.append(ModelSpec(parts[0], rpm, weight))
    return out


@dataclass
class Settings:
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    # Several keys are allowed (e.g. from different Groq orgs) — each key×model is its own lane.
    groq_keys: list[str] = field(default_factory=lambda: _list("GROQ_API_KEYS", os.getenv("GROQ_API_KEY", "")))
    groq_base: str = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    models: list[ModelSpec] = field(default_factory=_models)
    llm_mock: bool = os.getenv("LLM_MOCK", "0") == "1"          # offline testing
    news_mock: bool = os.getenv("NEWS_MOCK", "0") == "1"        # offline testing
    feed_ttl: int = int(os.getenv("FEED_TTL_SECONDS", "900"))   # refresh top-5 every 15 min
    explain_ttl: int = int(os.getenv("EXPLAIN_TTL_SECONDS", str(24 * 3600)))
    prewarm: bool = os.getenv("PREWARM", "0") == "1"            # decode top stories before anyone opens them
    worker_concurrency: int = int(os.getenv("WORKER_CONCURRENCY", "8"))
    client_rpm: int = int(os.getenv("CLIENT_RPM", "60"))        # per-IP API limit
    region: str = os.getenv("NEWS_REGION", "IN")                 # Google News edition


settings = Settings()
