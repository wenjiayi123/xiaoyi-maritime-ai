# Frozen research inputs

`registry-evidence-20261102.zip` contains 56 existing, immutable research JSON
reports/selections and small numeric-policy NPZ files referenced by the repository's
evidence registries. It excludes databases, sessions, credentials and language-model
weights. The source-relative paths and SHA-256 values are recorded in `manifest.json`.

Run `python3 scripts/restore_research_evidence.py` after cloning. It validates the
archive and every entry before restoring the original research paths; conflicting
local files cause an error and are never overwritten. CI and the container build
use the same command. Historical failed evidence remains failed.

The bulk PortWatch source export and external Malacca TypeScript planner remain
separate dependencies. Their integration checks explicitly skip when absent;
they are not reported as passing. See `docs/GITHUB_RELEASE_20261102.md`.
