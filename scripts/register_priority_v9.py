"""Register measured outcomes without promoting failed research candidates."""

import copy
import hashlib
import json
import statistics as stats
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".codex_artifacts/priority-v9-20261031"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads((ROOT / path).read_text())


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def main():
    forecast_path = "data/public/interval_v9_20261031/report.json"
    annual_path = "data/public/annual_v9_20261031/report.json"
    rl_path = ".runtime/rl-v9-20261031/report.json"
    f, a, r = [read(p) for p in [forecast_path, annual_path, rl_path]]
    assert read(".codex_artifacts/priority-v9-20261031/independent-readback.json")["passed"]
    fm = {v["method"]: v for v in f["summary"]}
    candidate = next(v for v in r["aggregate"] if v["algorithm"] == "constrained.reserve")
    former = next(v for v in r["aggregate"] if v["algorithm"] == "former.reserve")
    qstats = {}
    for method in fm:
        quarters = [
            q
            for c in f["cells"]
            if c["method"] == method
            for q in c["summary"]["quarters"].values()
            if q["expected"] >= 45
        ]
        qstats[method] = {
            "passed": sum(q["coverage_gate"] and q["width_gate"] for q in quarters),
            "total": len(quarters),
        }
    annual_joint = {
        method: sum(
            c["annual"]["passed"] and all(q["passed"] for q in c["quarters"].values())
            for c in a["cells"]
            if c["method"] == method
        )
        for method in ["v9", "legacy_v7_rule"]
    }
    annual_wis = {
        method: stats.mean(c["annual"]["wis90_m"] for c in a["cells"] if c["method"] == method and c["annual"]["n"])
        for method in ["v9", "legacy_v7_rule"]
    }
    improvement = 1 - fm["aci90"]["mean_normalized_wis"] / fm["global_v8"]["mean_normalized_wis"]
    reasons = {
        "forecast": f"分港滚动校准、延迟反馈与跨季门禁完成闭环；7新港21/21单元及42/42完整季度通过，原区间1/21及4/42。WIS下降{improvement:.2%}；区间变宽，简单分港固定校准平均WIS略优。仅限日活动指标范围的功能覆盖3→4，65→70；不增加现场成熟度。",
        "rl_policy": f"将同一安全约束纳入Bellman训练并保留同分布随机MPC强对照，8新港五次训练重采样实测相对收益{candidate['relative_cost_interval']['mean_delta']:.4%}，准入={candidate['research_admission']}。减少动作修正不等于增加收益；保持30，不把强MPC回退算成RL提升。",
        "annual_twin": f"新增3/5年拟合窗、季节平衡残差、严格逐季选型和最差季区间。相同8新站：全年5→6/8、全年与四季同时4→5/8，但季度25→23/32且平均WIS增加。旧金山校准缺口、巴尔的摩过宽和基韦斯特Q4漏覆盖保留；45分不变。",
    }
    baseline_path = "data/evaluation/xiaoyi_capability_scorecard_v8_20261031.json"
    scorecard = copy.deepcopy(read(baseline_path))
    scorecard.update(
        schema="xiaoyi-capability-scorecard.v9",
        baseline={"path": baseline_path, "sha256": sha(ROOT / baseline_path)},
        scope="三项优先能力完成代码改进与冻结新港/新站实测，其余34项保留V8评分；不声称三个科学问题已全部解决。",
    )
    for c in scorecard["components"]:
        c["previous_score"] = c["score"]
        c["round_status"] = "本轮未专项改动，沿用V8证据"
        c["score_change_reason"] = reasons.get(
            c["id"], "沿用V8评分，本轮未作该能力独立业务复验，不因共用回归通过而加分。"
        )
        if c["id"] in reasons:
            c["round_status"] = "已改进并实测；按完整证据判断是否加分"
            evidence = {"forecast": forecast_path, "annual_twin": annual_path, "rl_policy": rl_path}[c["id"]]
            c["evidence"].append(evidence)
            c["evidence_inventory"].append(
                {
                    "path": evidence,
                    "exists": True,
                    "sha256_at_review": sha(ROOT / evidence),
                    "notice": "本轮冻结后新港/新站实测；保留失败",
                }
            )
        if c["id"] == "forecast":
            assert fm["aci90"]["joint_pass"] == 21 and qstats["aci90"]["passed"] == 42 and improvement > 0
            c["dimensions"]["功能覆盖"] = 4
            c["can_do"] = (
                "在已声明的公开日港口活动指标范围，执行1/7/14天分港区间、延迟自适应校准、宽度/漂移/滚动覆盖门禁；新7港逐季回放通过。"
            )
            c["boundary"] = (
                "点预测未变；平均区间更宽，自适应WIS未超过简单分港固定校准；无实时船期/ETA或历史实际发布时间验证。"
            )
            c["target"]["next"] = (
                "冻结混合/分层校准选型，在新港新时期同时检验WIS、季度覆盖和暂停比例；不得依已看过测试结果改选方法。"
            )
        elif c["id"] == "rl_policy":
            c["target"]["next"] = (
                "保留强MPC作为基准方案；先检验真实多资源耦合、作业切换与可行动作空间，再定义新的RL问题并冻结新的独立测试。"
            )
        elif c["id"] == "annual_twin":
            c["target"]["next"] = (
                "修复可核验的历史观测缺口；在独立开发集联合选型逐季宽度与覆盖，区分年度天文潮和天气驱动残差；冻结后用新站/新年复验。"
            )
        c["score"] = 5 * sum(c["dimensions"].values())
    score_path = ROOT / "data/evaluation/xiaoyi_capability_scorecard_v9_20261031.json"
    write(score_path, scorecard)
    components = {c["id"]: c for c in scorecard["components"]}
    verdicts = {
        "forecast": "覆盖和跨季稳定性改善；宽度代价明确",
        "rl_policy": "训练更贴近约束；相对收益仍未达标",
        "annual_twin": "部分全年改善；季度退化阻止整体升级",
    }
    refs = [
        {
            "title": "自适应共形推断：分布变化下的原始研究",
            "url": "https://proceedings.neurips.cc/paper_files/paper/2021/hash/0d441de75945e5acbc865406fc9a2559-Abstract.html",
        },
        {
            "title": "延迟多步反馈的自适应共形推断",
            "url": "https://proceedings.mlr.press/v230/hallberg-szabadvary24a.html",
        },
        {"title": "NOAA 谐波分潮说明", "url": "https://tidesandcurrents.noaa.gov/about_harmonic_constituents"},
        {
            "title": "NOAA 已验证小时高度接口与质量标记",
            "url": "https://api.tidesandcurrents.noaa.gov/api/dev/responseHelp.html",
        },
    ]
    summary = {
        "schema": "xiaoyi-priority-improvements.v9",
        "production_authority": False,
        "priorities": [
            {
                "id": k,
                "name": components[k]["name"],
                "previous_score": components[k]["previous_score"],
                "score": components[k]["score"],
                "verdict": verdicts[k],
            }
            for k in reasons
        ],
        "forecast": {
            "methods": f["summary"],
            "quarters_at_least_45_days": qstats,
            "wis_improvement_vs_v8": improvement,
            "qualification": "90%名义覆盖的自定研究下限80%，不是达到90%的保证或行业认证",
        },
        "annual": {
            "summary": a["summary"],
            "annual_and_all_quarters_pass": annual_joint,
            "mean_wis90_m": annual_wis,
            "promote_globally": False,
            "forecast_and_truth_joint_availability_is_not_raw_truth_availability": True,
        },
        "rl": {
            "candidate": candidate,
            "former": former,
            "selected_research_controller": candidate["matched_baseline"],
            "controller_role": "comparison_baseline_only_not_safety_qualified",
            "rl_promoted": candidate["research_admission"],
        },
        "references": refs,
        "all_three_limitations_resolved": False,
        "all_37_capabilities_upgraded": False,
        "limitations": [
            "公开归档事件时间回放，非历史实际发布时间；港口共享全球年份冲击",
            "年度为潮位分量，不是完整港口孪生",
            "自适应区间有上下界和延迟，不宣称原论文理论保证直接成立",
            "保留V6/V7/V8失败；新样本分母不得替换旧失败",
            "真实队列、资源能力、实时源及现场长期运行资格未改变",
        ],
    }
    write(OUT / "summary.json", summary)
    reports = {
        "scorecard": str(score_path.relative_to(ROOT)),
        "summary": str((OUT / "summary.json").relative_to(ROOT)),
        "forecast": forecast_path,
        "annual": annual_path,
        "rl": rl_path,
        "forecast_manifest": "data/public/interval_v9_20261031/manifest.json",
        "forecast_selection": "data/public/interval_v9_20261031/selection-before-test.json",
        "annual_selection": "data/public/annual_v9_20261031/selection-before-test.json",
    }
    sources = {}
    for p in [
        reports["forecast_selection"],
        reports["annual_selection"],
        ".runtime/rl-v9-20261031/selection-before-test.json",
    ]:
        sources.update(read(p)["source_sha256"])
    for p in ["app/harness/priority_v9.py", "web/priority-v9.html", "web/priority-v9.js", "web/capability-review.css"]:
        sources[p] = sha(ROOT / p)
    for entry in read(reports["forecast_manifest"])["entries"]:
        sources[entry["path"]] = entry["sha256"]
    write(
        ROOT / "config/priority_v9_registry.json",
        {
            "schema": "xiaoyi-priority-registry.v9",
            "sources": sources,
            "reports": {k: {"path": p, "sha256": sha(ROOT / p)} for k, p in reports.items()},
            "production_authority": False,
        },
    )
    docs = [
        "# 小懿三项优先能力提升 V9（2026-10-31）",
        "",
        "**完成三项代码改进、冻结选型、实际测试与评分更新；预测明显改善，RL净收益与年度全面稳定性仍未解决。**",
        "",
        "评分沿用37项五维0—4分×5量表。它是工程证据成熟度判断，不是全球排名、第三方认证或精度百分比。其余34项未因共享测试通过而加分。",
        "",
        "|能力|V8→V9|实际结论|",
        "|---|---:|---|",
    ]
    docs += [
        f"|{components[k]['name']}|{components[k]['previous_score']}→{components[k]['score']}|{reasons[k]}|"
        for k in reasons
    ]
    docs += [
        "",
        "## 预测：独立新港、日频、完整季度",
        "",
        "开发集为原8港2025年，比较7种固定/滚动/自适应方法；规则按季度失效数、WIS、宽度依次选型，冻结选择aci90。之后才提取7新港测试标签，回放2026-01-22至07-24，每港3个提前量，共3,864次；三方法都保留暂停预测。",
        "",
        "|方法|联合通过|≥45天季度通过|最差覆盖|平均归一宽度|归一WIS|允许研究|",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    docs += [
        f"|{method}|{v['joint_pass']}/{v['cells']}|{qstats[method]['passed']}/{qstats[method]['total']}|{v['worst_coverage']:.2%}|{v['mean_width']:.4f}|{v['mean_normalized_wis']:.6f}|{v['retained']}/{v['expected']}|"
        for method, v in fm.items()
    ]
    docs += [
        "",
        "名义90%区间的研究最低覆盖要求为80%，并非每个港口达到90%；最差覆盖86.41%。归一宽度2.0为平均门槛，逐次过宽仍暂停。简单分港固定校准平均WIS更低，但42个完整季度仅36通过；自适应42通过。冻结后不按测试集重新选赢家。",
        "",
        "点模型保持weekday84，未宣称点预测变准。新功能是分港残差尺度、90天滚动校准、一次且延迟的误差反馈、宽度与覆盖双门禁。5分仅对应此声明范围的功能闭环3→4；泛化3、运行成熟度1保持不变。",
        "",
        "方法参考[自适应共形推断原始论文]("
        + refs[0]["url"]
        + ")和[延迟多步反馈研究]("
        + refs[1]["url"]
        + ")。本实现有概率边界和发布延迟假设，未验证论文理论条件，不能套用无条件覆盖保证。",
        "",
        "## RL：安全约束纳入训练后仍不能超越强MPC",
        "",
        "先完成此前已冻结的V7：旧策略在其8新港上，无过滤相对强MPC退化0.6249%（港口簇95%区间−1.1572%至−0.0805%），共同过滤后收益为0。原始失败完整保留。",
        "",
        "V9对五个原始港口—年份块重采样分布重新做约束内Bellman训练；不是神经DQN，也不是MPC教师模仿。共6个模型含池化模型，均训练90步终端策略与28步随机MPC对照。共同安全约束、观测、成本、动作掩码均不放宽。",
        "",
        f"冻结强基线为 `{candidate['matched_baseline']}`，在另外8新港、每港2个90天窗、4情景上评估。候选相对收益{candidate['relative_cost_interval']['mean_delta']:.4%}，港口簇95%区间{candidate['relative_cost_interval']['port_cluster_ci95']}；研究准入={candidate['research_admission']}。",
        "",
        f"旧策略动作修正比例{former['override_fraction']:.2%}，约束内训练{candidate['override_fraction']:.2%}。这是策略与安全层一致性改善，不能计作成本收益；没有绕过强基线、改成本或把回退收益记给RL。保留冻结强MPC作为研究对照，V9候选不提升为默认RL策略。",
        f"90.83%的步骤可行集合只有0或1个动作；候选的最终执行动作与强随机MPC完全一致。可行窗口违规为0，但超过最大产能对照的违规仍为{candidate['excess_over_max_capacity']}次（五个重采样重复，基线单次为1）。候选和强基线都没有通过严格安全准入，不能把对照角色误称为现场可用方案。",
        "",
        "## 年度潮位：部分全年改善，跨季结果仍混合",
        "",
        "8个新NOAA站，历史2016–2024，2021/2022滚动选型，2023/2024校准；冻结后下载2025全年的真值。每方法8×8,760小时留痕，缺失不插值。对照在同一新站上复现V7规则，并非拿不同站点的通过率相比较。",
        "",
        f"全年：5/8→6/8；四季：25/32→23/32；全年且全部四季：4/8→5/8。平均WIS {annual_wis['legacy_v7_rule']:.6f}→{annual_wis['v9']:.6f} m，变差{annual_wis['v9'] / annual_wis['legacy_v7_rule'] - 1:.2%}。不作全局替换，45分保持。",
        "",
        "|站点|V9全年|季度通过|MAE m|覆盖|最大宽度 m|预测/真值齐备率|",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for c in a["cells"]:
        if c["method"] == "v9":
            v = c["annual"]
            docs.append(
                f"|{c['site']}|{v['passed']}|{sum(q['passed'] for q in c['quarters'].values())}/4|{v.get('mae_m', '—')}|{v.get('coverage90', '—')}|{v.get('max_width90_m', '—')}|{v['availability']:.2%}|"
            )
    docs += [
        "",
        "旧金山是2024校准季度合格样本不足，不能把表中预测/真值齐备率0解读成2025没有真值。独立复核另列原始真值可用率。巴尔的摩最差季区间0.9954m超过0.75m，不截窄伪装达标；基韦斯特Q4漏覆盖，虽全年通过仍暂停年度研究准入。",
        "",
        "年度天文潮采用[NOAA谐波分潮框架]("
        + refs[2]["url"]
        + ")；并不等于天气残差、风暴潮或完整港口作业孪生。NOAA hourly_height是已验证小时产品，质量字段与6分钟产品不同，按[官方响应说明]("
        + refs[3]["url"]
        + ")拒收推算/异常标记。早期解析器误要求q字段导致全拒收，失败快照保留于`data/public/annual_v9_20261031/rejected-parser-run/`；在下载测试年真值前修复，不改变统计门槛。",
        "",
        "## 实际使用与证据",
        "",
        "本机页面：<http://127.0.0.1:18018/web/priority-v9.html>。可重算7港预测、删除最新已公布观测检验暂停、重算24小时年度潮位、查看强MPC对照与37项评分并导出。年度门禁同时检查全年及四季；预测回执不返回未来真值。",
        "",
        "- `data/public/interval_v9_20261031/`：协议、冻结选型、7港源数据、全样本轨迹与报告。",
        "- `.runtime/rl-v9-20261031/`：六次模型训练、开发集选型、8新港轨迹与收益报告；原V7源码和结果不覆盖。",
        "- `data/public/annual_v9_20261031/`：NOAA原始响应、选型、完整全年两种方法的轨迹与报告。",
        "- `.codex_artifacts/priority-v9-20261031/independent-readback.json`：不用模型汇总函数复算指标、冻结摘要与数据获取时序。",
        "- `.codex_artifacts/priority-v9-20261031/acceptance.json`：最终工程测试与浏览器验收（完成后生成）。",
        "",
        "## 尚需解决",
        "",
        "预测继续联合优化覆盖与区间宽度；RL先定义真实多资源耦合及可行动作空间，新增标签前冻结新问题，避免重复调参追逐已看结果；年度分开处理天文潮和天气残差，在开发集联选季节区间并补充可核验观测。所有结论限公开归档、研究代理与本机工程；现场资格、真实收益及生产权限均未提高。",
    ]
    (ROOT / "docs/XIAOYI_PRIORITY_V9_20261031.md").write_text("\n".join(docs) + "\n")
    print(json.dumps(summary["priorities"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
