"""Same V3 transitions, with explicit factual progress and a stable prompt.

No next-action labels, hidden event schedule, or teacher recommendations are
shown. The harness enforces a fixed step cap; remaining budget is logged but
omitted from the model input so repeated identical states reuse exact caches.
"""

from .environment_v3 import DynamicEnvironment, NAMES

REVISION = "xiaoyi-dynamic-tools.v2-readable-progress"


class ReadableEnvironment(DynamicEnvironment):
    def step(self, label):
        row = super().step(label)
        row["environment_revision"] = REVISION
        return row

    def prompt(self):
        original = super().prompt()
        goal, _, tail = original.partition("\n")
        menu = tail[tail.index("工具：") :]
        completed, missing, versions = [], [], []
        for key, version in self.current.items():
            seen = self.observed.get(key)
            versions.append(f"{NAMES[key]}当前{version}/已读{seen if seen is not None else '无'}")
            if seen == version:
                completed.append(NAMES[key] + "读取")
            else:
                missing.append(NAMES[key] + ("状态尚未读取" if seen is None else "读取版本已过期"))
        for key, title in [("port", "港口情景评估"), ("energy", "能碳参数比较")]:
            if not self.required[key]:
                continue
            receipt = self.receipts.get(key)
            if key == "energy" and self.uncertain:
                missing.append("已有能碳写入结果尚未确认")
            elif receipt and receipt.get("version") == self.current[key]:
                completed.append(title)
            else:
                missing.append(title + ("结果已过期" if receipt else "尚无结果"))
        if self.required["restore"]:
            if self.ever_paused:
                completed.append("暂停模拟时钟")
            else:
                missing.append("暂停实验尚未完成")
            if self.restored and not self.paused:
                completed.append("恢复原时钟")
            else:
                missing.append("原状态尚未恢复")
        if self.verified:
            completed.append("全部结果核验")
        else:
            missing.append("结果尚未通过核验")
        missing.append("报告尚未交付")
        return (
            goal
            + "\n已完成："
            + ("、".join(completed) or "无")
            + "。"
            + "当前时钟："
            + ("暂停" if self.paused else "运行")
            + "。"
            + "结果核验："
            + ("已通过" if self.verified else "尚未通过")
            + "。"
            + "执行结果不明："
            + ("是，需读回回执" if self.uncertain else "否")
            + "。\n"
            + "任务缺项："
            + "；".join(missing)
            + "。\n数据版本："
            + "；".join(versions)
            + "。最近反馈："
            + self.last
            + "。\n"
            + menu
        )
