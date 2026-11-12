"""Three task tiers with shared tool semantics and an observable changing menu.

The future tier is a controlled interface/state-shift proxy, not a claim about
unknown future ports. No task's hidden event times or seed enter the prompt.
"""

from dataclasses import asdict, dataclass, replace
import random

from .environment import FAMILIES, LETTERS
from .environment_v3 import DynamicTask, teacher_action as canonical_teacher
from .environment_v4 import ReadableEnvironment

REVISION = "xiaoyi-tiered-tools.v1"
TIERS = ("simple", "complex", "future")


@dataclass(frozen=True)
class TieredTask(DynamicTask):
    tier: str = "simple"
    menu_seed: int = 0
    switch_step: int = 0
    timed_revisions: tuple = ()
    initial_history: tuple = ()


class TieredEnvironment:
    def __init__(self, task):
        self.task = task
        self.base = ReadableEnvironment(task)
        permutation = list(LETTERS)
        random.Random(task.menu_seed).shuffle(permutation)
        self.changed_mapping = dict(zip(LETTERS, permutation))
        for action in task.initial_history:
            row = self.step(action)
            row.update(model_action=False, origin="reference_prefix_for_training_initialization")
        if self.base.done:
            raise ValueError("initialization cannot already complete the task")

    def __getattr__(self, name):
        if name == "base":
            raise AttributeError(name)
        return getattr(self.base, name)

    def mapping(self):
        return (
            self.changed_mapping
            if self.task.menu_seed and len(self.base.steps) >= self.task.switch_step
            else dict(zip(LETTERS, LETTERS))
        )

    @property
    def actions(self):
        return {external: self.base.actions[canonical] for external, canonical in self.mapping().items()}

    def prompt(self):
        original = self.base.prompt()
        head, menu = original.split("\n工具：", 1)
        labels, suffix = menu.split("\n下一步", 1)
        inverse = {v: k for k, v in self.mapping().items()}
        transformed = [inverse[item[0]] + item[1:] for item in labels.split(";")]
        transformed.sort(key=lambda item: item[0])
        contract = "已更新" if self.task.menu_seed and len(self.base.steps) >= self.task.switch_step else "常规"
        return (
            head
            + "\n工具接口合同："
            + contract
            + "；以当前工具表为准。\n工具："
            + ";".join(transformed)
            + "\n下一步"
            + suffix
        )

    def step(self, label):
        mapping = self.mapping()
        before_potential = self.base.progress()
        row = self.base.step(mapping[label])
        row["choice"] = label
        row["environment_revision"] = REVISION
        events = []
        if not self.base.done:
            for at, system in self.task.timed_revisions:
                if at == len(self.base.steps):
                    if system not in self.base.current:
                        raise ValueError("revision targets a system outside the task")
                    self.base.current[system] += 1
                    self.base.verified = False
                    events.append({"type": "source_revision", "system": system})
                    self.base.last += "；" + system + "数据在外部更新，须按当前版本核验"
            if mapping != self.mapping():
                events.append({"type": "tool_contract_changed"})
                self.base.last += "；工具接口合同已更新，请读取当前工具表"
        if events:
            row["after"] = self.base.observation()
            row["feedback"] = self.base.last
            row["injected_event"] = True
            # Preserve the action's original error/cost terms; an external event
            # must not excuse an unrelated bad action.
            row["reward_components"]["potential"] = 0.5 * (
                (0 if self.base.done else self.base.progress()) - before_potential
            )
            row["reward"] = sum(row["reward_components"].values())
        row["external_events"] = events
        return row


def teacher_action(env):
    canonical = canonical_teacher(env.base)
    return next(external for external, internal in env.mapping().items() if internal == canonical)


def reference_path(task):
    env = TieredEnvironment(replace(task, initial_history=()))
    actions = []
    while not env.done:
        label = teacher_action(env)
        actions.append(label)
        env.step(label)
    if not env.success:
        raise ValueError("unsolved reference task: " + task.case_id)
    return actions


