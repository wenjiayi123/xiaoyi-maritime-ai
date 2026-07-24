# Architecture and trust boundaries

```text
Browser / API client
  -> request ID, body limit, rate limit, security headers
  -> JWT verification and role permission mapping (production)
  -> FastAPI domain routers
       -> local evidence-controlled answer engine
       -> optional privacy-gated model gateway
       -> operations / automation / RL services
       -> read-only port and capability connectors
  -> SQLite control-plane state and append-oriented audit hashes
  -> knowledge files, public RL data, and model artifacts
```

The browser is untrusted. Client-supplied actor names, roles, confirmations, progress values, and production flags do not establish authority. In JWT mode the verified subject and role replace client identity claims.

The local evidence composer is the default generation path. An external model can rewrite a grounded answer but cannot bypass retrieval refusal, sandbox-data isolation, or production action controls. Connector responses must satisfy their registered schema and verification flags before the UI can label them live.

The repository ships a single-node control plane. SQLite protects local durability, not distributed consensus. RL training uses bounded background workers and writes hashed artifacts; production-scale orchestration requires the queue and shared-state replacements listed in [DEPLOYMENT.md](DEPLOYMENT.md).

