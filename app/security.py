from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable
from uuid import uuid4

from fastapi import Request
from starlette.datastructures import Headers
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.access_control import IdentityContext, ROLE_PERMISSIONS, has_permission, required_permission
from app.observability import TelemetryRegistry, configure_logging
from app.runtime_store import runtime_store
from app.settings import Settings


_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,128}$")
_TOKEN_PART = re.compile(r"^[A-Za-z0-9_-]+$")
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9._:-]{8,160}$")


class AuthenticationError(ValueError):
    pass


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    if not _TOKEN_PART.fullmatch(value):
        raise AuthenticationError("令牌编码无效")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue_access_token(
    *,
    actor_id: str,
    role: str,
    settings: Settings,
    expires_minutes: int = 60,
) -> str:
    if role not in ROLE_PERMISSIONS:
        raise ValueError(f"unsupported role: {role}")
    if len(settings.jwt_secret.encode("utf-8")) < 32:
        raise ValueError("JWT secret must be at least 32 bytes")
    now = datetime.now(timezone.utc)
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": actor_id,
        "role": role,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=max(1, expires_minutes))).timestamp()),
        "jti": uuid4().hex,
    }
    signing_input = f"{_b64encode(json.dumps(header, separators=(',', ':')).encode())}.{_b64encode(json.dumps(payload, separators=(',', ':')).encode())}"
    signature = hmac.new(settings.jwt_secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64encode(signature)}"


