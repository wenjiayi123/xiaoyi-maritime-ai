"""Versioned, resettable multi-tool tasks. Synthetic, never live dispatch.

All policies get the same visible version numbers and tool contracts. Fault
schedule is private; the rule/SFT teacher uses only the published observation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import random

from .environment import FAMILIES, TaskEnvironment, TaskSpec, digest

REVISION = "xiaoyi-dynamic-tools.v1"
NAMES = {"port": "港口", "energy": "能源", "traffic": "交通"}


@dataclass(frozen=True)
class DynamicTask(TaskSpec):
    shocks: tuple = ()
    require_restore: bool = False
    max_steps: int = 20


class DynamicEnvironment:
    def __init__(self, task):
        self.task = task
        template = TaskEnvironment(task)
        self.actions = template.actions
        self.required = dict(template.required, restore=task.require_restore)
        self.current = {k: 1 for k in self.required["reads"]}
        self.observed = {}
        self.receipts = {}
        self.triggered = set()
        self.uncertain = False
        self.verified = False
        self.paused = self.ever_paused = self.restored = False
        self.last = "无"
        self.steps = []
        self.done = self.success = False
        self.report = None

    def observation(self):
        # The scenario's future fault schedule is deliberately absent.
        return {
            "required": self.required,
            "current_versions": self.current.copy(),
            "observed_versions": self.observed.copy(),
            "receipts": {k: dict(v) for k, v in self.receipts.items()}
            if not self.uncertain
            else {k: dict(v) for k, v in self.receipts.items() if k != "energy"},
            "uncertain_write": self.uncertain,
            "verified": self.verified,
            "paused": self.paused,
            "ever_paused": self.ever_paused,
            "restored": self.restored,
            "last": self.last,
            "remaining_steps": self.task.max_steps - len(self.steps),
        }

    def checks(self):
        e, p = self.receipts.get("energy", {}), self.receipts.get("port", {})
        return {
            "fresh_reads": all(self.observed.get(k) == v for k, v in self.current.items()),
            "energy": not self.required["energy"]
            or (
                e.get("version") == self.current["energy"]
                and e.get("green") == self.task.green
                and e.get("carbon") == self.task.carbon
                and not self.uncertain
            ),
            "port": not self.required["port"]
            or (p.get("version") == self.current["port"] and p.get("scenario") == self.task.scenario),
            "restore": not self.required["restore"] or (self.ever_paused and self.restored and not self.paused),
            "known_write": not self.uncertain,
            "verified": self.verified,
        }

    def progress(self):
        c = self.checks()
        return sum(c.values()) / len(c)

    def prompt(self):
        names = {
            "energy.pause": "暂停模拟时钟",
            "energy.restore": "恢复原时钟",
            "execution.verify": "读回回执并核验全部结果",
            "artifact.report": "交付报告",
            "execution.diagnose": "诊断接口",
            "task.ask": "询问用户",
        }
        menu = []
        for letter, a in self.actions.items():
            tool, args = a["tool"], a["arguments"]
            if tool.endswith(".read"):
                desc = "读取" + NAMES[tool.split(".")[0]]
            elif tool == "energy.compare":
                desc = f"能碳比较(偏好{args['green_preference']:g},碳价{args['carbon_price_cny_per_ton']:g})"
            elif tool == "port.evaluate":
                desc = "港口评估(" + args["scenario"] + ")"
            else:
                desc = names[tool]
            menu.append(letter + "=" + desc)
        status = []
        for k, v in self.current.items():
            status.append(f"{NAMES[k]}当前版本{v}/已读{self.observed.get(k, '无')}")
        for k in ["port", "energy"]:
            if self.required[k]:
                receipt = self.receipts.get(k)
                status.append(
                    NAMES[k]
                    + "计算回执="
                    + (
                        "待读回"
                        if k == "energy" and self.uncertain
                        else f"版本{receipt['version']}"
                        if receipt
                        else "无"
                    )
                )
        status += [
            "核验=" + ("通过" if self.verified else "未通过"),
            f"时钟={'暂停' if self.paused else '运行'}/曾暂停={self.ever_paused}/已恢复={self.restored}",
        ]
        goal = self.task.goal()
        if self.required["restore"]:
            goal += "另需暂停模拟时钟并恢复原状态。"
        return (
            "任务："
            + goal
            + "所有读取和计算须与当前版本一致，变化后须更新。\n"
            + "；".join(status)
            + f"。反馈：{self.last}。剩余{self.task.max_steps - len(self.steps)}步。\n"
            + "工具："
            + ";".join(menu)
            + "\n下一步只输出一个字母："
        )

    def _fire(self, shock):
        if shock in self.task.shocks and shock not in self.triggered:
            self.triggered.add(shock)
            return True
        return False

    def step(self, label):
        if self.done:
            raise RuntimeError("episode ended")
        a = self.actions[label]
        tool, args = a["tool"], a["arguments"]
        before = self.observation()
        phi = self.progress()
        signature = digest({k: v for k, v in before.items() if k not in {"last", "remaining_steps"}})
        ok, injected, result = True, False, {}
        if tool.endswith(".read"):
            k = tool.split(".")[0]
            if k not in self.current:
                ok, self.last = False, "该读取不在任务范围"
            elif k == "energy" and self._fire("read_timeout"):
                ok, injected, self.last = False, True, "能源读取超时，可重试只读请求"
            else:
                version = self.current[k]
                if k == "port" and self._fire("stale_cache"):
                    version -= 1
                    injected = True
                changed = self.observed.get(k) != version
                self.observed[k] = version
                if changed:
                    self.verified = False
                self.last = f"{NAMES[k]}读取版本{version}，当前版本{self.current[k]}"
                result = {"source": "synthetic_versioned_state", "version": version}
        elif tool in {"energy.compare", "port.evaluate"}:
            k = tool.split(".")[0]
            if not self.required[k]:
                ok, self.last = False, "任务未要求此计算"
            elif k == "energy" and self.uncertain:
                ok, self.last = False, "上次写入结果不明，须先读回回执"
            elif self.observed.get(k) != self.current.get(k):
                ok, self.last = False, "输入未读或版本过期"
            elif k == "energy" and (
                args["green_preference"] != self.task.green or args["carbon_price_cny_per_ton"] != self.task.carbon
            ):
                ok, self.last = False, "比较参数与用户要求不一致"
            else:
                result = {"version": self.observed[k], "request_id": f"{self.task.case_id}-{k}-{self.observed[k]}"}
                result.update(
                    {"green": self.task.green, "carbon": self.task.carbon}
                    if k == "energy"
                    else {"scenario": self.task.scenario}
                )
                self.receipts[k] = dict(result)
                self.verified = False
                self.last = NAMES[k] + "计算完成"
                if k == "energy" and self._fire("lost_receipt"):
                    self.uncertain = True
                    ok, injected, self.last = False, True, "请求已发送但响应丢失，执行结果未知"
                    result = {"response_received": False}
                if k == "port" and self._fire("port_revision"):
                    self.current[k] += 1
                    injected = True
                    self.last += "；港口条件已更新，当前版本2"
        elif tool == "energy.pause":
            if not self.required["restore"] or self.observed.get("energy") != self.current.get("energy") or self.paused:
                ok, self.last = False, "暂停前置条件不满足"
            else:
                self.paused = self.ever_paused = True
                self.restored = self.verified = False
                self.last = "模拟时钟已暂停，需恢复"
        elif tool == "energy.restore":
            if not self.paused:
                ok, self.last = False, "无本任务待恢复的暂停"
            else:
                self.paused, self.restored, self.verified = False, True, False
                self.last = "原时钟已恢复"
        elif tool == "execution.verify":
            self.uncertain = False
            if self._fire("traffic_revision"):
                self.current["traffic"] += 1
                injected = True
            self.verified = True
            self.verified = all(self.checks().values())
            ok = self.verified
            self.last = "全部结果核验通过" if ok else "回执已读回；核验未通过，版本、计算或恢复存在缺项"
            result = {"checks": self.checks()}
        elif tool == "artifact.report":
            if all(self.checks().values()):
                self.done = self.success = True
                self.last = "报告已交付"
                self.report = {
                    "goal": self.task.goal(),
                    "receipts": self.receipts,
                    "checks": self.checks(),
                    "source": "synthetic_training",
                    "production_authority": False,
                }
                result = {"report_sha256": digest(self.report)}
            else:
                ok, self.last = False, "报告拒绝：证据不完整或版本不一致"
        elif tool == "execution.diagnose":
            self.last = "接口正常；只读可重试，未知写入需读回；当前版本见状态"
        else:
            self.last = "用户：参数已经给出，请继续"
        if len(self.steps) + 1 >= self.task.max_steps:
            self.done = True
        after = self.observation()
        new_sig = digest({k: v for k, v in after.items() if k not in {"last", "remaining_steps"}})
        components = {
            "success": 3.0 if self.success else 0.0,
            "failed_terminal": -1.0 if self.done and not self.success else 0.0,
            "step_cost": -0.02,
            "avoidable_error": -0.1 if not ok and not injected else 0.0,
            "no_progress": -0.05 if signature == new_sig and not injected else 0.0,
            "potential": 0.5 * ((0.0 if self.done else self.progress()) - phi),
        }
        row = {
            "step": len(self.steps) + 1,
            "choice": label,
            "action": a,
            "observation": before,
            "after": after,
            "ok": ok,
            "injected_event": injected,
            "result": result,
            "feedback": self.last,
            "reward_components": components,
            "reward": sum(components.values()),
            "environment_revision": REVISION,
            "model_action": True,
        }
        self.steps.append(row)
        row["after"]["remaining_steps"] = self.task.max_steps - len(self.steps)
        return row


def teacher_action(env):
    """Competent rules baseline; only sees the same observable facts as the LLM."""
    o = env.observation()
    if o["uncertain_write"]:
        return "I"
    for k, v in o["current_versions"].items():
        if o["observed_versions"].get(k) != v:
            return {"port": "A", "energy": "B", "traffic": "C"}[k]
    for k in ["port", "energy"]:
        if o["required"][k] and o["receipts"].get(k, {}).get("version") != o["current_versions"][k]:
            if k == "port":
                return "D"
            return next(
                c
                for c, a in env.actions.items()
                if a["tool"] == "energy.compare"
                and a["arguments"]["green_preference"] == env.task.green
                and a["arguments"]["carbon_price_cny_per_ton"] == env.task.carbon
            )
    if o["required"]["restore"]:
        if not o["ever_paused"]:
            return "G"
        if o["paused"]:
            return "H"
    return "J" if o["verified"] else "I"


def task_splits():
    """Fixed before training. Test compositions never occur in train/validation."""
    singles = [(), ("read_timeout",), ("stale_cache",), ("port_revision",), ("lost_receipt",), ("traffic_revision",)]
    val = [("read_timeout", "lost_receipt"), ("stale_cache", "port_revision")]
    test = [
        ("read_timeout", "port_revision"),
        ("lost_receipt", "traffic_revision"),
        ("stale_cache", "lost_receipt"),
        ("port_revision", "traffic_revision"),
        ("read_timeout", "stale_cache", "traffic_revision"),
        ("port_revision", "lost_receipt", "traffic_revision"),
    ]
    result = {}
    for split, patterns, count, offset in [
        ("train", singles, 2, 810000),
        ("validation", val, 2, 820000),
        ("test", test, 2, 830000),
        ("retention", [()], 6, 840000),
    ]:
        tasks = []
        for i, pattern in enumerate(patterns):
            for j in range(count):
                seed = offset + i * 100 + j
                rng = random.Random(seed)
                # Joint goals keep the business outcome fixed as disturbances vary.
                tasks.append(
                    DynamicTask(
                        f"v3-{split}-{i:02d}-{j:02d}",
                        split,
                        "joint",
                        seed,
                        green=round(rng.uniform(0.3, 0.9), 3),
                        carbon=rng.randint(45, 145),
                        shocks=pattern,
                        require_restore=bool(j % 2),
                    )
                )
        result[split] = tasks
    # Fresh numbers across all eight old business families. This partition is
    # sealed during the pilot, not a training anchor or checkpoint selector.
    result["retention"] = [
        DynamicTask(
            f"v3-retention-{family}-{j}",
            "retention",
            family,
            850000 + i * 100 + j,
            green=0.327 + 0.051 * j,
            carbon=69 + 7 * j,
            shocks={"read_recovery": ("read_timeout",), "write_recovery": ("lost_receipt",)}.get(family, ()),
            require_restore=family == "clock_restore",
        )
        for i, family in enumerate(FAMILIES)
        for j in range(2)
    ]
    return result


def demonstrations(tasks):
    records = []
    for task in tasks:
        env = DynamicEnvironment(task)
        while not env.done:
            letter = teacher_action(env)
            records.append(
                {
                    "task": asdict(task),
                    "prompt": env.prompt(),
                    "target": letter,
                    "history": [r["choice"] for r in env.steps],
                    "origin": "visible_state_rule_teacher",
                }
            )
            env.step(letter)
        if not env.success:
            raise AssertionError("rule baseline failed a solvable task")
    return records
