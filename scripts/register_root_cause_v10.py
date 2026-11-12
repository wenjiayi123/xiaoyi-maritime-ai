"""Attribute limitations, preserve scores unless frozen independent tests justify change."""

import copy
import hashlib
import json
import statistics as stats
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".codex_artifacts/root-cause-v10-20261031"


def read(p):
    return json.loads((ROOT / p).read_text())


def sha(p):
    return hashlib.sha256((ROOT / p).read_bytes()).hexdigest()


def write(p, value):
    (ROOT / p).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def main():
    assert read(".codex_artifacts/root-cause-v10-20261031/independent-readback.json")["passed"]
    annual = read("data/public/annual_v10_20261031/report.json")
    rl = read(".runtime/rl-v10-20261031/report.json")
    root = read(".codex_artifacts/root-cause-v10-20261031/root-cause-evidence.json")
    rule = read("data/public/annual_v10_20261031/rule-before-new-sites.json")
    test = read("data/public/annual_v10_20261031/test-manifest.json")
    promotion = read("data/public/annual_v10_20261031/promotion-gate.json")
    assert all(e["retrieved_at"] > promotion["registered_at"] for e in test["entries"])
    old, new = annual["summary"]["v9_global"], annual["summary"]["v10_selected"]
    regressions = []
    for c in annual["cells"]:
        if c["method"] != "v10_selected":
            continue
        previous = next(r for r in annual["cells"] if r["method"] == "v9_global" and r["station_id"] == c["station_id"])
        regressions += [
            {"station_id": c["station_id"], "quarter": q}
            for q, v in previous["quarters"].items()
            if v["passed"] and not c["quarters"][q]["passed"]
        ]
    promotion_checks = {
        "annual_pass_count_nondecreasing": new["annual_passed"] >= old["annual_passed"],
        "all_four_quarters_joint_pass_count_nondecreasing": new["annual_and_all_quarters"]
        >= old["annual_and_all_quarters"],
        "quarter_pass_count_strictly_increasing": new["quarters_passed"] > old["quarters_passed"],
        "mean_wis_nondecreasing_quality": new["mean_wis"] <= old["mean_wis"],
        "no_old_passing_quarter_becomes_failure": not regressions,
    }
    promoted = all(promotion_checks.values())
    candidate = next(r for r in rl["aggregate"] if r["algorithm"] == "rl_rollout7.reserve")
    capacity = [s["physical_capacity_ablation"] for s in rule["development"] if s["status"] == "ready"]
    capacity_summary = {
        "sites": len(capacity),
        "old_basis_mean_mae": stats.mean(c["old_basis_mae_m"] for c in capacity),
        "expanded37_mean_mae": stats.mean(c["expanded37_mae_m"] for c in capacity),
        "improved_sites": sum(c["expanded37_mae_m"] < c["old_basis_mae_m"] for c in capacity),
        "scope": "viewed development stations only; no promotion or independent point-accuracy claim",
    }
    capacity_summary["relative_improvement"] = (
        1 - capacity_summary["expanded37_mean_mae"] / capacity_summary["old_basis_mean_mae"]
    )
    language = {"qa", "dialogue", "handover", "query", "llm", "lora", "retrieval", "skills"}
    numeric = {
        "forecast",
        "rl_policy",
        "rl_lab",
        "mpc",
        "short_tide",
        "annual_twin",
        "forced_twin",
        "schedule",
        "energy",
        "wholeport",
        "navigation",
        "simulator",
    }
    external = {"live_data", "dispatch", "dcsa", "multimodal"}
    scorecard = copy.deepcopy(read("data/evaluation/xiaoyi_capability_scorecard_v9_20261031.json"))
    scorecard.update(
        schema="xiaoyi-capability-scorecard.v10",
        baseline={
            "path": "data/evaluation/xiaoyi_capability_scorecard_v9_20261031.json",
            "sha256": sha("data/evaluation/xiaoyi_capability_scorecard_v9_20261031.json"),
        },
        scope="全37项限制归因审查；仅RL和年度潮位实施本轮独立新港/新站复验，不把结构审查称为37项因果实测。",
    )
    for c in scorecard["components"]:
        c["previous_score"] = c["score"]
        sid = c["id"]
        category = (
            "语言/检索模型、训练数据与任务链"
            if sid in language
            else "专业数值模型、观测信息与物理约束"
            if sid in numeric
            else "真实数据、机构接口、授权或专用感知缺口"
            if sid in external
            else "工程可靠性、证据治理与交付条件"
        )
        verdict = (
            "未证明；需要固定数据/工具/提示的跨规模对照" if sid in language else "现有证据不支持归因于语言模型参数量"
        )
        if sid in {"rl_policy", "annual_twin"}:
            verdict = "已核查独立数值调用链并实测，非语言模型直接瓶颈"
        c["limitation_attribution"] = {
            "category": category,
            "verdict": verdict,
            "scope": "职责与既有证据审查，除标明专项外未进行本轮跨规模因果实验",
        }
        c["round_status"] = "本轮根因归类；沿用V9评分"
        c["score_change_reason"] = "没有本轮该项独立收益证据，保持V9评分；不把可能受规模影响当作已证明体量不足。"
        if sid == "rl_policy":
            c["round_status"] = "已改进并用独立8新港测试；未通过正收益门槛"
            c["score_change_reason"] = (
                "7日RL策略场景推演与同信息28日强对照已实测；相对最强MPC收益仍0。新8港常态15/16窗口连知晓未来的最优诊断器都无法改善，平均收益上界仅0.0101933%。瓶颈为本基准的信息/动作/成本结构，30分不变。"
            )
            c["target"]["next"] = (
                "不继续在接近最优的单队列基准上堆模型；取得真实多资源耦合作业数据后另立问题合同与独立数据，不把更换任务的收益冒充当前任务胜出。"
            )
        elif sid == "annual_twin":
            c["round_status"] = "已用冻结规则完成8个独立新站全年与逐季测试"
            c["score_change_reason"] = (
                f"新8站同数据对照：全年{old['annual_passed']}→{new['annual_passed']}/8，季度{old['quarters_passed']}→{new['quarters_passed']}/32，全年及四季{old['annual_and_all_quarters']}→{new['annual_and_all_quarters']}/8；WIS {old['mean_wis']:.6f}→{new['mean_wis']:.6f}。额外发布门槛通过={promoted}，原验收阈值不变。"
            )
            if promoted:
                c["dimensions"]["验证深度"] = 4
                c["score_change_reason"] += (
                    "根因消融、未见站独立复验和逐季非退化证据补齐，验证深度3→4，45→50；不提高现场成熟度。"
                )
            c["target"]["next"] = (
                "剩余失败站保持暂停；按真实季节偏差与气象/水文强迫建立新开发协议，冻结后使用新站新年验证，不放宽宽度/覆盖门槛。"
            )
        if sid in {"rl_policy", "annual_twin"}:
            evidence = (
                ".runtime/rl-v10-20261031/report.json"
                if sid == "rl_policy"
                else "data/public/annual_v10_20261031/report.json"
            )
            c["evidence"].append(evidence)
            c["evidence_inventory"].append(
                {
                    "path": evidence,
                    "exists": True,
                    "sha256_at_review": sha(evidence),
                    "notice": "本轮冻结后独立新港/新站实测",
                }
            )
        c["score"] = sum(c["dimensions"].values()) * 5
    components = {c["id"]: c for c in scorecard["components"]}
    score_path = "data/evaluation/xiaoyi_capability_scorecard_v10_20261031.json"
    write(score_path, scorecard)
    findings = [
        "约40.22亿参数来自此前实际模型身份记录；它负责语言任务。RL查表/策略推演和潮位谐波计算不读取这些语言权重。禁止语言网关及网络后，两条数值计算仍通过测试。",
        "RL常态16个新窗口中，强MPC在15个窗口达到知晓未来诊断器的最优值；平均最大可能改善仅0.0102%。扩大学习器并不会创造新的可行动作或可用信息。",
        f"年度谐波从20扩到37项，仅在已看开发站平均改善{capacity_summary['relative_improvement']:.2%}，{capacity_summary['sites'] - capacity_summary['improved_sites']}站变差。专业模型复杂度存在次要影响，但不是语言模型体量问题。",
        "年度区间的直接缺陷是把最差季节宽度传播到全年，以及不同季节的残差分布不同。开发集选出简单季度校准；点模型保持不变，原有宽度、覆盖、误差和可用率门槛全部保留。",
        "复杂对话、长链规划、检索与领域表达仍可能受语言/嵌入模型、数据和提示影响；本轮没有跨语言模型规模对照，不能宣称4B足以支撑全部顶级港航能力，也不能据此放弃所有可改进模块。",
    ]
    refs = [
        {"title": "语言模型缩放规律：规模、数据与计算共同影响损失", "url": "https://arxiv.org/abs/2001.08361"},
        {"title": "Chinchilla：训练数据与模型规模需要共同配置", "url": "https://arxiv.org/abs/2203.15556"},
        {
            "title": "Bertsekas：MPC与RL的动态规划联系",
            "url": "https://web.mit.edu/dimitrib/www/Bertsekas_NMPC_IFAC.pdf",
        },
        {"title": "NOAA：潮汐预测的准确度与天气影响", "url": "https://tidesandcurrents.noaa.gov/faq.html"},
        {"title": "条件覆盖保证的理论限制", "url": "https://arxiv.org/abs/1903.04684"},
    ]
    summary = {
        "schema": "xiaoyi-root-cause.v10",
        "findings": findings,
        "root_evidence": root,
        "oracle": root["oracle"],
        "capacity_ablation": capacity_summary,
        "rl": {"candidate": candidate, "baselines": rl["aggregate"], "oracle_is_not_executable": True},
        "annual": {
            "description": "独立8新站；先用原站2025年作开发集比较六种区间，再冻结规则、拟合2016–2024年历史，最后获取新站2025真值。选定分季度对称校准，点模型不变。",
            "summary": annual["summary"],
            "cells": annual["cells"],
            "promotion_checks": promotion_checks,
            "promoted": promoted,
            "quarter_regressions": regressions,
        },
        "priorities": [
            {
                "id": sid,
                "name": components[sid]["name"],
                "previous_score": components[sid]["previous_score"],
                "score": components[sid]["score"],
                "verdict": "收益空间极小；保持严格RL准入"
                if sid == "rl_policy"
                else "冻结季度校准改善通过原门槛"
                if promoted
                else "存在改善与失败，保持原评分",
            }
            for sid in ["rl_policy", "annual_twin"]
        ],
        "references": refs,
        "all_37_capabilities_causally_tested": False,
        "all_scientific_limits_resolved": False,
        "production_authority": False,
    }
    summary_path = ".codex_artifacts/root-cause-v10-20261031/summary.json"
    write(summary_path, summary)
    sources = {}
    for selection in [
        ".runtime/rl-v10-20261031/selection-before-test.json",
        "data/public/annual_v10_20261031/selection-before-test.json",
    ]:
        sources.update(read(selection)["source_sha256"])
    for p in [
        "app/harness/root_cause_v10.py",
        "web/root-cause-v10.html",
        "web/root-cause-v10.js",
        "web/capability-review.css",
        "data/public/annual_v10_20261031/promotion-gate.json",
    ]:
        sources[p] = sha(p)
    reports = {
        "summary": summary_path,
        "scorecard": score_path,
        "annual": "data/public/annual_v10_20261031/report.json",
        "annual_selection": "data/public/annual_v10_20261031/selection-before-test.json",
    }
    write(
        "config/root_cause_v10_registry.json",
        {
            "schema": "xiaoyi-root-cause-registry.v10",
            "sources": sources,
            "reports": {k: {"path": p, "sha256": sha(p)} for k, p in reports.items()},
            "production_authority": False,
        },
    )
    docs = [
        "# 舷鸥模型体量与能力限制根因评估 V10（2026-10-31）",
        "",
        "**结论：本轮两个重点失败不是由舷鸥约4B语言模型直接造成。RL受当前基准极小的可改进空间限制；年度潮位存在可修复的季节校准问题，亦有观测缺口和未建模低频残差。不能据此断言4B已足够完成全部顶级港航任务。**",
        "",
        "## 判断依据与理论边界",
        "",
        "模型规模、数据和训练计算共同影响语言损失；缩放规律并不自动适用于外部的潮位重构或离散控制器。[Kaplan等](https://arxiv.org/abs/2001.08361)与[Hoffmann等](https://arxiv.org/abs/2203.15556)支持“规模不是唯一变量”，并不能替代本机跨规模消融。",
        "",
        "本轮核对实际调用链：RL为经验分布/查表策略与数值推演，年度为UTide谐波与历史误差校准。单测禁用ModelGateway全部普通方法、HTTP请求和网络连接，仍能运行RL推演及24小时潮位重构；未来未公布记录的投毒也不改变RL动作。此前模型身份记录为4,022,468,096个语言参数，非本轮新增大模型运行证据。默认11435端点本轮探测不可达，不据此推断所有语言服务均离线；数值实验正常运行。",
        "",
        "RL和MPC都可由动态规划来理解，并没有“同信息条件下RL必然优于MPC”的定理。[Bertsekas的统一框架](https://web.mit.edu/dimitrib/www/Bertsekas_NMPC_IFAC.pdf)说明策略训练、终端价值与在线推演的关系。这里增加的是7天学习策略推演，并把同信息28天推演纳入强基线池；不冒称纯神经RL。",
        "",
        "天文潮与总观测水位不同；风、气压等可影响实际水位，[NOAA准确度说明](https://tidesandcurrents.noaa.gov/faq.html)对此有明确边界。本地旧7站残差的日均方差/逐小时方差约75%–88%，说明大量误差在日尺度或更长尺度，但没有气象因果实验，不能把每个残差都归因于天气。",
        "",
        "边际覆盖不能自动推出各季条件覆盖；无分布假设下精确条件覆盖有理论限制。[Barber等原始研究](https://arxiv.org/abs/1903.04684)。本轮只声称独立样本实测结果，不给未来所有季节提供无条件保证。",
        "",
        "## RL：先测量最优收益空间，再判模型是否不够",
        "",
        "新8港为Dongjiakou、Qinzhou、Qinhuangdao、Delfzijl、Bluff Harbor、Gisborne、San Giorgio、Safaga，与此前训练和各轮测试港ID均不重叠。冻结候选和强基线后才提取标签；2026年1月、4月各90天，四种情景。五个原训练块重采样模型沿用，新增的是基于这些模型的策略改进推演，没有重新训练4B。",
        "",
        "|情景|强MPC已最优窗口|平均收益上界|最大单窗上界|",
        "|---|---:|---:|---:|",
    ]
    docs += [
        f"|{key}|{v['exactly_optimal_baseline_windows']}/{v['windows']}|{v['mean_gain_upper_bound']:.6%}|{v['maximum_gain_upper_bound']:.6%}|"
        for key, v in root["oracle"].items()
    ]
    docs += [
        "",
        "诊断器知道未来90天全部到港量，是不可部署的上界工具；保留原5动作、资源可用性、原安全动作集合、资源/积压/切换/溢出/终端成本。64个MILP均达到最优终止，独立逐动作复算后，目标与对偶下界差最大约3.2×10⁻¹²。没有把oracle的未来信息提供给RL或强MPC。",
        "",
        f"可执行候选相对冻结最强基线 `{candidate['matched_baseline']}` 收益 {candidate['relative_cost_interval']['mean_delta']:.6%}，港口簇95%区间 {candidate['relative_cost_interval']['port_cluster_ci95']}，研究准入={candidate['research_admission']}。原正收益、逐港不退化、压力非劣、安全与收益分散性检查不变。30分保持；新数据没有通过正收益不能加分。",
        "",
        "这不是证明RL永远无用，也不是证明所有调度问题没有收益空间；它仅证明当前单队列、五档产能、现有观测与成本的基准已接近强基线最优。继续扩大策略或语言模型缺乏收益依据；真正不同的多资源耦合需要真实作业数据与另一个冻结任务合同，不能偷换题目算作本基准提升。",
        "",
        "## 年度潮位：根因消融与独立新站结果",
        "",
        f"开发集20项与嵌套37项UTide谐波对照：平均MAE {capacity_summary['old_basis_mean_mae']:.6f}→{capacity_summary['expanded37_mean_mae']:.6f}m，改善{capacity_summary['relative_improvement']:.2%}，6/7站改善、1/7退化。属于已看开发数据，未作为新站点预测增益；更大的物理基函数集合与更大的语言模型是不同概念。",
        "",
        "六种区间方法在旧站2025年开发集比较后，选定quarter_symmetric。新站的点模型、选型年份和强物理基线与V9保持一致，只改变区间按季度取值；不把全年最差季度半径复制到所有季度。2016–2024历史拟合/校准，规则冻结、各站模型冻结，再下载2025测试真值。",
        "",
        "|同一新8站对照|全年通过|季度通过|全年且四季均过|平均WIS m|",
        "|---|---:|---:|---:|---:|",
    ]
    docs += [
        f"|{method}|{v['annual_passed']}/8|{v['quarters_passed']}/32|{v['annual_and_all_quarters']}/8|{v['mean_wis']:.6f}|"
        for method, v in annual["summary"].items()
    ]
    docs += [
        "",
        f"额外发布/评分门槛在新站测试真值获取前登记：{promotion_checks}。整体升级准入={promoted}；旧通过季度退化记录={regressions}。",
        "",
        "原验收要求逐字保留：MAE≤0.2m、名义90%区间实测覆盖≥80%、最大宽度≤0.75m、齐备率≥95%、不劣于强物理点基线；全年与每季同时核查。固定宽度和覆盖率之间仍有信息限制，超宽不截窄、缺失不插值、失败站不换掉。Bob Hall Pier因历史选型季真值不足保留为阻塞站。",
        "",
        "WIS均值针对有可计算预测的7站；Bob Hall Pier没有可计算WIS，但仍保留在全年8站、季度32格的失败分母。11.4%的WIS下降是区间质量改善，不是点预测精度提升。",
        "",
        "剩余失败逐项保留：Crescent City第一季度最大区间宽度0.881m，超过0.75m；Charleston Oregon第一季度宽度0.890m，且第四季度观测齐备率仅75.7%（全年93.7%），未达到95%；Bob Hall Pier缺少历史选型季观测。新规则没有解决最难季节的过宽问题，也无法补造真实观测，全年及全部四季通过仍为5/8。",
        "",
        "|新站|V10全年|季度通过|MAE m|覆盖|最大宽度 m|",
        "|---|---|---:|---:|---:|---:|",
    ]
    for c in annual["cells"]:
        if c["method"] == "v10_selected":
            a = c["annual"]
            docs.append(
                f"|{c['site']}|{a['passed']}|{sum(q['passed'] for q in c['quarters'].values())}/4|{a.get('mae_m', '—')}|{a.get('coverage90', '—')}|{a.get('max_width90_m', '—')}|"
            )
    docs += [
        "",
        "## 逐项评分与体量归因",
        "",
        "以下对其余35项是现有模块职责与证据审查，不是新做35项因果实验。语言敏感任务若要判定体量瓶颈，需固定知识库、工具、提示、样本和预算后做不同规模模型对照；没有这个证据就不宣布“模型小，所以无须改进”。",
        "",
        "|能力|V9→V10|主要限制类型|规模判断|",
        "|---|---:|---|---|",
    ]
    docs += [
        f"|{c['name']}|{c['previous_score']}→{c['score']}|{c['limitation_attribution']['category']}|{c['limitation_attribution']['verdict']}|"
        for c in scorecard["components"]
    ]
    docs += [
        "",
        "## 复现与使用",
        "",
        "- `app/harness/root_control_v10.py`：可执行场景推演与不可执行最优界诊断，二者分开。",
        "- `.runtime/rl-v10-20261031/`：冻结选型、独立8港完整轨迹和64次最优界诊断。",
        "- `data/public/annual_v10_20261031/`：原始NOAA响应、规则/模型两次冻结、8新站全年轨迹与失败。",
        "- `.codex_artifacts/root-cause-v10-20261031/`：根因数据、独立读回、工程回归与浏览器证据。",
        "- 本机交互页面：<http://127.0.0.1:18018/web/root-cause-v10.html>，可重算新站一天潮位，查看旧新季度区间，导出完整回执。",
        "",
        "开发阶段曾因重复逐小时计算而中断一次，向量化/缓存后已逐方法对照原定义；又因NOAA式分潮名与UTide名称不兼容失败一次，按预先保留的修订文件换为明确的37项UTide嵌套集合。均发生在新站测试真值获取前；原失败日志、代码快照和修订文件保留，不改验收阈值。",
        "",
        "独立新数据指未用于先前训练/测试的新港、新站ID；它们仍共享世界年份与区域环境，不能冒称完全统计独立或真实历史发布时间验证。已看旧站仅作开发，旧失败分母不替换。生产权限、真实作业校准、长期部署资格未改变。",
    ]
    (ROOT / "docs/XIAOYI_ROOT_CAUSE_V10_20261031.md").write_text("\n".join(docs) + "\n")
    print(json.dumps(summary["priorities"], ensure_ascii=False, indent=2))
    print("promotion", promotion_checks)


if __name__ == "__main__":
    main()
