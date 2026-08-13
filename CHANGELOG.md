# Changelog

## Unreleased

- Added a deterministic, public-data-calibrated port realtime simulator with a
  two-second SSE stream, ten operational domains, 153 canonical fields, five
  causal scenarios, and 168 equipment objects. All simulator values are marked
  as non-site engineering simulation.
- Added a replacement-ready `port-realtime.v1` telemetry contract, provenance
  hashes, physical/data-quality gates, scenario evidence, and compatibility with
  the existing `port-ops.v1` application interfaces.
- Added two-distinct-person approval, simulator-state execution, immutable audit
  events, and rollback. Physical dispatch and production authority remain
  disabled until site admission is independently completed.
- Expanded the same-architecture local LoRA profile to Rank 96 with
  104,595,456 trainable adapter parameters, source-isolated v3 supervision,
  held-out-question exclusion, PEFT and GGUF artifacts, and before/after
  validation/test loss evidence.
- Added a BEIR-aligned retrieval, RAGAS-concept-aligned deterministic, and
  MLPerf-style latency benchmark for maritime operations, evidence boundaries,
  and daily workforce questions; these are local engineering measurements, not
  official benchmark submissions.
- Added role-aware daily-life guidance for vessel, pilotage, control-room,
  terminal, gate, yard, and maintenance personnel, plus continuous UI progress
  messages and stable typewriter rendering.
- Added exact-index fast routing and deterministic live/regulatory boundary
  routing so evidence-complete answers avoid redundant generation while
  unsupported high-risk facts are not invented; every answer path now retains
  a configurable minimum three-second visible review window before first output.
- Cleared successfully submitted chat input immediately and moved the hero
  speech-bubble tail to the avatar-facing right side.
- Added an Apache-2.0 4B Q4_K_M local generation base with a pinned
  revision, byte count, SHA-256 receipt, llama.cpp lifecycle, and automatic
  strict-evidence fallback.
- Added source-isolated, evaluation-excluding LoRA SFT dataset construction
  and a real local 1.7B PEFT training/export path for the Intel 16GB
  development machine; its adapter is explicitly incompatible with the 4B
  high-quality inference profile.
- Distinguished local-device generation from remote data egress in the model
  gateway and retained post-generation citation, claim-alignment, and numeric
  integrity gates.
- Added a pinned 0.6B-Embedding Q8_0 service and content-hash-bound dense
  index, blended with the existing Sparse/BM25 retrieval and safe fallback.

All notable changes are documented here. The project follows semantic versioning once tagged releases begin.

## [0.4.0] - 2026-07-26

### Added

- Decision-readiness responses with explicit risk, blockers, next actions, and human-confirmation requirements.
- Conservative supporting-evidence conflict detection for opposite legal-status language and source version/hash divergence, plus freshness assessment.
- A 30-case v3 decision-assurance benchmark; the three fixed benchmark versions now total 150 cases.
- Deterministic claim–evidence lexical alignment and numeric/date/value integrity checks that block valid-looking but unsupported citations.
- A 20-case v4 alignment benchmark; the four fixed benchmark versions now total 170 cases.
- Four daily-operations knowledge packs covering energy peak management, vessel/berth productivity, yard/gate/equipment flow, and shift/customer/system coordination.
- Colloquial daily-query expansion, business-object clarification for vague action questions, domain-specific follow-ups, and an actionable peak-shaving response sequence.
- A 60-case v5 daily-operations benchmark across six frontline categories plus three clarification/live-data boundary checks; the five fixed benchmark versions now total 230 cases.
- A 15-domain by 26-form port-question universe with 390 intent cells, 780 formal/daily matrix prompts, and 1,997 indexed or derived utterances.
- Five internal operational packs for decarbonization, safety/security/environment, commercial/intermodal/special cargo, management/KPI/systems, and navigation/weather/engineering.
- A 30-case v6 domain benchmark plus five clarification, live-data, and official-full-text boundaries; the six fixed benchmark versions now total 260 cases.
- History-aware standalone-question rewriting, auditable query decomposition, per-subquestion evidence coverage, and post-answer citation validation.
- A 60-case v2 assistant challenge set covering dialogue, compound questions, partial refusal, citation boundaries, prompt injection, and live-data failure closure.
- Eight official source directories or summaries covering U.S., EU, U.K., Australian, Japanese, Rotterdam, Paris MoU, and Tokyo MoU entry points.
- A 409,887-row UCI large-scale energy benchmark and a measured NOAA AIS port-traffic scenario, each with fixed provenance, transformations, licensing notice, and SHA-256.
- A `port_operations` environment with 11 observations, five capacity actions, a safety-constrained objective, port profiles, factor coverage, and international-port integration fields.
- A three-dataset, three-seed benchmark for four tabular RL algorithms and the PID control baseline, including tracked legacy and selected-run evidence bundles.
- A one-screen training center connecting the evidence ledger, algorithm matrix, Xiaoyi training advisor, environment contract, system linkage, and configuration actions.
- Port RL landing, data-contract, resume-claim, and public-data documentation.

### Changed

- Markdown chunks now inherit their document-level title, preventing generic section names from displacing the actual maritime topic after knowledge expansion.
- Single-answer citations now preserve the actual evidence index, and answer evidence exposes the complete bounded registered chunk used by the composer.
- Evidence-policy release gates now require 100% jurisdiction, temporal-applicability, unsupported-answer, and live-data-boundary results.
- The registered knowledge snapshot expands from 112 documents / 708 chunks / 60 official sources to 120 / 740 / 68.
- The registered knowledge snapshot further expands to 124 documents / 807 chunks / 68 official sources, with internal operational guidance kept distinct from official evidence and live instructions.
- The registered knowledge snapshot further expands to 129 documents / 882 chunks / 68 official sources, with 61 internal guidance documents kept distinct from official evidence and live instructions.
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
