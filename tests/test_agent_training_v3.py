import copy
from dataclasses import replace
import random
import unittest

from app.agent_training.environment import LETTERS
from app.agent_training.environment_v3 import DynamicEnvironment, task_splits, teacher_action, demonstrations
from app.agent_training.objectives_v3 import centered_advantages


class DynamicContracts(unittest.TestCase):
    def test_teacher_completes_all_predeclared_splits(self):
        for tasks in task_splits().values():
            for task in tasks:
                env = DynamicEnvironment(task)
                while not env.done:
                    env.step(teacher_action(env))
                self.assertTrue(env.success, task)
                self.assertTrue(all(env.checks().values()))
                self.assertLessEqual(len(env.steps), 16)

    def test_compositions_separated(self):
        splits = task_splits()
        a, b, c = [{tuple(t.shocks) for t in splits[s]} for s in ["train", "validation", "test"]]
        self.assertFalse(a & b or a & c or b & c)

    def test_future_fault_not_leaked_into_observation(self):
        t = task_splits()["train"][0]
        a = DynamicEnvironment(t)
        b = DynamicEnvironment(replace(t, shocks=("port_revision", "lost_receipt")))
        self.assertEqual(a.observation(), b.observation())
        self.assertEqual(a.prompt(), b.prompt())

    def test_unknown_write_is_not_reissued(self):
        t = replace(task_splits()["train"][0], shocks=("lost_receipt",))
        env = DynamicEnvironment(t)
        while not env.uncertain:
            env.step(teacher_action(env))
        selected = env.steps[-1]["choice"]
        receipt = copy.deepcopy(env.receipts)
        self.assertEqual(teacher_action(env), "I")
        self.assertFalse(env.step(selected)["ok"])
        self.assertEqual(receipt, env.receipts)
        self.assertNotIn("energy", env.observation()["receipts"])

    def test_early_report_never_succeeds_and_random_actions_obey_grader(self):
        rng = random.Random(111)
        for tasks in task_splits().values():
            for task in tasks:
                env = DynamicEnvironment(task)
                self.assertFalse(env.step("J")["ok"])
                while not env.done:
                    env.step(rng.choice(LETTERS))
                if env.success:
                    self.assertTrue(all(env.checks().values()))

    def test_shaping_cannot_be_farmed_by_loops(self):
        task = task_splits()["train"][0]
        env = DynamicEnvironment(task)
        phi0 = env.progress()
        while not env.done:
            env.step("A")
        self.assertAlmostEqual(sum(r["reward_components"]["potential"] for r in env.steps), -0.5 * phi0)
        self.assertLess(sum(r["reward"] for r in env.steps), 0)

    def test_demo_replay_exact(self):
        for record in demonstrations(task_splits()["train"]):
            from app.agent_training.environment_v3 import DynamicTask

            env = DynamicEnvironment(DynamicTask(**record["task"]))
            for a in record["history"]:
                env.step(a)
            self.assertEqual(env.prompt(), record["prompt"])
            self.assertEqual(teacher_action(env), record["target"])

    def test_group_advantage(self):
        self.assertEqual(centered_advantages([0, 1, 2, 3]), [-1.5, -0.5, 0.5, 1.5])
        self.assertEqual(centered_advantages([2, 2, 2, 2]), [0, 0, 0, 0])


if __name__ == "__main__":
    unittest.main()
