"""Operator entry point for local port work orders and specialist evidence."""

import argparse
import json
import os
from pathlib import Path
import sys

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from app.harness.contracts import digest
from app.specialist_orders import (
    Gateway,
    ROLES,
    adjudicate,
    journal,
    run_order,
    verified_output,
)
from app.specialist_planner import WorkstationModel


def read_state(path, actor, key):
    state = json.loads(path.read_bytes())
    if state["actor"] != actor or state["key"] != key:
        raise ValueError("工单身份与本机归档不符")
    return state


def verify(state, gw):
    checked = {}
    originals = {}
    for step in state.get("plan", []):
        output = state["workers"].get(step["role"], {}).get("output")
        if not output:
            continue
        task = gw.task(output["task_id"])
        stored = state["workers"][step["role"]]["attempts"][-1]
        request = stored["request"]
        if (
            task["request_id"] != request["request_id"]
            or task["goal"] != request["goal"]
            or task["actor_id"] != state["actor"]
            or task["required_tools"] != [step["tool"]]
        ):
            raise ValueError("岗位任务与工单身份、范围或原始委托不一致")
        fresh = verified_output(gw, task, step, state["selection"])
        originals[step["role"]] = fresh
        if (
            state["schema"] == 1
            and fresh["tool"] == "knowledge.figures"
            and "figure_sha256" not in output["facts"]
        ):
            # The original schema stored the authenticated artifact digest; newer
            # readers additionally expose the image digest inside that artifact.
            fresh = {
                **fresh,
                "facts": {
                    k: v for k, v in fresh["facts"].items() if k != "figure_sha256"
                },
            }
        if fresh != output:
            raise ValueError("已归档岗位结果与主站原件不一致：" + step["role"])
        checked[step["role"]] = {"task": task["id"], "sha256": fresh["sha256"]}
    if not checked:
        raise ValueError("尚无已完成的岗位证据可复核")
    if state["status"] == "completed":
        roles = {s["role"] for s in state["plan"]}
        if (
            set(checked) != roles - {"management"}
            or adjudicate(originals, state["selection"]) != state["decision"]
        ):
            raise ValueError("工单裁决或岗位清单与复算不符")
        if "management" in roles and set(
            state["management"]["interpretation"]["references"]
        ) != set(checked):
            raise ValueError("管理意见缺少已验证的岗位来源")
    return checked


def main(args=None):
    parser = argparse.ArgumentParser(description="舷鸥 · 本机港航专业岗位工单")
    parser.add_argument(
        "action", choices=["run", "show", "verify", "reply", "retry", "negotiate"]
    )
    parser.add_argument("key", help="同一用户下可复用的工单编号")
    parser.add_argument("--goal", help="首次运行时给出业务目标")
    parser.add_argument("--goal-file", type=Path, help="UTF-8 纯文本业务目标")
    selection_args = parser.add_mutually_exclusive_group()
    selection_args.add_argument(
        "--selection", help="明确指定的历史策略参数 JSON（可选）"
    )
    selection_args.add_argument(
        "--selection-file", type=Path, help="UTF-8 历史策略参数 JSON 文件"
    )
    parser.add_argument(
        "--alternatives",
        choices=["initial", "trained", "all"],
        help="协商可用的替代方案：只审原提案、允许受训策略、另允许逐小时穷举",
    )
    parser.add_argument(
        "--use-memory", action="store_true", help="在岗位任务中启用当前用户已保存的记忆"
    )
    parser.add_argument("--text", help="向当前等待资料的岗位补充输入")
    parser.add_argument("--json", action="store_true", help="输出完整工单记录")
    if args is None:
        args = sys.argv[1:]
        if args and args[0].lower() == "team":
            args = args[1:]
    a = parser.parse_args(args)
    if a.goal is not None and a.goal_file is not None:
        parser.error("业务目标文本与文件只能选择一个")
    gw = Gateway("http://127.0.0.1:8010", os.getenv("XIAOYI_WORKORDER_TOKEN"))
    root = Path(
        os.environ.get("XIAOYI_WORKORDER_DIR", APP / ".runtime" / "specialist-orders")
    )
    if a.action == "negotiate":
        if a.goal or a.goal_file or a.use_memory or a.text:
            parser.error("历史策略协商接受 --selection-file 和 --alternatives")
        from app.policy_negotiation import negotiate

        selection = (
            a.selection_file.read_text(encoding="utf-8-sig")
            if a.selection_file
            else a.selection
        )
        state = negotiate(
            root,
            gw,
            WorkstationModel("http://127.0.0.1:11435/v1"),
            a.key,
            json.loads(selection) if selection else None,
            a.alternatives,
            notify=lambda v: print(v, file=sys.stderr, flush=True),
        )
        if a.json:
            print(json.dumps(state, ensure_ascii=False, indent=2))
        else:
            print(
                "协商裁决", state["decision"]["choice"], state["decision"]["decision"]
            )
            for rnd in state["rounds"]:
                print(
                    "第",
                    rnd["round"],
                    "轮",
                    rnd["choice"],
                    {r: v["failed"] for r, v in rnd["opinions"].items()},
                )
            print("归档", journal(root / "negotiations", gw.actor, a.key))
        return 0 if state["status"] == "completed" else 2
    if a.alternatives:
        parser.error("--alternatives 仅用于历史策略协商")
    path = journal(root, gw.actor, a.key)
    if a.action in ("show", "verify", "reply", "retry"):
        if not path.is_file():
            parser.error("未找到当前用户的工单编号")
        state = read_state(path, gw.actor, a.key)
        if a.action == "verify":
            print(json.dumps(verify(state, gw), ensure_ascii=False, indent=2))
            return 0
        if a.action == "show":
            print(json.dumps(state, ensure_ascii=False, indent=2))
            return 0
        if a.action == "reply":
            if (
                state.get("status") != "waiting_input"
                or not a.text
                or not a.text.strip()
            ):
                parser.error("reply 需要一个等待补充资料的工单以及 --text")
            tid = state["waiting_task"]
            gw.task(tid)
            gw.call(
                "/api/harness/tasks/" + tid + "/inputs",
                {
                    "text": a.text,
                    "request_id": "team-input-" + digest([tid, a.text])[:30],
                },
            )
        if a.action == "retry" and (not a.text or not a.text.strip()):
            parser.error("请用 --text 说明要重新核查的证据")
    goal = (
        a.goal_file.read_text(encoding="utf-8-sig").strip() if a.goal_file else a.goal
    )
    model = WorkstationModel("http://127.0.0.1:11435/v1")
    selection = (
        a.selection_file.read_text(encoding="utf-8-sig")
        if a.selection_file
        else a.selection
    )
    state = run_order(
        root,
        gw,
        model,
        a.key,
        goal,
        json.loads(selection) if selection else None,
        a.use_memory,
        notify=lambda v: print(v, file=sys.stderr, flush=True),
        retry_reason=a.text if a.action == "retry" else None,
    )
    if a.json:
        print(json.dumps(state, ensure_ascii=False, indent=2))
    else:
        print("工单", state["key"], state["status"])
        for step in state.get("plan", []):
            role = step["role"]
            if role == "management":
                continue
            worker = state["workers"].get(role, {})
            if worker.get("output"):
                o = worker["output"]
                print(ROLES[role][0], o["task_id"], o["result"], o["report"])
        if state.get("decision"):
            print("证据裁决", state["decision"]["decision"])
        if state.get("management"):
            print("管理岗", state["management"]["interpretation"]["summary"])
        if state.get("question"):
            print("等待补充", state["question"])
        print("归档", path)
    return 0 if state["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
