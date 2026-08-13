from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


Role = Literal["viewer", "analyst", "operator", "admin"]

ROLE_PERMISSIONS: dict[str, list[str]] = {
    "viewer": [
        "api.read", "chat.use", "knowledge.read", "conversation.read", "capability.read",
    ],
    "analyst": [
        "api.read", "chat.use", "knowledge.read", "knowledge.intake", "conversation.read",
        "conversation.write", "feedback.submit", "evaluation.run", "rl.manage", "capability.read",
        "capability.preview", "context.write",
    ],
    "operator": [
        "api.read", "chat.use", "knowledge.read", "knowledge.intake", "conversation.read",
        "conversation.write", "feedback.submit", "evaluation.run", "rl.manage", "capability.read",
        "capability.preview", "capability.invoke_read", "context.write", "automation.execute",
        "operations.manage", "connector.check", "connector.preflight", "audit.read",
        "observability.read",
    ],
    "admin": ["*"],
}


@dataclass(frozen=True)
class IdentityContext:
    actor_id: str
    role: Role
    authenticated: bool
    authentication_status: str

    @property
    def permissions(self) -> list[str]:
        return list(ROLE_PERMISSIONS[self.role])


def has_permission(role: str, permission: str) -> bool:
    allowed = ROLE_PERMISSIONS.get(role, [])
    return "*" in allowed or permission in allowed


def required_permission(method: str, path: str) -> str | None:
    if not path.startswith("/api") and path != "/metrics":
        return None
    if method == "OPTIONS":
        return None
    if path == "/metrics" or path.startswith("/api/governance/audit") or path.startswith("/api/governance/metrics"):
        return "observability.read"
    if method in {"GET", "HEAD"}:
        return "api.read"
    if (
        path == "/api/chat"
        or path == "/api/chat/stream"
        or path.startswith("/api/chat/generations/")
    ):
        return "chat.use"
    if path.startswith("/api/knowledge/intake"):
        return "knowledge.intake"
    if path.startswith("/api/conversations"):
        return "conversation.write"
    if path.startswith("/api/rl-lab") or path.startswith("/api/rl-mission"):
        return "rl.manage"
    if path.startswith("/api/automation"):
        return "automation.execute"
    if path.startswith("/api/tasks") or path.startswith("/api/reports"):
        return "operations.manage"
    if path.startswith("/api/port-simulator"):
        return "operations.manage"
    if path.startswith("/api/orchestrator") or "/invoke" in path and path.startswith("/api/hub"):
        return "capability.invoke_read"
    if path.endswith("/health-check") and path.startswith("/api/connectors"):
        return "connector.check"
    if path.endswith("/write-preflight") and path.startswith("/api/connectors"):
        return "connector.preflight"
    if path.startswith(("/api/simulator", "/api/sailing-simulator", "/api/linked-systems", "/api/system-linkage")):
        return "*"
    if path.startswith("/api/evaluation/feedback/"):
        return "*"
    if path.startswith("/api/evaluation"):
        return "evaluation.run"
    if path.startswith("/api/context"):
        return "context.write"
    return "capability.preview"
