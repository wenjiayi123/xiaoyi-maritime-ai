# Software bill of materials

`xiaoyi-python-lock-snapshot.cdx.json` is a deterministic CycloneDX 1.6 snapshot
of the exact Python versions in `requirements.lock` and
`requirements-dev.lock`. It separates runtime packages from development-only
packages and records both lockfile SHA-256 values. The lock format does not
encode parent-child dependency edges, so the file explicitly declares a flat
snapshot instead of inventing a transitive graph.

Rebuild and verify locally:

```bash
python scripts/build_sbom.py build
python scripts/build_sbom.py verify
```

The `sbom` GitHub workflow additionally uses Syft to scan the checked-out
repository and publishes an SPDX JSON workflow artifact. No release asset is
published automatically.
