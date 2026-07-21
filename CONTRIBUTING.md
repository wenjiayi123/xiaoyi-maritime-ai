# 参与贡献 · Contributing

感谢你帮助小懿变得更可信、更可复现。Thank you for helping Xiaoyi become more trustworthy and reproducible.

## 本地开发 · Local development

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.lock
python scripts/build_index.py
python -m pytest -q
bash run.sh
```

打开 / Open <http://127.0.0.1:8010>。

## 贡献约束 · Contribution invariants

- 不得把合成、预览或客户端提交的数据描述为生产事实。 / Never present synthetic, preview, or client-supplied values as production facts.
- RL 修改必须保留时间顺序的训练/验证/测试隔离、确定性种子、真实进度计数和模型/数据哈希。 / RL changes must retain chronological train/validation/test isolation, deterministic seeds, real progress counters, and model/data hashes.
- 训练路径不得渲染；只有训练完成后才能在保留测试集生成轨迹。 / Training must not render; held-out traces may be generated only after training completes.
- 新数据集必须登记来源 URL、许可证、引用、转换记录和 SHA-256。 / New datasets require a source URL, license, citation, transformation record, and SHA-256 provenance.
- 新港航来源必须登记机构、验证级别、内容范围、辖区、复核日期和发布方条款。 / New maritime sources require institution, verification level, content scope, jurisdiction, review date, and publisher terms.
- 生产动作必须失败关闭，并由独立、当前、可审计的操作员授权。 / Production actions must fail closed and require separate, current, auditable operator authorization.

## 提交前验证 · Before a pull request

```bash
python -m compileall -q app scripts
python -m ruff check app scripts tests
python scripts/release_check.py
python -m pip check
node --check web/app.js
python -m pytest -q
```

每个行为变化都应补充或更新测试。外部集成在测试中保持 `offline`，只使用显式 fake 验证契约和失败边界。

Add or update tests for every behavioral change. Keep external integrations `offline` in tests; use explicit fakes only for contract and failure-boundary validation.

## Pull request 说明 · Pull request notes

说明用户问题、实现、数据与安全边界、验证证据以及是否影响部署。UI 变化请附可复现截图；数据贡献请附许可证与血缘记录。不要提交凭据、私有港口数据、内部主机名或本机绝对路径。

Describe the user problem, implementation, data and security boundaries, verification evidence, and deployment impact. Include reproducible screenshots for UI work and license/provenance records for data contributions. Never submit credentials, private port data, internal hostnames, or local absolute paths.
