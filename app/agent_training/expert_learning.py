"""Auditable, bounded actor training; no language model is loaded on import.

The new-task return is a two-step model-based lookahead, not an unbiased
long-horizon policy return, PPO, or GRPO. Potential shaping follows Ng,
Harada and Russell (ICML 1999); its complete-return identity does not make
this truncated planner optimal. The deployed model receives no branch scores.
"""

from __future__ import annotations

from copy import deepcopy
import math

from .expert_environment import LETTERS, MISSING_FIELDS, RecordedEnergyProvider

GAMMA = 0.95


def potential(env):
    """Observable progress only; terminal potential is always zero."""
    if env.done:
        return 0.0
    state = env.observation()
    supplied = sum(state["known"][key] is not None for key in MISSING_FIELDS)
    current = sum(v["goal_version"] == state["goal_version"] for v in state["verified"].values())
    return 0.05 * supplied + 0.1 * state["context_read"] + 0.15 * len(state["calculated"]) + 0.15 * current


def shaped_step(env, action, gamma=GAMMA):
    before = potential(env)
    result = env.step(action)
    after = potential(env)
    return {
        "action": action,
        "raw_reward": result["reward"],
        "phi_before": before,
        "phi_after": after,
        "reward": result["reward"] + gamma * after - before,
        "done": env.done,
        "outcome": env.outcome,
        "error": result["error"],
    }


def counterfactuals(env, gamma=GAMMA):
    if type(env.provider) is not RecordedEnergyProvider:
        raise ValueError("Counterfactual enumeration must never execute native writes")
    if env.done:
        raise ValueError("No training from terminal state")
    branches = {}
    for action in LETTERS:
        first_env = deepcopy(env)
        first = shaped_step(first_env, action, gamma)
        seconds = {}
        if not first_env.done:
            for second_action in LETTERS:
                seconds[second_action] = shaped_step(deepcopy(first_env), second_action, gamma)
        continuation = max((r["reward"] for r in seconds.values()), default=0.0)
        branches[action] = {
            "first": first,
            "seconds": seconds,
            "two_step_return": first["reward"] + gamma * continuation,
        }
    return branches


def actor_objective(
    logits, reference_logits, returns, *, temperature=2.0, kl_coefficient=0.02, entropy_coefficient=0.001
):
    """Exact categorical policy gradient through thirteen action probabilities.

    No action labels enter this objective. Returns are detached simulator
    estimates. Normalization uses an action-uniform, not learned, baseline.
    """
    import torch

    values = torch.as_tensor(returns, dtype=logits.dtype, device=logits.device).detach()
    if logits.shape != (13,) or values.shape != logits.shape or reference_logits.shape != logits.shape:
        raise ValueError("Expected thirteen actions")
    if not all(bool(torch.isfinite(v).all()) for v in (logits, reference_logits, values)):
        raise ValueError("Nonfinite objective inputs")
    logp = torch.log_softmax(logits / temperature, 0)
    probs = logp.exp()
    advantages = (values - values.mean()) / values.std(unbiased=False).clamp(min=0.1)
    logref = torch.log_softmax(reference_logits.detach() / temperature, 0)
    kl = (probs * (logp - logref)).sum()
    entropy = -(probs * logp).sum()
    loss = -(probs * advantages).sum() + kl_coefficient * kl - entropy_coefficient * entropy
    return loss, {
        "probabilities": probs,
        "advantages": advantages,
        "kl": kl,
        "entropy": entropy,
        "expected_return": (probs * values).sum(),
    }


def numpy_actor_audit(logits, reference_logits, returns, cfg):
    """Independent arithmetic for saved evidence, including analytic gradient."""
    import numpy as np

    def logsoftmax(values):
        a = np.asarray(values, dtype=np.float64) / cfg["temperature"]
        return a - a.max() - math.log(np.exp(a - a.max()).sum())

    logp, logref = logsoftmax(logits), logsoftmax(reference_logits)
    p = np.exp(logp)
    values = np.asarray(returns, dtype=np.float64)
    adv = (values - values.mean()) / max(values.std(), 0.1)
    kl, entropy = (p * (logp - logref)).sum(), -(p * logp).sum()
    loss = -(p * adv).sum() + cfg["kl_coefficient"] * kl - cfg["entropy_coefficient"] * entropy
    derivative_p = -adv + cfg["kl_coefficient"] * (logp - logref + 1) + cfg["entropy_coefficient"] * (logp + 1)
    gradient = p * (derivative_p - (p * derivative_p).sum()) / cfg["temperature"]
    return {
        "loss": float(loss),
        "kl": float(kl),
        "entropy": float(entropy),
        "expected_return": float(p @ values),
        "advantages": adv.tolist(),
        "probabilities": p.tolist(),
        "gradient_logits": gradient.tolist(),
    }
