import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from app.agent_training.environment_tiered import task_splits
from scripts import run_agent_rl_confirmatory as formal
from scripts import analyze_agent_rl_confirmatory as analysis


class FormalContracts(unittest.TestCase):
    def test_budget_and_no_split_overlap(self):
        for seed in formal.SEEDS:
            order = formal.schedule(seed)
            self.assertEqual(sorted(order), list(range(48)))
            self.assertEqual(sum(x < 24 for x in order[:24]), 12)
        for tier in formal.TIERS:
            splits = task_splits(tier)
            groups = [{t.case_id for t in splits[s]} for s in ["train", "validation", "test", "retention"]]
            for i, a in enumerate(groups):
                for b in groups[i + 1:]:
                    self.assertFalse(a & b)

    def test_bootstrap_pairs_seeds_and_keeps_parameter_variants_clustered(self):
        from dataclasses import asdict
        tasks = [asdict(t) for t in task_splits("complex")["test"]]
        zero = analysis.interval(np.zeros((3, len(tasks))), tasks, replicates=100)
        self.assertEqual(zero["interval_97_5"], [0, 0])
        constant = analysis.interval(np.ones((3, len(tasks))) * 0.25, tasks, replicates=100)
        self.assertEqual(constant["mean_lift"], 0.25)
        self.assertLess(constant["scenario_clusters"], len(tasks))
        negative = analysis.interval(np.ones((3, len(tasks))) * -0.25, tasks, replicates=100)
        self.assertLess(negative["interval_97_5"][1], 0)

    def test_test_access_requires_all_training_and_audits(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(formal, "verify"):
                with self.assertRaises(FileNotFoundError):
                    formal.evaluate_seed(Path(tmp), formal.SEEDS[0])
            self.assertFalse((Path(tmp) / "FINAL_TEST_OPENED.json").exists())

    def test_formal_child_is_stopped_before_queue_can_restore_inference(self):
        from unittest.mock import Mock
        proc = Mock()
        proc.pid = 123
        proc.poll.side_effect = [None, None]
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "PAUSE").touch()
            with patch.object(formal.subprocess, "Popen", return_value=proc):
                with self.assertRaisesRegex(RuntimeError, "pause requested"):
                    formal.child(base, ["fake"], "child.log", stage="audit")
            proc.send_signal.assert_called_once_with(formal.signal.SIGINT)
            proc.wait.assert_called_once()


class NumericalFormalPipeline(unittest.TestCase):
    def test_both_groups_resume_without_replay_or_heldout_calls(self):
        try:
            import torch
        except ImportError:
            self.skipTest("numerical test is run separately in .venv-lora")
        from app.agent_training.environment import LETTERS
        run = formal.core

        class FakePolicy:
            def __init__(self, **kwargs):
                self.torch = torch
                self.weight = torch.nn.Parameter(torch.zeros(13))
                self.parameters = [self.weight]
                self.cache_stats = {}

            def state(self):
                return {"weight": self.weight.detach().clone()}

            def load_state(self, state):
                with torch.no_grad():
                    self.weight.copy_(state["weight"])

            def fingerprint(self):
                return hashlib.sha256(self.weight.detach().numpy().tobytes()).hexdigest()

            def logits(self, prompt):
                return self.weight * 1.0

            def verify_prefix_cache(self, prompt):
                return {"fake_test_only": True}

            def choose(self, prompt, sample=False, temperature=1):
                p = (self.weight.detach() / temperature).softmax(-1)
                i = int(torch.multinomial(p, 1)) if sample else int(p.argmax())
                return LETTERS[i], {"log_probability": float(p[i].log()), "probabilities": p.tolist()}

            def save(self, path):
                Path(path).mkdir(parents=True, exist_ok=True)
                (Path(path) / "adapter_model.safetensors").write_bytes(self.weight.detach().numpy().tobytes())

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "fake"
            args = SimpleNamespace(output=out)
            with patch("builtins.print"):
                run.prepare(args)
            formal.configure()
            # Fake-policy numerical test uses the real tiered environment and oracle.
            from dataclasses import asdict
            tasks = task_splits("future")["train"][:2]
            run.save(out / "tasks/train.json", [asdict(t) for t in tasks])
            manifest = run.read(out / "task-manifest.json")
            manifest["train"]["sha256"] = run.digest(run.read(out / "tasks/train.json"))
            run.save(out / "task-manifest.json", manifest)
            run.save(out / "schedule.json", [0, 1])
            cfg = run.read(out / "config.json")
            cfg.update(warmup_updates=0, groups=2, training_groups=list(formal.GROUPS),
                       evaluate_common=False, validation_milestones=[])
            run.save(out / "config.json", cfg)
            lock = run.read(out / "protocol-lock.json")
            for key, name in [("config", "config.json"), ("tasks", "task-manifest.json"), ("schedule", "schedule.json")]:
                lock[key] = run.sha(out / name)
            run.save(out / "protocol-lock.json", lock)
            with (patch("app.agent_training.policy_v2.CachedLanguagePolicy", FakePolicy),
                  patch.object(run, "load_adapter"), patch.object(run, "evaluate") as evaluate,
                  patch("builtins.print")):
                run.develop(args)
                first = {g: run.read(out / g / "FINISHED.json") for g in formal.GROUPS}
                run.develop(args)
                evaluate.assert_not_called()
            self.assertEqual(first, {g: run.read(out / g / "FINISHED.json") for g in formal.GROUPS})
            self.assertFalse((out / "F_experience").exists())
            for step in [1, 2]:
                d, e = [run.read(out / g / ("step-%05d/summary.json" % step)) for g in formal.GROUPS]
                self.assertEqual(d["gradient_action_positions"], e["gradient_action_positions"])
                self.assertEqual(d["common_fingerprint"], e["common_fingerprint"])
                self.assertEqual(d["oracle_labels"], 0)
                self.assertGreater(e["oracle_labels"], 0)
            self.assertFalse(json.loads((out / "STATUS.json").read_text())["final_test_opened"])


if __name__ == "__main__":
    unittest.main()
