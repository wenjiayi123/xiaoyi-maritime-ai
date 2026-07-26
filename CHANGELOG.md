# Changelog

All notable changes are documented here. The project follows semantic versioning once tagged releases begin.

## [0.4.0] - 2026-07-26

### Added

- A 409,887-row UCI large-scale energy benchmark and a measured NOAA AIS port-traffic scenario, each with fixed provenance, transformations, licensing notice, and SHA-256.
- A `port_operations` environment with 11 observations, five capacity actions, a safety-constrained objective, port profiles, factor coverage, and international-port integration fields.
- A three-dataset, three-seed benchmark for four tabular RL algorithms and the PID control baseline, including tracked legacy and selected-run evidence bundles.
- A one-screen training center connecting the evidence ledger, algorithm matrix, Xiaoyi training advisor, environment contract, system linkage, and configuration actions.
- Port RL landing, data-contract, resume-claim, and public-data documentation.

### Changed

- Energy actions are masked against projected SOC feasibility before selection; PID now obeys the same mask.
- Test evaluation fails closed when dataset, port profile, or model hashes change.
- Chat streaming follows natural punctuation boundaries, and evidence-grounded responses use shorter Chinese-first phrasing.

### Evidence boundary

- UCI results remain public offline energy benchmarks.
- AIS traffic observations are measured; service, backlog, waiting, and score are calibrated planning outputs.
- Production connectors remain read-only and fail closed until a site provides verified configuration.

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
