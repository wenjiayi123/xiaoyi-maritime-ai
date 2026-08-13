# Security policy

## Supported versions

| Version | Supported |
| --- | --- |
| Latest `main` / latest GitHub release | Yes |
| Older commits and local forks | No |

## Reporting a vulnerability

Do not open a public issue containing credentials, private port data, internal
hostnames or an exploitable security report. Use the repository's
[private GitHub Security Advisory form](https://github.com/wenjiayi123/xiaoyi-maritime-ai/security/advisories/new).
Include the affected route, impact, reproduction steps and a minimal proof of
concept. Do not test against a real port without written authorization.

The maintainer aims to acknowledge a complete report within three business
days, provide an initial severity assessment within seven business days, and
coordinate a fix and disclosure within 90 days. Critical actively exploited
issues are handled sooner; incomplete reports or upstream fixes can change the
timeline. The reporter will receive status updates at material milestones.

Please keep the report confidential until a fix is available. The maintainer
will credit reporters who request attribution and will publish a GitHub
Security Advisory when disclosure is appropriate.

## Deployment boundary

The default configuration is for local development:

- cross-system capabilities and port connectors start offline;
- production writes are disabled;
- local identity headers are visibly unverified and only for loopback development;
- the bundled operational dashboard is a clearly labelled public-data-calibrated
  simulator, not connected port telemetry;
- the bundled RL dataset is public building-energy data, not port data.

Production mode enforces signed JWTs, role permissions, explicit hosts and CORS
origins, request-size limits, rate limiting, idempotency, security headers and
deep readiness checks. Deployers must still supply TLS, organizational SSO or
token issuance, secret management, network allowlists, centralized monitoring,
tested backups, a durable distributed job queue for multi-instance operation,
and a reviewed production data gateway. Never expose local launcher routes to
non-administrator roles or an untrusted network.

See `docs/DEPLOYMENT.md` for the complete production boundary and key rotation,
retention, recovery and model-data egress requirements.
