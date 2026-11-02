from dataclasses import asdict, replace
import unittest

from app.agent_training.environment_v3 import DynamicEnvironment, task_splits, teacher_action
from app.agent_training.environment_v4 import ReadableEnvironment
from scripts.run_agent_rl_v4 import CurriculumEnvironment, curriculum_splits, common_demonstrations


class ReadableCurriculumTests(unittest.TestCase):
    def test_prompt_is_factual_and_identical_despite_future_schedule(self):
        t = task_splits()["train"][0]
        a = ReadableEnvironment(t)
        b = ReadableEnvironment(replace(t, shocks=("port_revision", "lost_receipt")))
        self.assertEqual(a.prompt(), b.prompt())
        a.step("A")
        self.assertIn("已完成：港口读取", a.prompt())
        self.assertIn("能源状态尚未读取", a.prompt())
        before = a.prompt()
        a.step("A")
        self.assertEqual(before, a.prompt())

    def test_same_state_transitions_and_rewards_as_v3(self):
        for task in task_splits()["train"]:
            a, b = ReadableEnvironment(task), DynamicEnvironment(task)
            while not a.done:
                label = teacher_action(a)
                x, y = a.step(label), b.step(label)
                self.assertEqual(x["reward"], y["reward"])
                self.assertEqual(x["after"], y["after"])

    def test_prefixes_are_training_only_and_never_counted_as_model_actions(self):
        splits = curriculum_splits()
        keys = set()
        for task in splits["train"]:
            env = CurriculumEnvironment(task)
            keys.add(task.case_id)
            self.assertEqual(len(env.steps), len(task.initial_history))
            self.assertTrue(all(not r["model_action"] for r in env.steps))
            self.assertFalse(env.done)
            while not env.done:
                env.step(teacher_action(env))
            self.assertTrue(env.success)
        self.assertEqual(len(keys), len(splits["train"]))
        for split in ["validation", "test", "retention"]:
            self.assertTrue(all(not t.initial_history for t in splits[split]))

    def test_demos_and_oracle_replay_use_same_readable_state(self):
        from scripts.run_agent_rl_v4 import CurriculumTask

        demos = common_demonstrations([])
        self.assertEqual(len(demos), 109)
        for r in demos:
            env = CurriculumEnvironment(CurriculumTask(**r["task"]))
            for action in r["history"]:
                env.step(action)
            self.assertEqual(env.prompt(), r["prompt"])
            self.assertEqual(teacher_action(env), r["target"])
            self.assertFalse(asdict(env.task)["initial_history"])


if __name__ == "__main__":
    unittest.main()
