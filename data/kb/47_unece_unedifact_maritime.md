# UNECE UN/EDIFACT 港航电子数据交换目录

## 来源定位

- 发布机构：United Nations Economic Commission for Europe（UNECE / UN/CEFACT）
- 官方目录：https://unece.org/trade/uncefact/unedifact/download
- 消息目录示例：https://service.unece.org/trade/untdid/d18b/trmd/trmdi1.htm
- 核验日期：2026-07-11

## 已核验事实

- UN/EDIFACT 是用于行政、商业和运输领域电子数据交换的联合国目录体系。
- UNECE 官方下载目录按年份和发布版管理，例如 D.24A、D.23A、D.22A/D.22B；接入时必须记录目录版本，不能只记录消息名称。
- 港航相关消息类型包括 BAPLIE（船舶积载位置）、BERMAN（泊位管理）、CALINF（船舶挂靠信息）等；具体字段、段组与代码应以目标目录版本及实施指南为准。

## 接口落地提示

真实接入需要保存 interchange、message reference、sender/receiver、directory version、message type、功能代码、ACK/APERAK 回执以及原始报文哈希。重发必须使用幂等键，解析失败不能静默丢弃。不同码头或船公司采用的目录版本和 SMDG 实施指南可能不同，必须逐方建立映射和一致性测试。
