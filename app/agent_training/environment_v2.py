"""V2: explicit progress, bidirectional distractors, fully logged shaped reward.

V1 is deliberately untouched. Every comparison policy receives this same state
and tool menu. No next action or reward vector is disclosed in the prompt.
"""

from __future__ import annotations
import copy
from dataclasses import asdict
import random

from .environment import FAMILIES, LETTERS, TaskEnvironment, TaskSpec, digest, reference_action

REVISION = "xiaoyi-agent-env.v3-dense-progress"
NAMES = {"port": "港口", "energy": "能源", "traffic": "交通"}


def make_task_v2(split, family, index):
    seed = {"train": 511000, "validation": 622000, "test": 733000}[split] + FAMILIES.index(family) * 1000 + index
    rng = random.Random(seed)
    # Disjoint numerical grids, selected before any model evaluation.
    greens = {
        "train": [0.31, 0.43, 0.59, 0.71, 0.83],
        "validation": [0.37, 0.53, 0.79],
        "test": [0.29, 0.47, 0.61, 0.89],
    }[split]
    return TaskSpec(
        f"v2-{split}-{family}-{index:03d}",
        split,
        family,
        seed,
        green=rng.choice(greens),
        carbon=rng.choice([51, 78, 104, 129]) + {"train": 0, "validation": 4, "test": 7}[split],
        baseline=rng.choice([0.35, 0.5, 0.65]),
        scenario=rng.choice(["high_density_berthing", "channel_congestion", "equipment_degradation"]),
        fault={"read_recovery": "transient_read", "write_recovery": "lost_response"}.get(family, "none"),
    )


class ProgressEnvironment(TaskEnvironment):
    def _actions(self):
        actions = super()._actions()
        # Distractors can be above or below the requested value. Retain tool IDs
        # so the frozen SFT checkpoint remains a meaningful starting control.
        rng = random.Random(self.task.seed + 971)
        wrong_green = round(self.task.green + rng.choice([-1, 1]) * 0.13, 2)
        for key in ["E", "F"]:
            if actions[key]["arguments"]["green_preference"] != self.task.green:
                actions[key]["arguments"]["green_preference"] = wrong_green
        actions["L"]["arguments"]["carbon_price_cny_per_ton"] = self.task.carbon + rng.choice([-19, 19])
        return actions

    def progress(self):
        terms = [float(t in self.reads) for t in self.required["reads"]]
        if self.required["energy"]:
            receipt = self.receipts.get("energy", {})
            valid = receipt.get("green") == self.task.green and receipt.get("carbon") == self.task.carbon
            terms.append(float(valid) * (0.5 if self.uncertain else 1.0))
        if self.required["port"]:
            terms.append(float(self.receipts.get("port", {}).get("scenario") == self.task.scenario))
        if self.required["restore"]:
            terms += [float(self.ever_paused), float(self.restored and not self.paused)]
        terms.append(float(self.verified))
        return sum(terms) / len(terms)

    def signature(self):
        return (
            tuple(sorted(self.reads)),
            digest(self.receipts),
            self.verified,
            self.paused,
            self.ever_paused,
            self.restored,
            self.uncertain,
        )

    def pending(self):
        missing = [NAMES[t] + "状态尚未读取" for t in self.required["reads"] if t not in self.reads]
        if self.required["port"] and "port" not in self.receipts:
            missing.append("港口情景尚无评估结果")
        if self.required["energy"] and "energy" not in self.receipts:
            missing.append("能碳比较尚无匹配参数的结果")
        if self.uncertain:
            missing.append("已有写入结果尚未确认")
        if self.required["restore"]:
            if not self.ever_paused:
                missing.append("暂停实验尚未完成")
            if not self.restored:
                missing.append("原状态尚未恢复")
        if not self.verified:
            missing.append("结果尚未通过核验")
        if not self.success:
            missing.append("报告尚未交付")
        return missing

    def prompt(self):
        text = super().prompt()
        # Held-out wording is fixed before training. Numerical task semantics
        # and action contracts are unchanged for all comparison groups.
        phrasing = {
            "train": ["请处理以下请求：", "我的目标是：", "请完成这个任务："],
            "validation": ["现在需要你完成：", "本次工作要求："],
            "test": ["请替我办妥这件事：", "麻烦协助完成以下工作：", "本轮需要交付："],
        }.get(self.task.split, ["任务："])
        text = text.replace("任务：", phrasing[self.task.seed % len(phrasing)], 1)
        details = "任务缺项：" + "；".join(self.pending()) + "。"
        if self.last.startswith("parameter_mismatch") and self.steps:
            args = self.steps[-1]["action"]["arguments"]
            details += f"上次所选偏好{args['green_preference']:g}、碳价{args['carbon_price_cny_per_ton']:g}与目标不符。"
        # Facts only: do not give the model a correct action letter or reorder
        # candidates based on a hidden teacher policy.
        return text.replace("\n工具：", "\n" + details + "\n工具：")

    def step(self, label):
        progress_before, signature = self.progress(), self.signature()
        row = super().step(label)
        progress_after = self.progress()
        # Undiscounted finite-horizon potential shaping. Terminal potential=0
        # makes shaping telescope to zero over a complete episode.
        phi_after = 0.0 if self.done else progress_after
        components = {
            "potential_shaping": 2 * (phi_after - progress_before),
            "step_cost": -0.1,
            "invalid_action": -0.2 if not row["ok"] else 0.0,
            "no_progress": -0.2 if self.signature() == signature else 0.0,
            "terminal_success": 3.0 if self.success else 0.0,
            "budget_failure": -1.0 if self.done and not self.success else 0.0,
        }
        row.update(
            reward=round(sum(components.values()), 6),
            reward_components=components,
            progress_before=progress_before,
            progress_after=progress_after,
            potential_before=progress_before,
            potential_after=phi_after,
            environment_revision=REVISION,
            after=self.observation(),
        )
        return row


