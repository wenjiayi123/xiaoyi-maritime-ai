from __future__ import annotations

import json
import logging
import threading
import time
from collections import Counter
from typing import Any


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        fields = getattr(record, "structured", None)
        if isinstance(fields, dict):
            payload.update(fields)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)[-4000:]
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger("xiaoyi.http")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    logger.propagate = False
    return logger


class TelemetryRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._started = time.monotonic()
        self._requests: Counter[tuple[str, str, int]] = Counter()
        self._latency_seconds: Counter[tuple[str, str]] = Counter()
        self._in_flight = 0

    def begin(self) -> None:
        with self._lock:
            self._in_flight += 1

    def finish(self, method: str, route: str, status: int, duration_seconds: float) -> None:
        with self._lock:
            self._in_flight = max(0, self._in_flight - 1)
            self._requests[(method, route, status)] += 1
            self._latency_seconds[(method, route)] += duration_seconds

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            total = sum(self._requests.values())
            errors = sum(count for (_, _, status), count in self._requests.items() if status >= 500)
            return {
                "uptime_seconds": round(time.monotonic() - self._started, 3),
                "requests_total": total,
                "server_errors_total": errors,
                "in_flight": self._in_flight,
            }

    def prometheus(self, *, app_name: str, version: str) -> str:
        safe_app = app_name.replace('"', '\\"')
        safe_version = version.replace('"', '\\"')
        lines = [
            "# HELP xiaoyi_build_info Static build metadata.",
            "# TYPE xiaoyi_build_info gauge",
            f'xiaoyi_build_info{{app="{safe_app}",version="{safe_version}"}} 1',
            "# HELP xiaoyi_uptime_seconds Process uptime in seconds.",
            "# TYPE xiaoyi_uptime_seconds gauge",
            f"xiaoyi_uptime_seconds {time.monotonic() - self._started:.6f}",
            "# HELP xiaoyi_http_requests_in_flight Current in-flight HTTP requests.",
            "# TYPE xiaoyi_http_requests_in_flight gauge",
        ]
        with self._lock:
            lines.append(f"xiaoyi_http_requests_in_flight {self._in_flight}")
            lines.extend([
                "# HELP xiaoyi_http_requests_total HTTP requests by method, route and status.",
                "# TYPE xiaoyi_http_requests_total counter",
            ])
            for (method, route, status), count in sorted(self._requests.items()):
                route_value = route.replace('"', '\\"')
                lines.append(
                    f'xiaoyi_http_requests_total{{method="{method}",route="{route_value}",status="{status}"}} {count}'
                )
            lines.extend([
                "# HELP xiaoyi_http_request_duration_seconds_sum Accumulated HTTP request latency.",
                "# TYPE xiaoyi_http_request_duration_seconds_sum counter",
            ])
            for (method, route), value in sorted(self._latency_seconds.items()):
                route_value = route.replace('"', '\\"')
                lines.append(
                    f'xiaoyi_http_request_duration_seconds_sum{{method="{method}",route="{route_value}"}} {value:.6f}'
                )
        return "\n".join(lines) + "\n"


telemetry = TelemetryRegistry()
