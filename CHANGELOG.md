# Changelog

All notable changes are documented here. The project follows semantic versioning once tagged releases begin.

## [0.3.0] - 2026-07-20

### Added

- Production-gated JWT authentication, role-based authorization, request limits, rate limiting, security headers, and persistent idempotency.
- Durable conversation, task, report, automation, audit, and feedback state in SQLite with fail-safe restart behavior.
- Deep liveness/readiness endpoints, Prometheus metrics, structured JSON request logs, request IDs, and model-gateway status.
- Optional OpenAI-compatible model gateway with evidence gates, privacy opt-in, retries, circuit breaker, and local fallback.
- Container build, hardened local Compose profile, locked dependencies, CI, dependency review, Dependabot, release checks, and deployment guidance.
- Persistent server-side chat history and standard server-sent-event chat streaming API.

### Changed

- The web system-status panel now checks identity, deployment configuration, persistence, model state, knowledge indexing, and connectors separately.
- Authenticated production identities override all client-supplied actor/operator fields.
- Operations tasks, reports, and automation plans survive restarts; interrupted work is marked failed or cancelled instead of silently continuing.

### Security

- Production startup fails when JWT, signing secret, allowed hosts, or CORS origins are unsafe or incomplete.
- State-changing routes accept replay-safe idempotency keys, while public launch routes require the administrator role.

## [0.2.0] - 2026-07-20

- Replaced demonstration RL curves with four real tabular RL algorithms plus a PID baseline.
- Added public UCI dataset provenance, temporal train/validation/test separation, no-render training, and post-training test rendering.

