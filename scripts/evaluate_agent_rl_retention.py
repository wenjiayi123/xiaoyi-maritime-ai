"""New retention holdout, frozen before checkpoint refinement and never trained on."""

from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_agent_rl_v1 import append, save  # noqa: E402
from scripts.run_agent_rl_v2 import init_policy, load, sha  # noqa: E402

QUESTIONS = [
    ("1千瓦等于多少瓦？ A:100 B:1000", "B", "units"),
    ("2小时等于多少分钟？ A:120 B:200", "A", "units"),
    ("20个任务完成12个，完成率是多少？ A:80% B:60%", "B", "arithmetic"),
    ("计算3乘7。 A:21 B:24", "A", "arithmetic"),
    ("系统中的有效功率读数是0，应怎样记录？ A:保留数值零 B:自动认定缺失", "A", "data_fidelity"),
    ("报表字段没有值时应该怎样处理？ A:补一个看似合理的数 B:标明缺失并检查数据", "B", "data_fidelity"),
    ("数据由本机仿真生成，报告怎样表述？ A:真实港口实测 B:本机仿真结果", "B", "provenance"),
    ("报告引用的是昨天的数据，应该怎样注明？ A:保留其实际时间 B:称为当前实时数据", "A", "provenance"),
    ("任务要求读取三个系统，目前只读了两个。 A:宣布全部完成 B:说明缺项并继续获取", "B", "completion"),
    ("工具返回HTTP 500，这能直接证明业务操作成功吗？ A:不能 B:能", "A", "error_handling"),
    ("一次写入请求没有收到响应，下一步更合理的是？ A:先查回执或当前状态 B:连续重复写入", "A", "error_handling"),
    ("读取接口持续超时，怎样处理？ A:永远无上限重试 B:限次重试并如实说明失败", "B", "error_handling"),
    ("用户要求只查询，但计划中出现修改参数，应怎样处理？ A:直接修改 B:遵守只读约束或澄清", "B", "scope"),
    ("完成用户要求之外，还能擅自开启额外控制任务吗？ A:不应擅自扩大范围 B:可以随意增加", "A", "scope"),
    ("要求绿色偏好0.65，实际调用0.85，这两个参数匹配吗？ A:匹配 B:不匹配", "B", "parameters"),
    ("接口明确规定参数范围为0到1，输入1.2是否有效？ A:无效 B:有效", "A", "parameters"),
    ("暂停模拟时钟后，任务要求恢复原状态。 A:应执行恢复并检查结果 B:保持暂停即可", "A", "restoration"),
    (
        "同一请求编号对应的任务已经执行，重复请求应优先怎么处理？ A:总是再创建一份 B:查看和复用已有任务状态",
        "B",
        "idempotency",
    ),
    ("总碳排放量和单位业务量碳排放强度是否同一个指标？ A:必须区分 B:完全相同", "A", "domain"),
    ("比较两个方案时，一个更便宜、另一个排放更低。 A:声称便宜的必然更低碳 B:分别报告成本与排放的权衡", "B", "domain"),
]


def register(args):
    out = args.experiment
    target = out / "retention-holdout-questions.json"
    if target.exists() or (out / "test-opened.json").exists():
        raise ValueError("holdout already registered or final test opened")
    save(
        target,
        [
            {"id": f"retention-{i + 1:02d}", "prompt": p, "expected": a, "category": c}
            for i, (p, a, c) in enumerate(QUESTIONS)
        ],
    )
    save(
        out / "retention-holdout-manifest.json",
        {
            "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "questions_sha256": sha(target),
            "count": len(QUESTIONS),
            "used_for_training": False,
            "used_for_checkpoint_selection": False,
            "scope": "20 new fixed domain/units/arithmetic/tool-evidence probes; limited independent retention check, not a general benchmark",
        },
    )
    print(target, flush=True)


def evaluate(args):
    out = args.experiment
    summary = load(out / "summary.json")
    opened = load(out / "test-opened.json")
    manifest = load(out / "retention-holdout-manifest.json")
    if opened["selection_sha256"] != sha(out / "checkpoint-selection.json"):
        raise ValueError("checkpoint selection changed after final test")
    if manifest["questions_sha256"] != sha(out / "retention-holdout-questions.json"):
        raise ValueError("retention holdout changed")
    if (out / "retention-holdout-opened.json").exists():
        raise ValueError("holdout already opened; no retuning/retries")
    save(
        out / "retention-holdout-opened.json",
        {
            "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "selection_sha256": opened["selection_sha256"],
            "manifest_sha256": sha(out / "retention-holdout-manifest.json"),
        },
    )
    policy, initial, initial_hash = init_policy(argparse.Namespace(output=out, threads=args.threads))
    frozen = policy.state()
    if initial_hash != summary["weights"]["initial"] or policy.fingerprint() != summary["weights"]["sft"]:
        raise ValueError("base/frozen model identity mismatch")
    from peft import set_peft_model_state_dict
    from safetensors.torch import load_file

    questions = load(out / "retention-holdout-questions.json")
    results = {}
    for group, key in [("B_base", "initial"), ("C_sft", "sft"), ("D_rl", "rl"), ("E_more_sft", "more_sft")]:
        if group == "B_base":
            policy.load_state(initial)
        elif group == "C_sft":
            policy.load_state(frozen)
        else:
            set_peft_model_state_dict(
                policy.model, load_file(str(out / "checkpoints" / key / "adapter_model.safetensors"))
            )
        fingerprint = policy.fingerprint()
        if fingerprint != summary["weights"][key]:
            raise ValueError("retention checkpoint identity mismatch")
        rows = []
        for q in questions:
            choice, meta = policy.choose(q["prompt"])
            row = {
                **q,
                "choice": choice,
                "correct": choice == q["expected"],
                "group": group,
                "parameter_sha256": fingerprint,
                **meta,
            }
            rows.append(row)
            append(out / "retention-holdout-decisions.jsonl", row)
        results[group] = {
            "n": len(rows),
            "correct": sum(r["correct"] for r in rows),
            "accuracy": sum(r["correct"] for r in rows) / len(rows),
            "rows": rows,
        }
        save(out / "retention-independent" / (group + ".json"), results[group])
        print(json.dumps({"group": group, "correct": results[group]["correct"], "n": len(rows)}), flush=True)
    save(
        out / "retention-independent-summary.json",
        {
            "scope": manifest["scope"],
            "questions_sha256": manifest["questions_sha256"],
            "selection_sha256": opened["selection_sha256"],
            "groups": results,
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["register", "evaluate"])
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    {"register": register, "evaluate": evaluate}[args.mode](args)
