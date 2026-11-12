"""Revision002 objectives: common preservation terms, no model loading.

The RL term remains an exactly enumerated, truncated simulator policy
objective. This is not on-policy trajectory training or a PPO/GRPO replica.
"""

from __future__ import annotations

import math
import numpy as np


def objective(
    logits,
    reference_logits,
    *,
    route,
    target=None,
    returns=None,
    temperature=8.0,
    kl_coefficient=0.02,
    entropy_coefficient=0.001,
):
    import torch

    if logits.shape != (13,) or reference_logits.shape != (13,):
        raise ValueError("Expected thirteen action logits")
    if temperature <= 0 or route not in ("E_sft", "D_rl"):
        raise ValueError("Invalid objective configuration")
    if not all(bool(torch.isfinite(x).all()) for x in (logits, reference_logits)):
        raise ValueError("Nonfinite logits")
    logp = torch.log_softmax(logits / temperature, 0)
    p = logp.exp()
    logref = torch.log_softmax(reference_logits.detach() / temperature, 0)
    kl = (p * (logp - logref)).sum()
    entropy = -(p * logp).sum()
    extra = {}
    if route == "E_sft":
        if target is None or returns is not None or not 0 <= target < 13:
            raise ValueError("SFT needs an explicit demonstration target only")
        learning = torch.nn.functional.cross_entropy(logits.unsqueeze(0), torch.tensor([target], device=logits.device))
        extra["cross_entropy"] = learning
    else:
        if target is not None or returns is None:
            raise ValueError("RL requires detached simulator returns and no target label")
        q = torch.as_tensor(returns, dtype=logits.dtype, device=logits.device).detach()
        if q.shape != (13,) or not bool(torch.isfinite(q).all()):
            raise ValueError("Invalid simulator returns")
        adv = (q - q.mean()) / q.std(unbiased=False).clamp(min=0.1)
        learning = -(p * adv).sum()
        extra.update(advantages=adv, expected_return=(p * q).sum())
    loss = learning + kl_coefficient * kl - entropy_coefficient * entropy
    return loss, {
        "learning_loss": learning,
        "kl": kl,
        "entropy": entropy,
        "probabilities": p,
        "inference_probabilities": torch.softmax(logits, 0),
        **extra,
    }


def numpy_audit(
    logits,
    reference_logits,
    *,
    route,
    target=None,
    returns=None,
    temperature=8.0,
    kl_coefficient=0.02,
    entropy_coefficient=0.001,
):
    def logsoftmax(x, t):
        x = np.asarray(x, dtype=float) / t
        return x - x.max() - math.log(np.exp(x - x.max()).sum())

    logp, ref = logsoftmax(logits, temperature), logsoftmax(reference_logits, temperature)
    p = np.exp(logp)
    kl, ent = float(p @ (logp - ref)), float(-p @ logp)
    derivative = kl_coefficient * (logp - ref + 1) + entropy_coefficient * (logp + 1)
    gradient = p * (derivative - p @ derivative) / temperature
    extra = {}
    if route == "E_sft":
        if target is None or returns is not None:
            raise ValueError("SFT input contract")
        lp1 = logsoftmax(logits, 1)
        learning = -lp1[target]
        supervised_gradient = np.exp(lp1)
        supervised_gradient[target] -= 1
        gradient += supervised_gradient
        extra["cross_entropy"] = float(learning)
    elif route == "D_rl":
        if target is not None or returns is None:
            raise ValueError("RL input contract")
        q = np.asarray(returns, dtype=float)
        adv = (q - q.mean()) / max(q.std(), 0.1)
        learning = -p @ adv
        gradient += -p * (adv - p @ adv) / temperature
        extra.update(advantages=adv.tolist(), expected_return=float(p @ q))
    else:
        raise ValueError("Unknown route")
    return {
        "loss": float(learning + kl_coefficient * kl - entropy_coefficient * ent),
        "learning_loss": float(learning),
        "kl": kl,
        "entropy": ent,
        "probabilities": p.tolist(),
        "inference_probabilities": np.exp(logsoftmax(logits, 1)).tolist(),
        "gradient_logits": gradient.tolist(),
        **extra,
    }


def arithmetic_check():
    import torch

    rng = np.random.default_rng(20261104)
    cases = []
    for route in ("E_sft", "D_rl"):
        for i in range(24):
            logits = rng.normal(size=13) * (30 if i % 3 == 0 else 3)
            reference = rng.normal(size=13) * 5
            kwargs = dict(route=route, temperature=8.0, kl_coefficient=0.02, entropy_coefficient=0.001)
            if route == "E_sft":
                kwargs["target"] = i % 13
            else:
                kwargs["returns"] = np.zeros(13) if i == 0 else rng.normal(size=13)
            x = torch.tensor(logits, dtype=torch.float64, requires_grad=True)
            loss, metrics = objective(x, torch.tensor(reference, dtype=torch.float64), **kwargs)
            loss.backward()
            expected = numpy_audit(logits, reference, **kwargs)
            errors = [
                abs(float(loss.detach()) - expected["loss"]),
                float(np.max(np.abs(x.grad.numpy() - expected["gradient_logits"]))),
            ]
            for key, value in metrics.items():
                errors.append(float(np.max(np.abs(value.detach().numpy() - np.asarray(expected[key])))))
            if max(errors) > 1e-10:
                raise ValueError("Independent objective/gradient mismatch")
            cases.append({"route": route, "case": i, "max_error": max(errors)})
    return {
        "passed": True,
        "tiny_tensor_cases": len(cases),
        "max_error": max(x["max_error"] for x in cases),
        "model_loads": 0,
        "training_updates": 0,
        "checks": cases,
    }


if __name__ == "__main__":
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-output", type=Path, required=True)
    args = parser.parse_args()
    result = arithmetic_check()
    if args.audit_output.exists():
        raise ValueError("Preserve prior audit")
    args.audit_output.parent.mkdir(parents=True, exist_ok=True)
    args.audit_output.write_text(json.dumps(result, indent=2) + "\n")
    print({k: result[k] for k in ("passed", "tiny_tensor_cases", "max_error", "model_loads")})
