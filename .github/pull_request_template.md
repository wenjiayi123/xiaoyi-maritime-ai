## 变更 · Change

说明行为变化、用户问题以及为何需要。Describe the behavior, user problem, and why it is needed.

## 证据与安全边界 · Evidence and safety boundary

- [ ] Synthetic, preview, and production data are visibly distinguished.
- [ ] New datasets or knowledge sources include license, provenance, and SHA-256 where applicable.
- [ ] Production actions remain fail-closed and human-confirmed.
- [ ] No credentials, private port data, local paths, or generated runtime state are included.

## 验证 · Verification

- [ ] `python -m ruff check app scripts tests`
- [ ] `python scripts/release_check.py`
- [ ] `python -m pytest -q`
- [ ] UI behavior checked if the web application changed.
