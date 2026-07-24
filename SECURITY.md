# Security policy

## Supported version

Security fixes target the latest `main` branch.

## Reporting a vulnerability

Do not open a public issue containing credentials, private port data, internal
hostnames or an exploitable security report. After publication, use the
repository's private GitHub Security Advisory form. Until that channel is
configured, contact the repository owner privately. Include the affected route,
impact, reproduction steps and a minimal proof of concept. Do not test against
a real port without written authorization.

## Deployment boundary

The default configuration is for local development:

- cross-system capabilities and port connectors start offline;
- production writes are disabled;
- local identity headers are visibly unverified and only for loopback development;
- the bundled operational dashboard is explicitly synthetic;
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
