"""Small tensor numerical and tokenizer checks; never loads model weights."""

from pathlib import Path
import argparse
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.agent_training.expert_learning import actor_objective, numpy_actor_audit  # noqa: E402
from scripts.prepare_agent_expert_training import read, save  # noqa: E402


def run(out):
    import numpy as np
    import torch
    from transformers import AutoTokenizer
    from app.agent_training.policy import BASE, SYSTEM

    cfg = read(out / "CONFIG.json")
    rng = np.random.default_rng(20261103)
    errors = []
    for _ in range(40):
        z, ref, q = (rng.normal(size=13) for _ in range(3))
        logits = torch.tensor(z, dtype=torch.float64, requires_grad=True)
        loss, _ = actor_objective(logits, torch.tensor(ref), q)
        loss.backward()
        audit = numpy_actor_audit(z, ref, q, cfg)
        errors.append(
            max(
                abs(float(loss.detach()) - audit["loss"]),
                np.max(np.abs(logits.grad.numpy() - audit["gradient_logits"])),
            )
        )
    # Check an equal-return case (only regularization can supply gradient).
    z = torch.zeros(13, dtype=torch.float64, requires_grad=True)
    loss, _ = actor_objective(z, z.detach(), [1] * 13)
    loss.backward()
    assert float(z.grad.abs().max()) < 1e-12
    save(
        out / "OBJECTIVE_AUDIT.json",
        {
            "passed": max(errors) < 1e-10,
            "random_gradient_cases": 40,
            "equal_return_gradient_check": True,
            "max_loss_or_gradient_error": max(errors),
            "model_loaded": False,
            "trainable_test_tensor_values": 13,
            "method": "Torch autodiff versus independent NumPy analytic derivative",
        },
    )
    tokenizer = AutoTokenizer.from_pretrained(BASE, local_files_only=True)
    counts = []
    for r in read(out / "STATES.json"):
        text = tokenizer.apply_chat_template(
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": r["prompt"]}],
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        counts.append({"state_id": r["state_id"], "tokens": len(tokenizer.encode(text))})
    passed = all(row["tokens"] <= 768 for row in counts)
    save(
        out / "TOKEN_AUDIT.json",
        {
            "passed": passed,
            "states": len(counts),
            "max_tokens": max(x["tokens"] for x in counts),
            "limit": 768,
            "truncation": False,
            "model_loaded": False,
            "rows": counts,
        },
    )
    if not passed or max(errors) >= 1e-10:
        raise ValueError("Audit failed")
    print(
        {
            "objective_passed": True,
            "max_error": max(errors),
            "token_max": max(x["tokens"] for x in counts),
            "model_loaded": False,
        }
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--experiment", type=Path, required=True)
    run(p.parse_args().experiment)
