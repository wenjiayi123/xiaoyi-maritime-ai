"""Register immutable scientific results and evidence-based37component scores."""

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

from app.harness.physical_v2 import sha, write

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".codex_artifacts/research-v6-20261030"
REGISTRY = ROOT / "config/research_v6_evidence_registry.json"


def main():
    if REGISTRY.exists():
        raise ValueError("registration already exists; do not silently replace scientific evidence")
    learning_path = ROOT / ".runtime/rl-v6-20261030/report.json"
    physical_path = ROOT / "data/public/long_twin_v6_20261030/report.json"
    learning, physical = [json.loads(p.read_text()) for p in [learning_path, physical_path]]
    selected = next(r for r in learning["aggregate"] if r["algorithm"] == learning["selection"]["selected_rl"])
    assert json.loads((OUT / "independent-readback.json").read_text())["passed"]
    old_path = ROOT / "data/evaluation/xiaoyi_capability_scorecard_v5_20261030.json"
    score = copy.deepcopy(json.loads(old_path.read_text()))
    score.update(
        schema="xiaoyi-capability-scorecard.v6",
        assessed_at=datetime.now(timezone.utc).isoformat(),
        latest_acceptance=".codex_artifacts/research-v6-20261030/ACCEPTANCE.json",
        baseline={"path": str(old_path.relative_to(ROOT)), "sha256": sha(old_path)},
        current_stage="可复现离线研究与本地工程；RL额外收益、全季长期稳定性和现场闭环分别验收",
    )
    changes = {
        "rl_lab": (
            "运行成熟度",
            2,
            "40港跨年训练、5次港口年度块自助拟合、8个新港先封存再测试；完整模型、协议、原始与过滤动作和失败均可回放。提升研究运行成熟度，不提升有效收益评分。",
        ),
        "mpc": (
            "验证深度",
            4,
            "加入90步确定性MPC、使用同一经验误差均值的MPC和28步随机MPC；同成本、同观测时钟、同过滤器，实际独立算术回读。随机MPC共享Bellman求解器，未冒充外部独立实现。",
        ),
        "annual_twin": (
            "功能覆盖",
            3,
            f"从稀疏月初片段推进到完整365天8760小时及每季度验收；新8站全年{physical['annual']['passed']}/8，季度{physical['quarters']['passed']}/32；新晚期时段{physical['new_periods']['passed']}/16。只提升已具备的完整年度评估范围，仍不声称稳定全季通过。",
        ),
    }
    for row in score["components"]:
        row["previous_score"] = row["score"]
        row["score_change_reason"] = (
            "复核原有能力与本轮变化；没有足以提升该项五维成熟度的新证据，保留原分和未通过边界。"
        )
        if row["id"] in changes:
            dimension, value, reason = changes[row["id"]]
            row["dimensions"][dimension] = value
            row["score_change_reason"] = reason
        row["score"] = sum(row["dimensions"].values()) * 5
        if row["id"] in {"rl_lab", "rl_policy", "mpc", "annual_twin", "visual", "lineage", "audit", "container"}:
            row["evidence"] = list(dict.fromkeys([*row["evidence"], "config/research_v6_evidence_registry.json"]))
        if row["id"] == "annual_twin":
            row["can_do"] = (
                "冻结滚动年度选型和月度区间，再下载新站完整年度及新晚期时段真值；全部小时、缺测和四季分别评估。"
            )
            row["boundary"] = (
                f"新站完整年度{physical['annual']['passed']}/8，季度{physical['quarters']['passed']}/32；新晚期时段{physical['new_periods']['passed']}/16。覆盖、历史不足与真实缺测仍失败；纯天文模型不能预知年度异常海平面和风暴增水。"
            )
        if row["id"] == "rl_policy":
            row["boundary"] = (
                f"新八港相对开发集最强基线平均成本改善{selected['new_port_relative_cost_interval']['mean_delta'] * 100:.4f}%；准入{selected['research_admission']}，失败项：{'、'.join(selected['blockers'])}。旧集中收益和退化结果保留；仍无现场收益。"
            )
    score_path = ROOT / "data/evaluation/xiaoyi_capability_scorecard_v6_20261030.json"
    write(score_path, score)
    old_improvements = json.loads(
        (ROOT / "data/evaluation/xiaoyi_capability_improvements_v5_20261030.json").read_text()
    )
    improvements = copy.deepcopy(old_improvements)
    improvements.update(schema="xiaoyi-capability-improvements.v6", updated_at=datetime.now(timezone.utc).isoformat())
    for row in improvements["components"]:
        component = next(c for c in score["components"] if c["id"] == row["id"])
        row.update(
            score=component["score"], previous_score=component["previous_score"], remaining=component["boundary"]
        )
        if component["id"] in changes:
            row["change"] = component["score_change_reason"]
        elif component["id"] in {"visual", "lineage", "audit"}:
            row["change"] += (
                " 本轮补充新研究来源、失败原始响应下载、真实时间轴与缺测断线、五次拟合和完整年度证据；评分保留。"
            )
    improvement_path = ROOT / "data/evaluation/xiaoyi_capability_improvements_v6_20261030.json"
    write(improvement_path, improvements)
    reports = {
        "learning": learning_path,
        "physical": physical_path,
        "pilot": ROOT / ".runtime/rl-v6-20261030/pilot.json",
        "readback": OUT / "independent-readback.json",
        "scorecard": score_path,
        "improvements": improvement_path,
    }
    science_names = [
        "app/harness/rl_v6.py",
        "app/harness/long_twin_v6.py",
        "app/harness/crossport_v2.py",
        "app/harness/crossport_control.py",
        "app/harness/crossport_forecast.py",
        "app/harness/physical_v2.py",
        "app/harness/physical_v3.py",
        "app/harness/modelbased_v3.py",
        "app/harness/robust_v4.py",
        "data/public/rl_v6_20261030/protocol.json",
        "data/public/rl_v6_20261030/manifest.json",
        ".runtime/rl-v6-20261030/selection-before-test.json",
        ".runtime/rl-v6-20261030/empirical-transition-model.json",
        "data/public/long_twin_v6_20261030/protocol.json",
        "data/public/long_twin_v6_20261030/history-manifest.json",
        "data/public/long_twin_v6_20261030/test-manifest.json",
        "data/public/long_twin_v6_20261030/selection-before-test.json",
    ]
    write(
        REGISTRY,
        {
            "schema": "xiaoyi-research-evidence.v6",
            "registered_at": datetime.now(timezone.utc).isoformat(),
            "reports": {k: {"path": str(p.relative_to(ROOT)), "sha256": sha(p)} for k, p in reports.items()},
            "scientific_sources": {p: sha(ROOT / p) for p in science_names},
            "production_authority": False,
        },
    )
    # Preserve prior score files; only the current pointers move forward.
    for name in ["config/remediation_v4_evidence_registry.json", "config/proof_evidence_registry.json"]:
        path = ROOT / name
        (OUT / (path.stem + "-before-v6.json")).write_bytes(path.read_bytes())
        registry = json.loads(path.read_text())
        registry["reports"]["scorecard"] = {"path": str(score_path.relative_to(ROOT)), "sha256": sha(score_path)}
        if "improvements" in registry["reports"]:
            registry["reports"]["improvements"] = {
                "path": str(improvement_path.relative_to(ROOT)),
                "sha256": sha(improvement_path),
            }
        write(path, registry)
    print(
        json.dumps(
            {
                "score_changes": [
                    {"name": r["name"], "before": r["previous_score"], "after": r["score"]}
                    for r in score["components"]
                    if r["score"] != r["previous_score"]
                ],
                "rl_admitted": selected["research_admission"],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