def task_splits(tier, *, seed=20261102):
    if tier not in TIERS:
        raise ValueError(tier)
    patterns = {
        "train": [
            (),
            ("read_timeout",),
            ("lost_receipt",),
            ("stale_cache", "port_revision"),
            ("read_timeout", "traffic_revision"),
            ("port_revision", "lost_receipt"),
        ],
        "validation": [("read_timeout", "lost_receipt"), ("stale_cache", "traffic_revision")],
        "test": [
            ("read_timeout", "stale_cache", "traffic_revision"),
            ("port_revision", "lost_receipt", "traffic_revision"),
            ("read_timeout", "port_revision", "lost_receipt"),
            ("stale_cache", "port_revision", "lost_receipt"),
        ],
    }
    result = {}
    for split, count, offset in [("train", 24, 1000), ("validation", 8, 2000), ("test", 24, 3000)]:
        rows = []
        for index in range(count):
            value = seed * 10000 + TIERS.index(tier) * 10000 + offset + index
            rng = random.Random(value)
            family = FAMILIES[index % len(FAMILIES)] if tier == "simple" else "joint"
            shocks = (
                {"read_recovery": ("read_timeout",), "write_recovery": ("lost_receipt",)}.get(family, ())
                if tier == "simple"
                else patterns[split][index % len(patterns[split])]
            )
            menu_seed, switch_step, timed = 0, 0, ()
            if tier == "future":
                # Two announced target contracts. Adaptation train/dev/test share
                # the contracts but use disjoint tasks and event timing. This
                # measures learning after a shift, not zero-shot unknown APIs.
                menu_seed = 601 + index % 2
                switch_step = {"train": 3, "validation": 4, "test": 2}[split]
                shocks = ("read_timeout",) if index % 2 else ("lost_receipt",)
                times = {"train": (3, 6), "validation": (4, 7), "test": (2, 5)}[split]
                timed = ((times[0], "port"), (times[1], "traffic"))
            rows.append(
                TieredTask(
                    case_id=f"tiered-{tier}-{split}-{index:02d}-{seed}",
                    split=split,
                    family=family,
                    seed=value,
                    green=round(rng.uniform(0.25, 0.9), 4),
                    carbon=rng.randint(40, 180),
                    scenario="high_density_berthing",
                    shocks=shocks,
                    require_restore=(family == "clock_restore" or tier != "simple" and index % 2 == 1),
                    max_steps=24,
                    tier=tier,
                    menu_seed=menu_seed,
                    switch_step=switch_step,
                    timed_revisions=timed,
                )
            )
        result[split] = rows
    result["retention"] = (
        [
            replace(
                t,
                case_id=t.case_id.replace("train", "retention"),
                split="retention",
                seed=t.seed + 8000,
                green=round(0.31 + i * 0.019, 4),
                carbon=61 + i,
            )
            for i, t in enumerate(task_splits("simple", seed=seed)["train"][:16])
        ]
        if tier != "simple"
        else [
            replace(
                t,
                case_id=t.case_id.replace("train", "retention"),
                split="retention",
                seed=t.seed + 8000,
                green=round(0.31 + i * 0.019, 4),
                carbon=61 + i,
            )
            for i, t in enumerate(result["train"][:16])
        ]
    )
    return result


def common_source_tasks(seed=20261102):
    rows = []
    for tier in TIERS:
        for index, task in enumerate(task_splits(tier, seed=seed)["train"]):
            # Source contracts differ from the two future adaptation contracts.
            rows.append(
                replace(
                    task,
                    case_id=task.case_id.replace("train", "common"),
                    split="train",
                    menu_seed=101 + index % 4 if tier == "future" else 0,
                )
            )
    return rows


def demonstrations(tasks):
    rows = []
    for task in tasks:
        env = TieredEnvironment(task)
        while not env.done:
            label = teacher_action(env)
            rows.append(
                {
                    "task": asdict(task),
                    "prompt": env.prompt(),
                    "target": label,
                    "history": [r["choice"] for r in env.steps],
                    "origin": "visible_state_reference",
                }
            )
            env.step(label)
        if not env.success:
            raise ValueError("reference did not complete " + task.case_id)
    return rows
