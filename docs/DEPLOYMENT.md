# Deployment guide

This repository is safe by default for local evaluation. A public or port deployment requires explicit production configuration and infrastructure owned by the deployer.

## Local evaluation

```bash
cp .env.example .env
bash run.sh
```

Open <http://127.0.0.1:8010>. Local mode deliberately accepts unverified development identity headers and must not be exposed to an untrusted network.

## Container

```bash
docker compose build
docker compose up
```

The supplied Compose profile binds only to loopback, drops Linux capabilities, and uses a read-only root filesystem. Named volumes persist the runtime database (`xiaoyi-runtime`), RL artifacts (`xiaoyi-rl-runs`), and pending knowledge intake (`xiaoyi-kb-pending`) without making the governed knowledge and public-data image layer writable. Back up all three volumes before upgrades; rebuild the image for approved knowledge-source changes.

## Production configuration

Generate a random secret with a platform secret manager; do not commit it. The service refuses production startup when required controls are missing.

```dotenv
XIAOYI_ENV=production
XIAOYI_SECURITY_MODE=jwt
XIAOYI_JWT_SECRET=<at-least-32-random-bytes-from-secret-manager>
XIAOYI_JWT_ISSUER=xiaoyi-ai
XIAOYI_JWT_AUDIENCE=xiaoyi-api
XIAOYI_ALLOWED_HOSTS=assistant.example.com
XIAOYI_CORS_ORIGINS=https://assistant.example.com
XIAOYI_DOCS_ENABLED=false
```

Create a short-lived local HS256 token for controlled testing:

```bash
python scripts/create_access_token.py --actor operator-001 --role operator --minutes 60
```

For an organization, issue tokens through the organization identity platform or replace the verifier with validated OIDC/JWKS support. Put the API behind TLS termination, a web application firewall or gateway, network allowlists, centralized secret management, and centralized logs. Rotate signing keys and tokens according to the organization policy.

## Model gateway and privacy

The default `local_rules` provider never sends content outside the service. To use an OpenAI-compatible endpoint, configure the following and complete a data-processing review first:

```dotenv
XIAOYI_MODEL_PROVIDER=openai_compatible
XIAOYI_MODEL_BASE_URL=https://model-gateway.example.com/v1
XIAOYI_MODEL_NAME=<approved-model>
XIAOYI_MODEL_API_KEY=<secret-manager-reference>
XIAOYI_MODEL_EXTERNAL_DATA_ALLOWED=true
```

Only grounded, non-sandbox answers pass the external model gate. Failures, an open circuit, missing authorization, or insufficient evidence return the local evidence-controlled answer.

## Health and observability

- `GET /health/live`: process liveness only.
- `GET /health/ready`: storage, index, RL dataset, model, and deployment-configuration readiness; returns 503 when blocked.
- `GET /metrics`: Prometheus-format request count, error, latency, in-flight, and uptime metrics. Restrict it to the monitoring network in production.
- Every response includes `X-Request-ID`; application request logs are structured JSON.

## Scaling and recovery boundary

The built-in SQLite store and in-process RL workers are intentionally a single-instance baseline. Keep one application worker. Before horizontal scaling, replace them with a shared transactional database, durable queue, distributed rate limiter/idempotency store, object storage for model artifacts, and coordinated migration/backup procedures.

On restart, unfinished UI tasks are marked cancelled and unfinished automation plans are marked failed. They are never silently resumed. Restore from a tested backup, run `/health/ready`, then perform an operator-approved replay.

## Port integration gate

Keep `XIAOYI_PORT_DATA_MODE=operations_sandbox` until a read-only `port-ops.v1` gateway returns all metadata required by `data/contracts/port_site_admission_v1.json` and passes freshness, completeness, duplication, ordering, physical-constraint, feature-coverage and PSI drift checks. `live_data_verified=true` alone is insufficient. Production writes remain disabled until field mapping, calibration, shadow operation, dual approval, rollback drill, OT/IT allowlisting and site acceptance all have signed evidence. See [PORT_CONNECTOR_INTEGRATION.md](PORT_CONNECTOR_INTEGRATION.md).
