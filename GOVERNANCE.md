# 项目治理 · Project governance

仓库所有者负责版本与安全修复。变更通过评审 Pull Request 合入，并要求 CI 通过。

The repository owner maintains releases and security fixes. Changes are accepted through reviewed pull requests with passing CI.

维护者可以拒绝模糊合成/生产边界、移除证据拒答、削弱人工确认、引入无许可数据或宣称不可验证完整性的变更。数据与知识来源贡献必须包含血缘和发布方条款；安全敏感变更需要聚焦测试与明确部署边界。

Maintainers may reject changes that blur synthetic and production data, remove evidence refusal behavior, weaken human confirmation, introduce unlicensed data, or make unverifiable completeness claims. Dataset and knowledge-source contributions require provenance and publisher terms. Security-sensitive changes require focused tests and a documented deployment boundary.

在多位维护者正式加入前，项目采用仁慈维护者模式。未来维护者应基于持续、建设性贡献，安全判断力，以及对证据和运营安全边界的尊重进行选择。

Until multiple maintainers are named, the project uses a benevolent-maintainer model. Future maintainers should be selected based on sustained constructive contributions, security judgment, and respect for evidence and operational safety.