def counterfactuals(env):
    """Exact two-step simulator lookahead. No reference continuation or LLM calls."""
    branches = {}
    for label in LETTERS:
        child = copy.deepcopy(env)
        first = child.step(label)
        first["model_action"] = False
        first["origin"] = "counterfactual_environment_expansion"
        following = {}
        if not child.done:
            for second in LETTERS:
                transition = copy.deepcopy(child).step(second)
                transition["model_action"] = False
                transition["origin"] = "counterfactual_environment_expansion"
                following[second] = transition
        value = first["reward"] + max((row["reward"] for row in following.values()), default=0.0)
        branches[label] = {"first": first, "following": following, "two_step_return": value}
    return branches


def replay_state(record):
    env = ProgressEnvironment(TaskSpec(**record["task"]))
    for label in record["history"]:
        env.step(label)
    if env.done or env.prompt() != record["prompt"]:
        raise ValueError("training state is not reproducible")
    return env


def build_state_pool(tasks):
    records = {}

    def add(env, origin):
        if env.done:
            return
        prompt = env.prompt()
        key = digest(prompt)
        if key in records:
            return
        branches = counterfactuals(env)
        records[key] = {
            "state_id": key,
            "origin": origin,
            "task": asdict(env.task),
            "history": [s["choice"] for s in env.steps],
            "prompt": prompt,
            "rewards": [branches[k]["two_step_return"] for k in LETTERS],
            "immediate_rewards": [branches[k]["first"]["reward"] for k in LETTERS],
            "counterfactuals": branches,
            "sft_target": reference_action(env),
        }

    for task in tasks:
        env = ProgressEnvironment(task)
        while not env.done:
            add(env, "reference_path_state")
            # One invalid-action branch supplies recovery-state exposure to BOTH
            # RL and continued-SFT controls. RL never consumes sft_target.
            if len(env.steps) in {0, 1}:
                bad = copy.deepcopy(env)
                bad.step("J" if not env.verified else "A")
                add(bad, "failed_action_state")
            env.step(reference_action(env))
        if not env.success:
            raise AssertionError("competent reference baseline failed")
    return list(records.values())
