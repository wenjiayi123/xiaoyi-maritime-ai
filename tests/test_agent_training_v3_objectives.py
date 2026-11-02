"""Numerical tests run in .venv-lora; they never count as model experiments."""

import hashlib
import math
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

try:
    import torch
except ImportError:
    torch = None

from app.agent_training.objectives_v3 import action_loss


@unittest.skipIf(torch is None, "torch lives in the isolated training environment")
class ObjectiveTests(unittest.TestCase):
    def test_replay_gradient_matches_finite_difference(self):
        def value(x):
            lp = torch.tensor([x, 0.0], dtype=torch.float64).log_softmax(-1)
            return float(action_loss(lp, 0, math.log(0.3), 0.7, replay=True)[0])

        z = torch.tensor([0.4, 0.0], dtype=torch.float64, requires_grad=True)
        loss, _ = action_loss(z.log_softmax(-1), 0, math.log(0.3), 0.7, replay=True)
        loss.backward()
        finite = (value(0.400001) - value(0.399999)) / 0.000002
        self.assertAlmostEqual(float(z.grad[0]), finite, places=7)
        self.assertLess(float(z.grad[0]), 0)

    def test_clip_signs_and_reference_kl(self):
        for advantage, active in [(1, False), (-1, True)]:
            z = torch.tensor([2.0, 0.0], requires_grad=True)
            lp = z.log_softmax(-1)
            loss, _ = action_loss(lp, 0, math.log(0.1), advantage)
            loss.backward()
            self.assertEqual(float(z.grad[0]) > 0, active)
        lp = torch.tensor([0.0, 0.0]).log_softmax(-1)
        _, stats = action_loss(lp, 0, math.log(0.5), 0, reference_probs=[0.5, 0.5])
        self.assertAlmostEqual(stats["kl"], 0.0)

    def test_complete_pipeline_and_resume_with_fake_policy(self):
        # Exercises checkpoint/logging/strong-SFT replay without loading 1.7B.
        from scripts import run_agent_rl_v3 as run
        from app.agent_training.environment import LETTERS

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
            out = Path(tmp) / "mock"
            args = SimpleNamespace(output=out)
            with patch("builtins.print"):
                run.prepare(args)
            cfg = run.read(out / "config.json")
            cfg.update(warmup_updates=2, groups=2, validation_milestones=[0, 2])
            run.save(out / "config.json", cfg)
            lock = run.read(out / "protocol-lock.json")
            lock["config"] = run.sha(out / "config.json")
            run.save(out / "protocol-lock.json", lock)
            with (
                patch("app.agent_training.policy_v2.CachedLanguagePolicy", FakePolicy),
                patch.object(run, "load_adapter"),
                patch("builtins.print"),
            ):
                run.develop(args)
                fingerprints = {
                    p.name: run.read(p / "FINISHED.json")["fingerprint"]
                    for p in out.iterdir()
                    if (p / "FINISHED.json").exists()
                }
                run.develop(args)
            for name, fp in fingerprints.items():
                self.assertEqual(run.read(out / name / "FINISHED.json")["fingerprint"], fp)
            for i in [1, 2]:
                d = run.read(out / "D_drgrpo" / f"step-{i:05d}" / "summary.json")
                e = run.read(out / "E_more_sft" / f"step-{i:05d}" / "summary.json")
                self.assertEqual(d["gradient_action_positions"], e["gradient_action_positions"])
                self.assertEqual(d["common_fingerprint"], e["common_fingerprint"])
                self.assertEqual(d["oracle_labels"], 0)
                self.assertGreater(e["oracle_labels"], 0)
            self.assertFalse(run.read(out / "STATUS.json")["final_test_opened"])


if __name__ == "__main__":
    unittest.main()
