from itertools import product

import numpy as np
import pytest

from scripts.agent_expert_episodic_objective import episode_return, leave_one_out


def test_leave_one_out_not_self_including_mean():
    np.testing.assert_allclose(leave_one_out([1., -1., .5, .25]), [13/12, -19/12, 5/12, 1/12])
    np.testing.assert_allclose(leave_one_out([2., 2., 2., 2.]), 0)


@pytest.mark.parametrize('values', [[], [1.], [1., np.nan], [[1., 2.]]])
def test_invalid_episode_cohort(values):
    with pytest.raises(ValueError):
        leave_one_out(values)


def test_success_and_loops_use_complete_outcome():
    assert episode_return(True, 8, 0, 0) > episode_return(False, 18, 0, 17)
    assert episode_return(True, 8, 0, 0) > episode_return(True, 12, 2, 2)


def test_success_priority_for_entire_registered_eighteen_step_budget():
    # Even the worst registered correct terminal outcome outranks the best
    # failure. Invalid and repeated counters can overlap on the same step.
    worst_success = min(episode_return(True, steps, steps, steps) for steps in range(1, 19))
    best_failure = max(episode_return(False, steps, 0, 0) for steps in range(1, 19))
    assert worst_success > best_failure


@pytest.mark.parametrize('args', [(True, 0, 0, 0), (True, 3, 4, 0), (False, True, 0, 0), ('false', 3, 0, 0)])
def test_invalid_counters(args):
    with pytest.raises(ValueError):
        episode_return(*args)


@pytest.mark.parametrize('logits', [[-.4, .8, -.1], [1.2, -.7, .3], [0., 0., 0.]])
def test_exact_small_mdp_rloo_gradient_matches_terminal_objective(logits):
    # A real two-decision branching MDP, not max-over-oracle continuation.
    # Parameters: root Bernoulli and separate Bernoulli for each reached branch.
    z = np.asarray(logits)
    p = 1 / (1 + np.exp(-z))
    episodes = []
    for a, b in product(range(2), repeat=2):
        prob = (p[0] if a else 1-p[0]) * (p[1+a] if b else 1-p[1+a])
        reward = (1 if a != b else -1) - .03 * a
        score = np.zeros(3)
        score[0] = a-p[0]
        score[1+a] = b-p[1+a]
        episodes.append((prob, reward, score))
    rloo = np.zeros(3)
    for e1, e2 in product(episodes, repeat=2):
        advantages = leave_one_out([e1[1], e2[1]])
        rloo += e1[0]*e2[0]*(advantages[0]*e1[2] + advantages[1]*e2[2])/2

    def exact_return(v):
        q = 1/(1+np.exp(-v))
        return sum((q[0] if a else 1-q[0]) * (q[1+a] if b else 1-q[1+a])
                   * ((1 if a != b else -1)-.03*a) for a,b in product(range(2), repeat=2))
    finite_difference = np.zeros(3)
    for j in range(3):
        delta = np.zeros(3)
        delta[j] = 1e-5
        finite_difference[j] = (exact_return(z+delta)-exact_return(z-delta))/2e-5
    np.testing.assert_allclose(rloo, finite_difference, rtol=1e-8, atol=1e-9)
