## Change

Describe the behavior and why it is needed.

## Evidence and safety boundary

- [ ] Synthetic, preview, and production data are visibly distinguished.
- [ ] New datasets or knowledge sources include license, provenance, and SHA-256 where applicable.
- [ ] Production actions remain fail-closed and human-confirmed.
- [ ] No credentials, private port data, local paths, or generated runtime state are included.

## Verification

- [ ] `python scripts/release_check.py`
- [ ] `python -m pytest -q`
- [ ] UI behavior checked if the web application changed.