def verify_access_token(token: str, settings: Settings, *, now: datetime | None = None) -> IdentityContext:
    parts = token.split(".")
    if len(parts) != 3:
        raise AuthenticationError("Bearer令牌格式无效")
    signing_input = f"{parts[0]}.{parts[1]}"
    expected = hmac.new(settings.jwt_secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    try:
        supplied = _b64decode(parts[2])
        header = json.loads(_b64decode(parts[0]))
        payload = json.loads(_b64decode(parts[1]))
    except (ValueError, json.JSONDecodeError) as exc:
        raise AuthenticationError("Bearer令牌无法解析") from exc
    if header.get("alg") != "HS256" or not hmac.compare_digest(expected, supplied):
        raise AuthenticationError("Bearer令牌签名无效")
    current = int((now or datetime.now(timezone.utc)).timestamp())
    skew = settings.jwt_clock_skew_seconds
    if payload.get("iss") != settings.jwt_issuer or payload.get("aud") != settings.jwt_audience:
        raise AuthenticationError("Bearer令牌签发方或受众不匹配")
    if not isinstance(payload.get("exp"), int) or current > payload["exp"] + skew:
        raise AuthenticationError("Bearer令牌已过期")
    if isinstance(payload.get("nbf"), int) and current + skew < payload["nbf"]:
        raise AuthenticationError("Bearer令牌尚未生效")
    actor_id = str(payload.get("sub") or "").strip()
    role = str(payload.get("role") or "").strip()
    if len(actor_id) < 2 or role not in ROLE_PERMISSIONS:
        raise AuthenticationError("Bearer令牌身份声明无效")
    return IdentityContext(
        actor_id=actor_id,
        role=role,  # type: ignore[arg-type]
        authenticated=True,
        authentication_status="jwt_hs256_verified",
    )


def request_identity(request: Request) -> IdentityContext:
    identity = getattr(request.state, "identity", None)
    if isinstance(identity, IdentityContext):
        return identity
    return IdentityContext("local-admin", "admin", False, "local_unverified_header")


def bind_claimed_identity(request: Request, actor_id: str, role: str) -> tuple[str, str]:
    identity = request_identity(request)
    if identity.authenticated:
        return identity.actor_id, identity.role
    return actor_id, role


class SlidingWindowRateLimiter:
    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = max(1, limit)
        self.window_seconds = max(1, window_seconds)
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.RLock()

    def consume(self, key: str, now: float | None = None) -> tuple[bool, int, int]:
        moment = now if now is not None else time.monotonic()
        cutoff = moment - self.window_seconds
        with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            allowed = len(events) < self.limit
            if allowed:
                events.append(moment)
            remaining = max(0, self.limit - len(events))
            retry_after = max(1, int(self.window_seconds - (moment - events[0]))) if events and not allowed else 0
            if not events:
                self._events.pop(key, None)
        return allowed, remaining, retry_after


class PlatformMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, settings: Settings, telemetry: TelemetryRegistry) -> None:
        super().__init__(app)
        self.settings = settings
        self.telemetry = telemetry
        self.rate_limiter = SlidingWindowRateLimiter(settings.rate_limit_requests, settings.rate_limit_window_seconds)
        self.logger = configure_logging(settings.log_level)

    def _identity(self, request: Request) -> IdentityContext:
        if self.settings.security_mode == "local":
            actor = request.headers.get("X-Xiaoyi-Actor", "local-admin").strip()[:100] or "local-admin"
            role = request.headers.get("X-Xiaoyi-Role", "admin").strip().lower()
            if role not in ROLE_PERMISSIONS:
                role = "viewer"
            return IdentityContext(actor, role, False, "local_unverified_header")  # type: ignore[arg-type]
        authorization = request.headers.get("Authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise AuthenticationError("需要有效的 Authorization: Bearer 令牌")
        return verify_access_token(token, self.settings)

    @staticmethod
    def _public_path(path: str) -> bool:
        return path == "/" or path.startswith("/web/") or path in {
            "/favicon.ico", "/health", "/health/live", "/health/ready", "/openapi.json", "/docs", "/redoc",
        }

    @staticmethod
    def _error(status: int, detail: str, request_id: str, headers: dict[str, str] | None = None) -> JSONResponse:
        return JSONResponse(status_code=status, content={"detail": detail, "request_id": request_id}, headers=headers)

    def _secure_headers(self, response: Response, request_id: str, duration: float) -> None:
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; "
            "base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        )
        response.headers["Server-Timing"] = f"app;dur={duration * 1000:.2f}"
        if self.settings.production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        started = time.perf_counter()
        self.telemetry.begin()
        supplied_id = request.headers.get("X-Request-ID") or request.headers.get("X-Xiaoyi-Trace-Id") or ""
        request_id = supplied_id if _REQUEST_ID.fullmatch(supplied_id) else f"req-{uuid4().hex}"
        request.state.request_id = request_id
        identity = IdentityContext("anonymous", "viewer", False, "anonymous")
        response: Response
        try:
            content_length = request.headers.get("Content-Length")
            if content_length and int(content_length) > self.settings.max_request_bytes:
                response = self._error(413, "请求体超过服务端允许大小", request_id)
            else:
                try:
                    identity = self._identity(request)
                except AuthenticationError as exc:
                    if self._public_path(request.url.path) or request.method == "OPTIONS":
                        identity = IdentityContext("anonymous", "viewer", False, "anonymous")
                    else:
                        response = self._error(401, str(exc), request_id, {"WWW-Authenticate": "Bearer"})
                        raise _ResponseReady(response)
                request.state.identity = identity
                permission = required_permission(request.method, request.url.path)
                if self.settings.security_mode == "jwt" and permission and not has_permission(identity.role, permission):
                    response = self._error(403, f"当前角色缺少权限：{permission}", request_id)
                else:
                    client_host = request.client.host if request.client else "unknown"
                    rate_key = f"{identity.actor_id}:{client_host}"
                    allowed, remaining, retry_after = self.rate_limiter.consume(rate_key)
                    if not allowed and not self._public_path(request.url.path):
                        response = self._error(429, "请求过于频繁，请稍后重试", request_id, {"Retry-After": str(retry_after)})
                    else:
                        response = await call_next(request)
                        response.headers["X-RateLimit-Limit"] = str(self.settings.rate_limit_requests)
                        response.headers["X-RateLimit-Remaining"] = str(remaining)
        except _ResponseReady as ready:
            response = ready.response
        except ValueError:
            response = self._error(400, "请求头格式无效", request_id)
        except Exception:
            self.logger.exception("unhandled_request_error", extra={"structured": {"request_id": request_id, "path": request.url.path}})
            response = self._error(500, "服务内部错误", request_id)
        duration = time.perf_counter() - started
        route = getattr(request.scope.get("route"), "path", request.url.path)
        self._secure_headers(response, request_id, duration)
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        self.telemetry.finish(request.method, route, response.status_code, duration)
        self.logger.info(
            "http_request",
            extra={"structured": {
                "request_id": request_id, "method": request.method, "route": route,
                "status": response.status_code, "duration_ms": round(duration * 1000, 3),
                "actor_id": identity.actor_id, "actor_role": identity.role,
            }},
        )
        return response


class _ResponseReady(Exception):
    def __init__(self, response: Response) -> None:
        self.response = response


class IdempotencyMiddleware:
    """Persist successful mutation responses keyed by caller and idempotency key."""

    def __init__(self, app: ASGIApp, *, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    @staticmethod
    def _namespace(headers: Headers) -> str:
        credential = headers.get("authorization") or headers.get("x-xiaoyi-actor") or "anonymous"
        return hashlib.sha256(credential.encode()).hexdigest()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        method = str(scope.get("method") or "GET").upper()
        path = str(scope.get("path") or "")
        headers = Headers(scope=scope)
        key = headers.get("x-idempotency-key", "")
        if method not in {"POST", "PUT", "PATCH", "DELETE"} or not key or path.endswith("/stream"):
            await self.app(scope, receive, send)
            return
        if not _IDEMPOTENCY_KEY.fullmatch(key):
            response = JSONResponse(status_code=400, content={"detail": "X-Idempotency-Key 格式无效"})
            await response(scope, receive, send)
            return
        body_parts: list[bytes] = []
        more = True
        while more:
            message = await receive()
            if message["type"] != "http.request":
                continue
            body_parts.append(message.get("body", b""))
            more = bool(message.get("more_body", False))
        body = b"".join(body_parts)
        request_hash = hashlib.sha256(method.encode() + b"\0" + path.encode() + b"\0" + body).hexdigest()
        namespace = self._namespace(headers)
        cached = runtime_store.get_idempotency(namespace, key)
        if cached:
            if cached["method"] != method or cached["path"] != path or cached["request_hash"] != request_hash:
                response = JSONResponse(status_code=409, content={"detail": "幂等键已用于不同请求"})
                await response(scope, receive, send)
                return
            replay_headers = [(name.encode("latin-1"), value.encode("latin-1")) for name, value in cached["response_headers"] if name.lower() not in {"content-length", "x-request-id"}]
            replay_headers.append((b"x-idempotent-replay", b"true"))
            await send({"type": "http.response.start", "status": cached["status_code"], "headers": replay_headers})
            await send({"type": "http.response.body", "body": bytes(cached["response_body"])})
            return

        delivered = False

        async def replay_receive() -> Message:
            nonlocal delivered
            if delivered:
                return {"type": "http.request", "body": b"", "more_body": False}
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}

        status_code = 500
        response_headers: list[tuple[str, str]] = []
        response_body = bytearray()

        async def capture_send(message: Message) -> None:
            nonlocal status_code, response_headers
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                response_headers = [
                    (name.decode("latin-1"), value.decode("latin-1"))
                    for name, value in message.get("headers", [])
                ]
            elif message["type"] == "http.response.body" and len(response_body) <= 1_000_000:
                response_body.extend(message.get("body", b""))
            await send(message)

        await self.app(scope, replay_receive, capture_send)
        if 200 <= status_code < 300 and len(response_body) <= 1_000_000:
            runtime_store.save_idempotency(
                namespace=namespace, key=key, method=method, path=path, request_hash=request_hash,
                status_code=status_code, response_headers=response_headers, response_body=bytes(response_body),
                ttl_seconds=self.settings.idempotency_ttl_seconds,
            )
