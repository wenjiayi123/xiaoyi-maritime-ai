# DCSA Port Call Interface Standard 2.0

## 来源定位

- 发布机构：Digital Container Shipping Association（DCSA）
- 官方文档：https://reference.dcsa.org/content/standards/releases/port-call/v2-0-0/port-call-v2-0-0-purpose-and-scope
- 实施指南：https://reference.dcsa.org/content/standards/releases/port-call/v2-0-0/port-call-v2-0-0-implementation-guide
- 版本：2.0.0（官方变更记录日期 2025-12-18）
- 核验日期：2026-07-11

## 已核验事实

- DCSA Port Call 标准用于承运人、码头、港口主管机关及服务商之间交换港口挂靠运营信息。
- 标准覆盖靠泊计划、引航、拖轮、系泊、加油和其他港口服务协同，目标包括提高计划可预测性、减少等待和支持船舶航速优化。
- 2.0 实施指南描述事件发布方的 `GET /events` 和事件接收方的 `POST /events` 接口，并提供 OpenAPI 与一致性测试材料。
- 数据来源与所有权需要通过参与方角色明确区分，不能把不同主体的估计、请求、计划和实际时间混为同一状态。

## 接口落地提示

小懿连接器应保留事件原始发布方、事件时间、接收时间、版本、港口挂靠标识、时间类型和状态转换。读取可以自动化；修改计划、发布事件或代表参与方提交数据必须经过权限校验、幂等控制和人工确认。
