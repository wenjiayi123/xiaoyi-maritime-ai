"""Small auditable objectives for *action-token* agent adaptations.

Not a reproduction of the original papers' distributed reasoning experiments.
Full trajectories determine advantages; tool observations receive no gradients.
"""


def centered_advantages(returns):
    if len(returns) < 2:
        raise ValueError("group relative learning needs at least two trajectories")
    mean = sum(returns) / len(returns)
    return [r - mean for r in returns]


def action_loss(
    log_probs,
    action,
    behavior_logprob,
    advantage,
    *,
    replay=False,
    clip=0.2,
    beta=0.1,
    reference_probs=None,
    kl_coefficient=0.02,
):
    """Dr.GRPO-style fresh surrogate / ExGRPO-inspired shaped replay surrogate.

    Caller sums over action positions then divides by fixed K * max_steps,
    never by each trajectory length or by reward standard deviation.
    Importance denominator is the probability at actual collection temperature.
    """
    import torch

    logp = log_probs[action]
    ratio = (logp - torch.as_tensor(behavior_logprob, dtype=logp.dtype)).exp()
    adv = torch.as_tensor(advantage, dtype=logp.dtype)
    if replay:
        surrogate = -adv * ratio / (ratio + beta)
    else:
        surrogate = -torch.minimum(adv * ratio, adv * ratio.clamp(1 - clip, 1 + clip))
    kl = logp * 0
    if reference_probs is not None:
        q = torch.as_tensor(reference_probs, dtype=log_probs.dtype)
        kl = (log_probs.exp() * (log_probs - q.clamp_min(1e-30).log())).sum()
    entropy = -(log_probs.exp() * log_probs).sum()
    return surrogate + kl_coefficient * kl, {
        "surrogate": float(surrogate.detach()),
        "ratio": float(ratio.detach()),
        "kl": float(kl.detach()),
        "entropy": float(entropy.detach()),
        "clipped": bool(not replay and abs(float(ratio.detach()) - 1) > clip),
    }
