# Contributing

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements-dev.lock
python scripts/build_index.py
pytest -q
```

Start the app with `bash run.sh`, then open <http://127.0.0.1:8010>.

## Change requirements

- Do not present synthetic, preview or client-supplied values as production
  facts.
- RL changes must retain explicit train/validation/test isolation, deterministic
  seeds, real progress counters and model/data hashes.
- Training code must not render the environment. Test rendering is allowed only
  after training completes.
- New datasets need a source URL, license, citation, transformation record and
  SHA-256 provenance.
- New maritime sources need a registry entry with institution, verification
  level, content scope, jurisdictions, review date and publisher terms.
- Production actions must remain fail-closed and require a separate, current
  operator authorization.

Before opening a pull request, run `python scripts/release_check.py` and
`python -m pytest -q`. Add or update tests for every behavioral change. Keep external integrations
offline in tests; use explicit fakes only to validate contracts and failure
boundaries.
