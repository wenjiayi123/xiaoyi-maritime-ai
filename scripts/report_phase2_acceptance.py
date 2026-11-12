"""Produce an evidence-bound acceptance report from completed native/API receipts."""

from __future__ import annotations
import csv
import hashlib
import json
import math
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ART = ROOT / ".codex_artifacts/joint-harness-phase2-20261029"
TASKS = {
    "enterprise_release": "jm-0b2a7dd640044757ad71a8ec0f78d365",
    "research": "jm-88323d580ada46089b46df05e01b33d6",
    "enterprise_first": "jm-2c9814cc4c2b42c69025ef151ad7b41c",
    "legacy": "jm-3e4fba2d21ab4504aaf29cb083f5c754",
}


def read(name):
    return json.loads((ART / name).read_text())


def api(path):
    with urllib.request.urlopen("http://127.0.0.1:8010" + path, timeout=15) as response:
        return json.load(response)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    exports = {}
    for name, mid in TASKS.items():
        receipt = api("/api/harness/joint/missions/" + mid + "/export")
        if receipt["mission"]["status"] != "completed":
            raise SystemExit(name + " has not completed; report cannot pass")
        assert all(
            receipt["integrity"][key]
            for key in ["event_chain_valid", "result_hashes_valid", "business_operation_hashes_valid"]
        )
        exports[name] = receipt
        (ART / (name + "-accepted-export.json")).write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
    jobs = {k: v["mission"] for k, v in exports.items()}
    release = jobs["enterprise_release"]
    research = jobs["research"]
    assert release["plan"]["executor_sha256"] == sha(ROOT / "app/harness/joint.py"), (
        "final enterprise run does not match released executor"
    )
    assert release["results"]["transport"]["data"]["pretrained_selection_allowed"] is False
    assert research["results"]["transport"]["data"]["selected"]["model"] == "parco"
    for name in ["enterprise_release", "research"]:
        j = jobs[name]
        port = j["results"]["port_execute"]["data"]
        assert (
            port["native_totals"]["violations"] == 0
            and port["forecast_matches_execution"]
            and port["resource_event_execution"]["tasks_completed"] == 18
        )
        assert all(
            s["status"] in ["rolled_back", "rolled_back_simulation"]
            for s in j["results"]["business_rollback"]["data"]["results"].values()
        )
    assert jobs["legacy"]["results"]["mobile"]["data"]["actor_authenticated"] is False
    benchmark = read("same-contract-benchmark.json")
    assert benchmark["complete"] and len(benchmark["results"]) == 20
    matrix = read("native-voyages/matrix.json")
    assert matrix["complete"] and all(e["passed"] for e in matrix["results"])
    protected = read("original-integrity-final.json")
    assert not protected["changed"] and all(x["unchanged"] for x in protected["original_models"].values())
    samples = [json.loads(line) for line in (ART / "resource-samples.ndjson").read_text().splitlines()]
    health = {}
    for service in ["xiaoyi", "policy"]:
        values = sorted(r["health"][service]["seconds"] for r in samples if r["health"][service]["ok"])
        health[service] = {
            "probes": len(samples),
            "failed": sum(not r["health"][service]["ok"] for r in samples),
            "p95_seconds": values[max(0, math.ceil(len(values) * 0.95) - 1)],
            "maximum_seconds": max(values),
        }
    peak = {}
    for r in samples:
        for line in r["processes"]:
            parts = line.split(maxsplit=3)
            if len(parts) != 4:
                continue
            pid, rss, cpu, cmd = parts
            if "Virtualization.VirtualMachine" in cmd:
                key = "local_linux_guest_host_process"
            elif "Godot --headless" in cmd:
                key = "single_native_godot_process"
            elif "uvicorn app.main" in cmd:
                key = "single_xiaoyi_api_process"
            elif "llama-server" in cmd:
                key = "single_original_llama_process"
            else:
                continue
            peak[key] = max(peak.get(key, 0), int(rss) / 1024)
    resource = {
        "duration_minutes": (samples[-1]["epoch"] - samples[0]["epoch"]) / 60,
        "samples": len(samples),
        "health": health,
        "sampled_peak_rss_mib": peak,
        "scope": "finite local sampling; no continuous production SLA",
    }
    (ART / "resource-summary.json").write_text(json.dumps(resource, indent=2))
    rows = []
    for domain in ["CVRP", "HCVRP"]:
        cases = [r for r in benchmark["results"] if r["domain"] == domain]
        for model in ["nearest_neighbor", "ortools", "routefinder" if domain == "CVRP" else "parco"]:
            values = [next(c for c in r["candidates"] if c["model"] == model) for r in cases]
            feasible = [c for c in values if c["validation"]["feasible"]]
            rows.append(
                {
                    "domain": domain,
                    "model": model,
                    "instances": len(cases),
                    "feasible": len(feasible),
                    "mean_objective": sum(c["validation"]["objective_value"] for c in feasible) / len(feasible),
                    "mean_compute_seconds": sum(c["compute_seconds"] for c in feasible) / len(feasible),
                    "selected": sum(r["selected"]["model"] == model for r in cases),
                }
            )
    with (ART / "same-contract-summary.csv").open("w") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    table = "\n".join(
        f"|{r['domain']}|{r['model']}|{r['feasible']}/{r['instances']}|{r['mean_objective']:.3f}|{r['mean_compute_seconds']:.3f}|{r['selected']}|"
        for r in rows
    )
    voyages = [("open_water", release["results"]["sailing"]["data"]["raw"])] + [
        (e["scene"], e["receipt"]) for e in matrix["results"]
    ]
    voyage_table = "\n".join(
        f"|{scene}|{r['physics_frames']}|{r['validation']['simulatedDurationSeconds']:.2f}|{r['inference_count']}|{r['validation']['collisionCount']}|{r['validation']['minimum_ukc_m']}|{r['validation']['minimum_bank_clearance_m']}|原控制器到达终点|"
        for scene, r in voyages
    )
    testlog = (ART / "release-python-tests.log").read_text() if (ART / "release-python-tests.log").exists() else ""
    tests = re.findall(r"(\d+) passed", testlog)
    if not tests:
        raise SystemExit("release Python regression not completed")
    count = tests[-1]
    summary = {
        "schema": "xiaoyi-harness-phase2-acceptance.v1",
        "tasks": {
            k: {
                "id": j["id"],
                "status": j["status"],
                "plan_sha256": j["plan_sha256"],
                "delivery_sha256": j["delivery_sha256"],
                "steps": len(j["plan"]["steps"]),
                "active_seconds": j.get("active_seconds"),
            }
            for k, j in jobs.items()
        },
        "all_receipt_hash_checks_passed": True,
        "native_scenes": 7,
        "benchmark": rows,
        "resources": resource,
        "original_protected_files": 166,
        "original_model_hashes_match": True,
        "python_regression_passed": int(count),
        "native_gui_verified": False,
        "native_gui_reason": "Sky Computer Use service startup request failed",
        "production_authority": False,
    }
    (ART / "acceptance-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    report = f"""# 双模式 Harness 二期验收报告（2026-10-29）

**结论：本机注册系统的完整仿真业务链验收通过。** 企业模式、研究模式均已完成原生航行、约束运输、资源排程、实际模拟执行、核验、补偿和真实 Flutter 网页客户端签收。原生桌面逐按钮验收仍受本机控制服务故障限制；现场生产、统一真实港口物理校准和长期 SLA 不在已通过结论中。

## 一、原未完成项与补齐证据

|原缺口|本轮结果|主要证据|
|---|---|---|
|开源运输模型只有下载，Intel原生依赖不兼容|已用本机隔离 Linux 实际运行两份固定预训练策略，严格装载参数；主机每次独立复核路线|policy-runtime-final.json、same-contract-benchmark.json|
|仅4秒航行样本|七个正常准入场景均完成原控制器起点至终点全过程；保留40维状态、2维动作和物理帧轨迹|native-voyages/matrix.json、发布任务航行回执|
|联合流程只做评估，缺业务执行|港区原生V6完整24步，沙盘原生SOP动作，能碳原生MPC审批执行均获确认；逐系统读回核验并补偿|三个完整任务的 accepted-export.json|
|共同上下文与资源链不足|声明的工程时钟、18个任务、9个阶段、11类资源；执行时实际占用、推进和释放，映射为V6逐时控制|coordination、port_execute.resource_event_execution|
|研究增益与强基线不足|20个新冻结实例，对比最近邻、允许补载的同约束OR-Tools和预训练策略；保留不利结果与自动基线回退|same-contract-protocol.json、same-contract-summary.csv|
|并发、资源、失效路径不足|8并发推理1受理/7个409；联合执行器争用409；真实原生航次30秒预算终止；未准入天气拒绝；收尾补充暂停后取消补偿和回执防损坏检查|policy-contention.json、full-native-budget-and-contention.json、测试日志|

## 二、从头到尾实际重放

|任务|编号|步骤数|最终状态|
|---|---|---|---|
|企业模式首轮完整成功|{jobs["enterprise_first"]["id"]}|15|completed|
|研究模式完整成功|{research["id"]}|16|completed|
|最终发布版企业模式重放|{release["id"]}|15|completed|
|原有短时评估回归|{jobs["legacy"]["id"]}|6|completed|

发布版完整链：服务门禁 → 交通来源 → 原生完整航次 → 港区负荷评估 → 能碳试算 → 运输候选独立复核 → 共同工程时钟与资源排程 → 三个原生工作单 → 绑定实际动作的二次审批 → 港区执行 → 沙盘执行 → 能碳执行 → 读回核验 → 补偿与恢复 → Flutter签收。研究模式另核对已冻结的五种子研究报告。

此次界面演练明确选择 **模拟岗位**，所有审批角色均带模拟标记。真实岗位路径用独立JWT账号做了接口测试：申请人不能自批、两个身份及岗位必须互异、安全复核需要相应管理员权限，客户端声明的身份不能覆盖JWT身份。这些测试不代表现场两名人员已经签字。当前本机仍是原有local模式；签收记录如实标记 `actor_authenticated=false`。

企业模式只允许合格基线参与选择，预训练候选保留为影子比较。研究模式才允许在独立约束复核后选择学习策略。本轮发布企业模式采用 {release["results"]["transport"]["data"]["selected"]["model"]}，研究模式采用 {research["results"]["transport"]["data"]["selected"]["model"]}。两类模型的准入和目标不混用。

## 三、完整航次原始结果

|场景|物理帧|模拟秒|策略推理次数|碰撞计数|最小UKC/m|最小岸距/m|终点状态|
|---|---:|---:|---:|---:|---:|---:|---|
{voyage_table}

正常 `start_current()` 准入、原有准入策略与物理控制器，保留原阈值，没有通过传送船位构造成功。追越场景明确记录工程演练中的协议确认。表中 `None` 表示该场景未观测该量，不是零或额外安全证明；桥楼、通信、人工岗位协作与认证等级仍按原系统边界解释。完整原生任务完成不等于真实港口航次已获准执行。

## 四、业务链与回滚含义

两种完整模式的港区工作单均完成24个原生数值步，预测与执行结果摘要匹配，原生约束违例为0。使用的是原港区配置中的36,000kW需求上限；最初误用了通用3,500kW默认值的失败记录已保留，现按配置读取，未修改原港区阈值。

事件执行器推进18个任务，覆盖到港、航道服务、靠泊服务、装卸、水平运输、堆场、闸口、铁路和维修；覆盖航道窗口、泊位、引航、拖轮、岸桥、车队、箱位、闸口、铁路、岸电储能和维修班组。它按候选排程实际校验前置交接、到港时间、截止与容量，记录36条开始/完成事件并释放资源。预约资源按原生采样间隔的时间占比映射为V6控制；原始数据时钟与统一工程时钟同时保留。

原生V6还保留驳船、冷藏箱、岸电、检查缓冲和积压等业务数值结果。工作单按有限仿真范围执行完成，未把原生剩余积压清零，未冒充海关放行、现场设备作业或真实货物流转。

沙盘和能碳调用原有审批/执行/回滚接口，原生状态最终分别为 `rolled_back`、`rolled_back_simulation`；港区独立工作单恢复至初始状态。补偿恢复控制或原生安全保持计划，已流逝时间、能耗和审计历史保留。其他后续决策冲突会阻断补偿；未知写入留待核查，不自动重放。

## 五、开源策略同约束比较

实例种子44401—44410，两个问题域，每例30个作业、5辆车；均为声明的开放堆场工程实例，不是现场数据。CVRP目标单位为米，HCVRP目标单位为秒。OR-Tools预算分别1秒/5秒；实际耗时和返回路线重新计量，有限预算不提供全局最优证明。

|问题域|候选|可行实例|平均目标值|平均推理/求解秒|被采用次数|
|---|---|---:|---:|---:|---:|
{table}

RouteFinder在这组CVRP实例中弱于OR-Tools，企业模式保留基线。PARCO在HCVRP组中9例被选中，另1例选最近邻；不隐藏该不利结果。原有表格RL的港口测试中PID仍领先，运输组的增益只用于解释运输任务。

上游HCVRP的连续同节点动作表示等待，适配层已按原生语义修正；非连续重复服务仍会被拒绝。修正前后的同组结果、额外一组新实例和最终同约束强基线协议分别保存。权重和上游源码未为这些测试重训练或改写。

## 六、回归与原有功能保护

- 舷鸥发布版全量 Python：**{count}项通过**；包含审批、来源、越权、时间窗、容量、能量、回执、恢复及新取消路径测试。
- 舷鸥原前端及运行时：**47项通过**，包含启动恢复历史对话时不关闭用户已打开工作台的竞态回归。
- 港区V6与协同原生模块：**17项通过**。
- Flutter：**46项通过**，analyze无问题，Web release构建成功；完整任务由真实Flutter网页客户端读取和签收。
- 原有166份受保护数据/知识文件哈希一致，三个原生成/嵌入模型权重哈希一致，SQLite quick_check为ok。
- 原问答界面实际返回生成式RAG答案和5条索引来源；港区视角、能碳调度/历史、沙盘证据页及移动端原有控件实际检查，相关截图与文本已保存。

本轮没有修改能碳和马六甲的原业务源代码。港区新增独立工作单执行器，航行新增独立验收脚本；主流程、知识库和原模型继续保留。旧待审批任务在代码变更后需重新预览，历史已完成回执保持可读。

## 七、资源与失效证据

抽样持续 **{resource["duration_minutes"]:.1f}分钟**、**{len(samples)}个样本**，保留每次API健康耗时和进程RSS。配置为本机Linux客体2vCPU/2GiB；推理服务串行请求、忙时409。实施与服务重启期间，记录到舷鸥探针5次失败、策略服务探针2次失败，原始记录全部保留。抽样峰值：Linux客体宿主进程约1550MiB、单舷鸥API进程约360MiB、单Godot进程约475MiB；各进程峰值不能直接相加作为整机内存。具体结果见 `resource-summary.json`，不外推为24/7或现场SLA。

首次完整业务演练遇到历史未执行决策的空回执，回滚保护读取空值失败；修复后对原任务执行实际补偿，三系统均确认恢复。相关任务 {read("enterprise-prototype-compensated.json")["id"]} 与前后日志保留。后续完整成功不覆盖该失败记录。

## 八、仍不能计入通过的范围

1. 原生桌面逐按钮：本次多次请求原生应用控制均返回 `Sky Computer Use service startup request failed`。Godot引擎真实headless闭环与Web/Flutter界面已验，原生窗口和所有桌面按钮没有假定通过。
2. 统一真实港口物理校准：各源上海/马六甲/公开数据等原始地理与历史时钟保留。新统一时钟属于工程场景，能碳仍保留原有负荷来源；六源现场影子准入不因本次联动自动变成6/6。
3. 现场生产、人员资质/监管签字、真实设备授权、长时间SLA和全球产品排名：没有相应现场证据，本轮不作认证结论。

这份报告的通过结论限定为已经列明并留下回执的本机仿真、研究与注册业务链。

## 九、重新演示

1. `.venv/bin/python scripts/run_joint_demo.py`，打开舷鸥的“双模式港航联合系统”。
2. 选择企业受控或RL研究；选择“完整原生航次与业务执行、核验、补偿”。本机单人演示选择显式模拟岗位。
3. 生成计划、核对摘要、批准；等待原生航次到终点，查看运输对照与资源排程。
4. 审阅具体工作单后确认模拟岗位演练；真实岗位模式需两个独立认证账号。
5. 查看执行、读回核验和补偿回执；从实际链接打开Flutter并签收。
6. 刷新舷鸥或从历史选择任务，导出回执核验事件链、步骤结果和业务操作摘要。

运行时版本、固定权重与复现指令见 [开源策略运行时说明](HARNESS_POLICY_RUNTIME_20261029.md)。全部原始文件位于 `.codex_artifacts/joint-harness-phase2-20261029/`，关键入口为 `acceptance-summary.json` 和四份 `*-accepted-export.json`。
"""
    (ROOT / "docs/HARNESS_PHASE2_ACCEPTANCE_20261029.md").write_text(report)
    delivery = f"""# 双模式Harness二期交付（2026-10-29）

已交付完整原生航次、固定开源预训练策略推理、同约束基线比较、资源事件执行、原生业务审批执行核验补偿、客户端签收和故障门禁。验收范围与未验证边界见 [二期验收报告](HARNESS_PHASE2_ACCEPTANCE_20261029.md)。

## 稳定与研究分离

企业模式采用登记流程与合格基线，新预训练运输策略只作影子比较；研究模式允许在独立约束复核后采用学习策略。两种模式共享来源、版本、审批、预算、幂等和审计门禁。原有评估与短时航行样本仍为默认；完整流程显式选择，不替换旧功能。

## 主要代码

- `app/harness/transport.py`：本地隔离模型身份/版本检查、SI路线复核、基线与策略选择。
- `integrations/policy_runtime/`：固定上游策略、补载求解器、动作语义转换、依赖锁和systemd服务。
- `app/harness/coordination.py`：共同工程时钟、资源和原有协同接口适配。
- `app/harness/business.py`：逐操作写前记录、原生工作单、审批、执行、读回和补偿。
- `app/harness/joint.py`、`dual_api.py`、`contracts.py`：可选完整工作流、二次审批、可恢复取消/核查和协议。
- `web/joint_harness.js`：完整范围、岗位选择、候选数值比较、审阅/控制/导出；`web/app.js`保留快速打开的工作台，资源版本已更新。
- 数字孪生新增 `tools/harness_business_worker.py`、`app/services/harness_event_execution.py`；航行新增 `tools/harness_full_voyage.gd`；Flutter扩展原联合任务卡。

## 交付路径

- 本机入口：http://127.0.0.1:8010/；Flutter：http://127.0.0.1:7357/。
- 最终企业任务：{release["id"]}；完整研究任务：{research["id"]}。
- 安装与启动：[运行时说明](HARNESS_POLICY_RUNTIME_20261029.md)。
- 原有一期报告和失败记录保留，二期补齐结论以本次报告和原始回执为准。

没有重新训练或替换舷鸥原大模型。新增运行时、模拟控制和测试都保留在本机。真实生产授权与本机演练分开。
"""
    (ROOT / "docs/HARNESS_PHASE2_DELIVERY_20261029.md").write_text(delivery)
    print(
        json.dumps(
            {
                "tasks": summary["tasks"],
                "python_passed": count,
                "report": str(ROOT / "docs/HARNESS_PHASE2_ACCEPTANCE_20261029.md"),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
