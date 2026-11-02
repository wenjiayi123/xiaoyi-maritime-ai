"""Publish the reviewed 37-item scorecard without changing historical registries."""

import argparse
import copy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".codex_artifacts/capability-review-v8-20261031"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def register(experiment):
    baseline_path = ROOT / "data/evaluation/xiaoyi_capability_scorecard_v6_20261030.json"
    baseline = json.loads(baseline_path.read_text())
    targets_path = ROOT / "config/capability_targets_v8.json"
    targets = json.loads(targets_path.read_text())
    summary = json.loads((experiment / "summary.json").read_text())
    for path, checksum in summary["source_sha256"].items():
        if sha(ROOT / path) != checksum:
            raise ValueError("experiment sources changed: " + path)
    actual = {
        "linkage": "恢复三个登记本机演示服务后，重新运行八项适配器；观测、幂等与配置恢复均通过。第一次离线失败保留，70分不因恢复服务而提高。",
        "forecast": f"新增1/7/14天预测、独立校准、WIS及因果监控；48单元只有{summary['candidate_90_coverage_pass_cells']}达到覆盖门槛，与强基线48/48持平，保持65分。",
        "schedule": "新增五情景共享min-max排程；16案例×5情景全部可行，独立小问题穷举核验。仅功能覆盖3→4，其余维度不变，50→55分。",
        "energy": "联合计划实际约束20%供电降额，并在基本负荷不可行时拒绝输出执行计划；实测能源/碳资格未改变。",
        "wholeport": "同一共享计划同时约束各情景的泊位、引航、拖轮、岸桥、运输、堆场和供电；仍是合成工单。",
        "observability": "新增只用已公布真值的28点覆盖/误差监控、连续历史窗口检查及漂移提示。",
        "audit": "新增协议、冻结模型、全样本回放、代码/数据摘要和版本失效检查；历史证据未覆盖。",
        "lineage": "新增选型2023/校准2024/回放2025–2026的独立记录，明确7天发布时间为假设。",
        "visual": "新增37项搜索/优先级筛选、逐项展开、逐港预测与共享计划甘特图。",
        "clients": "新增浏览器评估页面与窄屏布局；原生窗口仍待验收。",
        "handover": "新增包含失败、代价、下一步验收条件与当次计算回执的评估导出。",
        "query": "新增预测提前量、日活动指标、代理成本和实际执行资格的独立呈现。",
        "harness": "新增有身份约束、冻结证据校验、限定输入和计算互斥的预测/联合优化API。",
        "security": "新增API沿用现有身份权限；证据变化、非法输入、并发计算时拒绝执行。",
        "sop": "新增缺测/漂移/区间不合格时暂停、候选退化时仅回退到合格基线的研究决策。",
        "simulator": "新增相同工单在五种压力情景下对名义与共享计划逐项复算，完整保留约束失败。",
    }
    components = []
    mapping = {r["id"]: r for r in targets["targets"]}
    assert len(mapping) == len(baseline["components"]) == 37
    for old in baseline["components"]:
        c = copy.deepcopy(old)
        c["previous_score"] = old["score"]
        c["target"] = mapping[c["id"]]
        c["round_status"] = "本轮已实现或完成专项复验" if c["id"] in actual else "本轮完成评估；专项提升待执行"
        if c["id"] in {"live_data", "dispatch", "multimodal"}:
            c["round_status"] = "已评估；需要真实数据、标定或机构授权后才能继续验收"
        c["score_change_reason"] = actual.get(
            c["id"], "保留当前证据成熟度分；没有本轮专项新收益证据，不因路线图或测试总数加分。"
        )
        if c["id"] == "schedule" and summary["all_scenarios_feasible"] and summary["proven_robust_optima"] == 16:
            c["dimensions"]["功能覆盖"] = 4
            c["score"] = sum(c["dimensions"].values()) * 5
            c["can_do"] += "新增同一计划在五种压力情景中共同满足约束，报告稳健性代价。"
        if c["id"] in actual:
            c["evidence"].append(str((experiment / "summary.json").relative_to(ROOT)))
        if c["id"] == "linkage":
            c["evidence"].append("reports/linked_agent_acceptance_capability_v8_ready_20261031.json")
        c["evidence_inventory"] = [
            {
                "path": p,
                "exists": (ROOT / p).is_file(),
                "sha256_at_review": sha(ROOT / p) if (ROOT / p).is_file() else None,
                "notice": "文件存在与摘要核对；不等于此项全部业务在本轮重新执行",
            }
            for p in c["evidence"]
        ]
        assert c["score"] == sum(c["dimensions"].values()) * 5
        components.append(c)
    scorecard = {
        "schema": "xiaoyi-capability-scorecard.v8",
        "reviewed_on": "2026-10-31",
        "baseline": {"path": str(baseline_path.relative_to(ROOT)), "sha256": sha(baseline_path)},
        "rubric": baseline["rubric"],
        "components": components,
        "references": targets["references"],
        "scope": "37项当前工程证据评审；历史研究证据+本轮回归+两个新算法/保障模块。未对37项全部进行新的独立业务盲测。",
        "production_authority": False,
    }
    score_path = ROOT / "data/evaluation/xiaoyi_capability_scorecard_v8_20261031.json"
    write(score_path, scorecard)
    docs = [
        "# 小懿37项能力评估与逐项提升 V8（2026-10-31）",
        "",
        "**结论：小懿是已有较强可追溯工程能力的港航研究平台，距离顶级港口生产系统的主要差距仍是预测可靠性、真实物理标定、多机构协同和现场验证。**",
        "",
        "本轮沿用五维0—4分×5的100分量表。没有统一的“全球顶级港航系统百分制”；这些是工程判断，不是排名、认证或统计显著差异。文件存在、代码测试通过、算法收益和现场资格分别记录。",
        "",
        "37项均已逐项审阅并给出目标、改进动作和验收条件；本轮重点落地预测可信度和多情景联合排程，并补评估/监控/证据界面。其余专项动作明确列为待执行，不宣称全部能力都已提升。",
        "",
        "## 本轮实际结果",
        "",
        f"- 预测：{summary['forecast_cells']}个港口×年份×提前量单元、{summary['forecast_predictions']}次历史回放。选型最终均为weekday84，与冻结强基线{summary['candidate_ties_strong_baseline_mae_cells']}/48持平；{summary['candidate_beats_persistence_mae_cells']}/48优于简单持续值，但不能称超过强基线。",
        f"- 90%名义区间只有{summary['candidate_90_coverage_pass_cells']}/48单元达到本轮80%覆盖下限；宽度门槛48/48通过。监控允许{summary['forecast_statuses'].get('candidate', 0)}次研究使用、暂停{summary['forecast_statuses'].get('hold', 0)}次。不能只报告允许子集的准确率。",
        "- 预测改进：增加1/7/14天提前量、选型/校准分离、WIS、缺测/陈旧输入阻断、漂移提示、只用已公布真值的滚动监控及合格基线回退。预测评分维持65，不因加入检查就提高精度评价。",
        f"- 排程：{summary['schedule_cases']}个合成工单案例×5情景，共{summary['declared_scenario_evaluations']}次。原名义计划{summary['nominal_failed_scenarios']}次约束失败，新共享计划{summary['robust_failed_scenarios']}次失败；16/16取得求解最优界，额外暂缓工单{summary['additional_deferred_jobs']}。",
        f"- 稳健性代价：在相同名义情景下，目标平均增加{summary['mean_nominal_cost_increase_points']:.4f}代理分，最大增加{summary['maximum_nominal_cost_increase_points']:.4f}。包括等待、迟交、用能和暂缓罚项，不是货币或实测损失。排程功能覆盖3→4，50→55分，其余维度不变。",
        "- 源数据是此前已使用的IMF PortWatch归档。2023选型、2024校准、2025–2026回放；本轮不是新的盲测或整港未见泛化证明。发布时间仅采用假设7天延迟。",
        "- 在开始时发现已有V7训练任务；本轮保持其源码、训练与研究结果独立，未把未登记的V7开发结果算入本轮加分。原有全部失败、评分与证据注册表保留。",
        "- 时间边界修正：早期experiment/experiment-final存在跨年校准模型尚不可用的问题，不作为最终验收。修正后，校准样本的决策日起点为2024-01-08，最终模型可用日起点为2025-01-08；监控排除模型可用前的历史预测，样本不足时暂停。原结果与原因保留在clock-correction.json。阈值未按结果调优。最终预测为1,872次、覆盖门槛26/48、暂停939次，与初步结果不同。",
        "",
        "## 逐项评分总表",
        "",
        "|能力|上轮|本轮|优先级|本轮状态|",
        "|---|---:|---:|---|---|",
    ]
    docs.extend(
        f"|{c['name']}|{c['previous_score']}|{c['score']}|{c['target']['priority']}|{c['round_status']}|"
        for c in components
    )
    docs += [
        "",
        "P0优先处理影响预测可信度、计划可行性与现场边界的事项；P1提升专项能力；P2在核心数据和验证齐备后扩展。优先级不表示已授权现场执行。",
        "",
        "## 逐项评估与下一道验收",
        "",
    ]
    for i, c in enumerate(components, 1):
        t = c["target"]
        docs += [
            f"### {i}. {c['name']}：{c['score']}/100",
            "",
            f"**现在能做：**{c['can_do']}",
            "",
            f"**缺口：**{c['boundary']}",
            "",
            f"**本轮：**{c['score_change_reason']}",
            "",
            f"**对标目标：**{t['target']}",
            "",
            f"**提升动作：**{t['next']}",
            "",
            f"**验收条件：**{t['acceptance']}",
            "",
            "五维：" + "；".join(f"{k}{v}/4" for k, v in c["dimensions"].items()) + "。",
            "",
            "依据：" + "、".join(f"[{Path(p).name}](../{p})" for p in c["evidence"]) + "。",
            "",
        ]
    docs += [
        "## 公开对标依据",
        "",
        "当前标准和公开实践作为能力要求的依据；具体门槛由项目定义。MPA公告中的试点与未来计划仍按其原范围描述，不当作全部规模部署。",
        "",
    ]
    docs.extend(f"- [{s['name']}]({s['url']})：{s['kind']}；核查日期{s['checked_on']}。" for s in targets["references"])
    docs += [
        "",
        "## 使用与复验",
        "",
        "在小懿左侧点击“能力评估与提升 · 37项”，或访问 `/web/capability-review.html`。可搜索能力、按优先级筛选、查看逐港/逐提前量结果，运行预测检查、缺测/突变演练以及五情景排程；导出包含当前会话回执。",
        "",
        "API沿用现有身份权限：`GET /api/harness/capability-review/catalog`；`POST /api/harness/capability-review/forecast`；`POST /api/harness/capability-review/schedule`。代码或输入哈希变化后历史资料仍可查阅，重算暂停。",
        "",
        "回归与浏览器检查回执见 [验收文件](../.codex_artifacts/capability-review-v8-20261031/acceptance.json)。研究完整记录见 [最终实验摘要](../.codex_artifacts/capability-review-v8-20261031/experiment-qualified/summary.json)。",
        "",
        "复算研究：`.venv/bin/python scripts/evaluate_capabilities_v8.py --out .codex_artifacts/一个新的输出目录`。输出目录必须未存在；旧报告不覆盖。当前已看过的归档复算只能称回归，不重新命名为独立留出。",
        "",
        "本轮重新运行八项本机适配器并核对恢复；第一次因三个服务离线造成的失败保留，服务恢复后的八项均通过。此项不等于四系统全部业务、硬件或长期SLA验收。本轮未重建Docker镜像、未重测本机4B自由生成、未通过原生窗口验收、未开展生产调度。后续真正改变这些评分需要相应专项或现场证据。",
        "",
    ]
    (ROOT / "docs/XIAOYI_CAPABILITY_REVIEW_V8_20261031.md").write_text("\n".join(docs))
    reports = {
        "scorecard": score_path,
        "summary": experiment / "summary.json",
        "forecast": experiment / "forecast.json",
        "scheduling": experiment / "scheduling.json",
        "selection": experiment / "selection-before-audit.json",
    }
    owned = [
        "app/harness/capability_review_v8.py",
        "app/harness/predictive_v8.py",
        "app/harness/robust_schedule_v8.py",
        "app/harness/operations_v5.py",
        "config/capability_targets_v8.json",
        "web/capability-review.html",
        "web/capability-review.css",
        "web/capability-review.js",
    ]
    registry = {
        "schema": "xiaoyi-capability-review-registry.v8",
        "reports": {k: {"path": str(p.relative_to(ROOT)), "sha256": sha(p)} for k, p in reports.items()},
        "sources": {**summary["source_sha256"], **{p: sha(ROOT / p) for p in owned}},
        "production_authority": False,
    }
    write(ROOT / "config/capability_review_v8_registry.json", registry)
    print(
        json.dumps(
            {
                "components": len(components),
                "changed_scores": [
                    (c["name"], c["previous_score"], c["score"])
                    for c in components
                    if c["score"] != c["previous_score"]
                ],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", type=Path, default=OUT / "experiment-qualified")
    register(parser.parse_args().experiment.resolve())
