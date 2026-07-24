from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal


Environment = Literal["local", "staging", "production"]
SecurityMode = Literal["local", "jwt"]
ModelProvider = Literal["local_rules", "openai_compatible"]


def _boolean(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _integer(name: str, default: int, *, minimum: int = 0) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _number(name: str, default: float, *, minimum: float = 0.0) -> float:
    try:
        return max(minimum, float(os.getenv(name, str(default))))
    except ValueError:
        return default


def _csv(name: str, default: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in os.getenv(name, default).split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    environment: Environment
    security_mode: SecurityMode
    jwt_secret: str
    jwt_issuer: str
    jwt_audience: str
    jwt_clock_skew_seconds: int
    cors_origins: tuple[str, ...]
    allowed_hosts: tuple[str, ...]
    docs_enabled: bool
    rate_limit_requests: int
    rate_limit_window_seconds: int
    max_request_bytes: int
    idempotency_ttl_seconds: int
    chat_retention_enabled: bool
    chat_retention_days: int
    model_provider: ModelProvider
    model_base_url: str
    model_name: str
    model_api_key: str
    model_timeout_seconds: float
    model_max_retries: int
    model_external_data_allowed: bool
    log_level: str

    @property
    def production(self) -> bool:
        return self.environment == "production"

    @classmethod
    def from_env(cls) -> "Settings":
        environment_raw = os.getenv("XIAOYI_ENV", "local").strip().lower()
        environment: Environment = environment_raw if environment_raw in {"local", "staging", "production"} else "local"  # type: ignore[assignment]
        default_security = "jwt" if environment == "production" else "local"
        security_raw = os.getenv("XIAOYI_SECURITY_MODE", default_security).strip().lower()
        security_mode: SecurityMode = security_raw if security_raw in {"local", "jwt"} else "local"  # type: ignore[assignment]
        provider_raw = os.getenv("XIAOYI_MODEL_PROVIDER", "local_rules").strip().lower()
        model_provider: ModelProvider = provider_raw if provider_raw in {"local_rules", "openai_compatible"} else "local_rules"  # type: ignore[assignment]
        return cls(
            environment=environment,
            security_mode=security_mode,
            jwt_secret=os.getenv("XIAOYI_JWT_SECRET", ""),
            jwt_issuer=os.getenv("XIAOYI_JWT_ISSUER", "xiaoyi-ai"),
            jwt_audience=os.getenv("XIAOYI_JWT_AUDIENCE", "xiaoyi-api"),
            jwt_clock_skew_seconds=_integer("XIAOYI_JWT_CLOCK_SKEW_SECONDS", 30),
            cors_origins=_csv("XIAOYI_CORS_ORIGINS", "http://127.0.0.1:8010,http://localhost:8010"),
            allowed_hosts=_csv("XIAOYI_ALLOWED_HOSTS", "127.0.0.1,localhost,testserver"),
            docs_enabled=_boolean("XIAOYI_DOCS_ENABLED", environment != "production"),
            rate_limit_requests=_integer("XIAOYI_RATE_LIMIT_REQUESTS", 120 if environment == "production" else 600, minimum=1),
            rate_limit_window_seconds=_integer("XIAOYI_RATE_LIMIT_WINDOW_SECONDS", 60, minimum=1),
            max_request_bytes=_integer("XIAOYI_MAX_REQUEST_BYTES", 2_500_000, minimum=1024),
            idempotency_ttl_seconds=_integer("XIAOYI_IDEMPOTENCY_TTL_SECONDS", 86_400, minimum=60),
            chat_retention_enabled=_boolean("XIAOYI_CHAT_RETENTION_ENABLED", True),
            chat_retention_days=_integer("XIAOYI_CHAT_RETENTION_DAYS", 30, minimum=1),
            model_provider=model_provider,
            model_base_url=(os.getenv("XIAOYI_MODEL_BASE_URL") or os.getenv("OPENAI_BASE_URL") or "").rstrip("/"),
            model_name=os.getenv("XIAOYI_MODEL_NAME") or os.getenv("OPENAI_MODEL") or "",
            model_api_key=os.getenv("XIAOYI_MODEL_API_KEY") or os.getenv("OPENAI_API_KEY") or "",
            model_timeout_seconds=_number("XIAOYI_MODEL_TIMEOUT_SECONDS", 30.0, minimum=1.0),
            model_max_retries=_integer("XIAOYI_MODEL_MAX_RETRIES", 2, minimum=0),
            model_external_data_allowed=_boolean("XIAOYI_MODEL_EXTERNAL_DATA_ALLOWED", False),
            log_level=os.getenv("XIAOYI_LOG_LEVEL", "INFO").upper(),
        )

    def deployment_blockers(self) -> list[str]:
        blockers: list[str] = []
        if self.production and self.security_mode != "jwt":
            blockers.append("production 环境必须设置 XIAOYI_SECURITY_MODE=jwt")
        if (self.production or self.security_mode == "jwt") and len(self.jwt_secret.encode("utf-8")) < 32:
            blockers.append("JWT签名密钥必须至少32字节")
        if self.production and (not self.allowed_hosts or "*" in self.allowed_hosts):
            blockers.append("production 环境必须配置显式 XIAOYI_ALLOWED_HOSTS")
        if self.production and (not self.cors_origins or "*" in self.cors_origins):
            blockers.append("production 环境必须配置显式 XIAOYI_CORS_ORIGINS")
        if self.model_provider == "openai_compatible":
            if not self.model_base_url:
                blockers.append("openai_compatible 模型缺少 XIAOYI_MODEL_BASE_URL")
            if not self.model_name:
                blockers.append("openai_compatible 模型缺少 XIAOYI_MODEL_NAME")
            if not self.model_api_key and not self.model_base_url.startswith(("http://127.0.0.1", "http://localhost")):
                blockers.append("远程模型接口缺少 XIAOYI_MODEL_API_KEY")
            if self.production and not self.model_external_data_allowed:
                blockers.append("远程模型发送证据前必须显式设置 XIAOYI_MODEL_EXTERNAL_DATA_ALLOWED=true")
        return blockers

    def validate_startup(self) -> None:
        blockers = self.deployment_blockers()
        if blockers:
            raise RuntimeError("; ".join(blockers))


settings = Settings.from_env()
