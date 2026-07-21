# 安全策略 · Security policy

## 支持版本 · Supported version

安全修复面向最新 `main` 分支。Security fixes target the latest `main` branch.

## 漏洞披露 · Vulnerability disclosure

请勿在公开 Issue 中提交凭据、私有港口数据、内部主机名或可利用漏洞细节。仓库公开后，请使用 GitHub Private Security Advisory；该渠道启用前，请通过仓库所有者的私有渠道联系。报告应包含受影响路由、影响、复现步骤和最小化 PoC。未经书面授权，不得对真实港口或外部系统进行测试。

Do not place credentials, private port data, internal hostnames, or exploitable details in a public issue. After publication, use GitHub Private Security Advisories; until that channel is enabled, contact the repository owner privately. Include the affected route, impact, reproduction steps, and a minimal proof of concept. Never test a real port or external system without written authorization.

## 默认安全边界 · Secure defaults

- 连接器和跨系统能力默认 `offline`。 / Connectors and cross-system capabilities default to `offline`.
- 生产写操作默认禁用。 / Production writes are disabled by default.
- 本地身份头未验证，仅允许回环开发。 / Local identity headers are unverified and only for loopback development.
- 运营看板数据明确为合成沙箱。 / Operational dashboard data is explicitly synthetic sandbox data.
- 内置 RL 数据是公开建筑能源数据，不是港口数据。 / The bundled RL dataset is public building-energy data, not port data.

生产模式强制签名 JWT、角色权限、显式 Host/CORS、请求体限制、限流、幂等、安全响应头和深度就绪检查。部署方仍必须提供 TLS、组织 SSO/OIDC 或令牌签发、集中密钥管理、网络白名单、监控、经演练备份，以及多实例所需的共享状态和持久任务队列。

Production mode enforces signed JWTs, role permissions, explicit Host/CORS policy, body limits, rate limiting, idempotency, security headers, and deep readiness checks. Deployers must still provide TLS, organizational SSO/OIDC or token issuance, centralized secret management, network allowlists, monitoring, tested backups, and shared state plus a durable job queue for multiple instances.

完整要求见 [部署指南](docs/DEPLOYMENT.md)。See the [deployment guide](docs/DEPLOYMENT.md) for the complete boundary.
