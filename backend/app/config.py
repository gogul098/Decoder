"""Runtime settings, all from environment variables."""
import os
from dataclasses import dataclass, field


def _list(name: str, default: str) -> list[str]:
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


# Groq rate limits are per organisation *per model*, so spreading work across
# several models multiplies throughput. Each entry: model_id:requests_per_minute:weight
# Weight = preference (higher = picked more often, e.g. better writers).
DEFAULT_MODELS = (
    # llama-3.3-70b-versatile and llama-3.1-8b-instant were shut down by Groq on 2026-08-16.
    # Models Groq no longer serves are dropped at start-up by Balancer.discover().
    "openai/gpt-oss-120b:30:5,"
    "qwen/qwen3.8-27b:30:4,"
    "openai/gpt-oss-20b:30:3,"
    "qwen/qwen3-32b:60:3,"
    "meta-llama/llama-4-scout-17b-16e-instruct:30:2"
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
    # App updates come from this repo's "latest" release. Set GITHUB_TOKEN (fine-grained, read-only
    # "Contents" on this one repo) once the repo is private.
    github_repo: str = os.getenv("GITHUB_REPO", "gogul098/Decoder")
    github_token: str = os.getenv("GITHUB_TOKEN", "")
    models: list[ModelSpec] = field(default_factory=_models)
    llm_mock: bool = os.getenv("LLM_MOCK", "0") == "1"          # offline testing
    news_mock: bool = os.getenv("NEWS_MOCK", "0") == "1"        # offline testing
    feed_ttl: int = int(os.getenv("FEED_TTL_SECONDS", "900"))   # refresh top-5 every 15 min
    explain_ttl: int = int(os.getenv("EXPLAIN_TTL_SECONDS", str(24 * 3600)))
    prewarm: bool = os.getenv("PREWARM", "0") == "1"            # decode top stories before anyone opens them
    worker_concurrency: int = int(os.getenv("WORKER_CONCURRENCY", "8"))
    client_rpm: int = int(os.getenv("CLIENT_RPM", "60"))        # per-IP API limit
    # Spend guards for the paid model calls (an attacker must not be able to drain the daily quota)
    decode_per_ip_day: int = int(os.getenv("DECODE_PER_IP_DAY", "80"))     # new decodes one phone/IP may start per day
    decode_daily_cap: int = int(os.getenv("DECODE_DAILY_CAP", "400"))      # new decodes for everyone per day
    translate_daily_cap: int = int(os.getenv("TRANSLATE_DAILY_CAP", "600"))  # headline-translation batches per day
    streams_per_ip: int = int(os.getenv("STREAMS_PER_IP", "8"))            # open live streams per IP
    debug_token: str = os.getenv("DEBUG_TOKEN", "")                         # empty = /api/debug disabled
    cors_origins: list[str] = field(default_factory=lambda: _list(
        "CORS_ORIGINS", "https://localhost,http://localhost,capacitor://localhost"))
    region: str = os.getenv("NEWS_REGION", "IN")                 # Google News edition
    # Run the queue worker inside the API process (one-service hosting such as Render Free)
    embedded_worker: bool = os.getenv("EMBEDDED_WORKER", "0") == "1"


settings = Settings()
