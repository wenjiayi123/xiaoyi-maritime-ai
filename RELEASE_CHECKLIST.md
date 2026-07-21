# 发布清单 · Release checklist

本清单用于维护者发布版本；站点部署仍须执行 `docs/DEPLOYMENT.md` 中的生产验收。

This checklist is for maintainers releasing the software. A site deployment must additionally complete the production acceptance work in `docs/DEPLOYMENT.md`.

## 代码与可复现性 · Code and reproducibility

- [ ] `VERSION`、`app/config.py`、`CITATION.cff`、容器标签和变更日志一致。 / Version markers and changelog agree.
- [ ] 锁定依赖经过全套测试，`python -m pip check` 通过。 / Locked dependencies pass the full suite and `pip check`.
- [ ] `python -m ruff check app scripts tests` 与 `node --check web/app.js` 通过。 / Python lint and JavaScript syntax checks pass.
- [ ] 公开 RL 数据的来源、许可证、原始/派生 SHA-256 与行数验证通过。 / Public RL provenance, license, hashes, and row count verify.
- [ ] 知识来源登记数量、KB 文件数量和覆盖矩阵结构一致。 / Registry counts, KB files, and authority matrix are consistent.

## 安全与数据边界 · Security and data boundaries

- [ ] 没有 `.env`、凭据、私钥、运行数据库、日志、本机路径或私有港口数据。 / No environment file, credential, private key, runtime database, log, local path, or private port data is tracked.
- [ ] 默认连接器和跨系统能力仍为 `offline`。 / Connectors and cross-system capabilities remain offline by default.
- [ ] 运营 UI 明确标示 `SANDBOX`，公开 RL 数据明确标示非港口基准。 / The operations UI says `SANDBOX`, and public RL data says non-port benchmark.
- [ ] 生产模式缺少 JWT、Host 或 CORS 门禁时失败关闭。 / Production fails closed when JWT, Host, or CORS gates are missing.
- [ ] 高风险动作仍需要当前人工确认；没有新增无人值守生产写路径。 / High-risk actions retain current human confirmation and no unattended production-write path was added.

## 发布证据 · Release evidence

- [ ] `python scripts/release_check.py` 通过。 / Release check passes.
- [ ] `python -m pytest -q` 全部通过。 / The complete test suite passes.
- [ ] 本地 Web 主控台、RL 实验室和系统就绪页完成视觉检查，控制台无错误。 / Console, RL lab, and readiness UI pass visual inspection with no console errors.
- [ ] README 中的测试数、文档数、片段数、API 数和截图来自本次候选版本。 / README counts and screenshots come from the current candidate.
- [ ] GitHub Actions 通过，发布说明包含迁移、安全与数据边界变化。 / GitHub Actions passes, and release notes cover migration, security, and data-boundary changes.
