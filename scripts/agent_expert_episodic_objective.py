"""REINFORCE-LOO utilities for actual policy-generated complete episodes.

Preparation only. No critic, oracle continuation or supervised action target in
the actor objective. The unit tests enumerate a tiny MDP to verify its gradient.
"""
from __future__ import annotations

import numpy as np


def leave_one_out(returns):
    rewards = np.asarray(returns, dtype=np.float64)
    if rewards.ndim != 1 or len(rewards) < 2 or not np.isfinite(rewards).all():
        raise ValueError('At least two finite independent episode returns required')
    return rewards - (rewards.sum() - rewards) / (len(rewards) - 1)


def episode_return(success, steps, invalid_actions, repeated_actions):
    # success means the environment's correct terminal outcome, including a
    # supported no-feasible-candidate explanation, not physical port output.
    if not isinstance(success, bool):
        raise ValueError('An explicit boolean terminal outcome is required')
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in (steps, invalid_actions, repeated_actions)):
        raise ValueError('Nonnegative integer counters required')
    if steps < 1 or invalid_actions > steps or repeated_actions > steps:
        raise ValueError('Invalid episode counters')
    return (1.0 if success else -1.0) - .01 * steps - .05 * invalid_actions - .05 * repeated_actions


def trajectory_actor_loss(logits, actions, advantage, temperature=1.0):
    """One sampled trajectory contribution; callers average across trajectories.

    Rollouts must use the same current policy/temperature with no optimizer
    update until the entire sibling group has been sampled. One update only;
    repeated epochs would require a separately audited importance-ratio method.
    """
    import torch

    if logits.ndim != 2 or logits.shape[1] != 13 or len(logits) < 1 or len(actions) != len(logits):
        raise ValueError('Expected steps-by13 logits and one selected action per step')
    if not torch.isfinite(logits).all() or not np.isfinite(temperature) or temperature <= 0 or not np.isfinite(advantage):
        raise ValueError('Nonfinite logits/advantage or invalid temperature')
    raw = torch.as_tensor(actions, device=logits.device)
    if raw.ndim != 1 or not torch.isfinite(raw).all() or bool((raw != raw.long()).any()):
        raise ValueError('One integer action index per step is required')
    selected = raw.long()
    if bool(((selected < 0) | (selected >= 13)).any()):
        raise ValueError('Action outside registered menu')
    logp = torch.log_softmax(logits / temperature, dim=-1)
    return -float(advantage) * logp.gather(1, selected[:, None]).sum()


def numpy_trajectory_gradient(logits, actions, advantage, temperature=1.0):
    z = np.asarray(logits, dtype=np.float64) / temperature
    z -= z.max(axis=1, keepdims=True)
    p = np.exp(z) / np.exp(z).sum(axis=1, keepdims=True)
    target = np.zeros_like(p)
    target[np.arange(len(actions)), actions] = 1
    return -float(advantage) * (target - p) / temperature
