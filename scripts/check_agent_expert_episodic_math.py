"""Tiny-tensor REINFORCE arithmetic check; never constructs a language model."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.agent_expert_episodic_objective import numpy_trajectory_gradient, trajectory_actor_loss  # noqa: E402
from scripts.probe_agent_expert_observation import EXPERT, now, read, save, sha  # noqa: E402


def run():
    output = EXPERT / 'continuation-003/EPISODIC_GRADIENT_ARITHMETIC.json'
    if output.exists():
        raise ValueError('Previous arithmetic audit must be preserved')
    status = read(EXPERT / 'resource-guard-001/STATUS.json')
    from datetime import datetime, timezone
    age = (datetime.now(timezone.utc)-datetime.fromisoformat(status['time'])).total_seconds()
    if age > 90 or status['decision']['pause'] or (EXPERT/'PAUSE').exists():
        raise ValueError('Resource guard does not allow even the bounded arithmetic check')
    import numpy as np
    import torch
    torch.set_num_threads(1)
    rng = np.random.default_rng(20261105)
    rows = []
    for steps in (1, 8, 18):
        for temperature in (.7, 1., 2., 8.):
            for advantage in (-1.5, 0., 1.5):
                logits = rng.normal(size=(steps,13))*3
                actions = rng.integers(0,13,size=steps).tolist()
                x = torch.tensor(logits,dtype=torch.float64,requires_grad=True)
                loss = trajectory_actor_loss(x,actions,advantage,temperature)
                loss.backward()
                expected = numpy_trajectory_gradient(logits,actions,advantage,temperature)
                error = float(np.max(np.abs(x.grad.numpy()-expected)))
                if error > 1e-12:
                    raise ValueError('Logit gradient mismatch')
                rows.append(dict(steps=steps,temperature=temperature,advantage=advantage,loss=float(loss.detach()),max_error=error))
    bad = [([1.5],1.),([13],1.),([-1],1.),([float('nan')],1.),([1],float('nan')),([1],0.)]
    for actions,temp in bad:
        try:
            trajectory_actor_loss(torch.zeros((1,13)),actions,1.,temp)
        except ValueError:
            pass
        else:
            raise ValueError('Invalid actor input accepted')
    report = dict(time=now(),passed=True,tensor_cases=len(rows),invalid_input_cases=len(bad),
                  maximum_error=max(r['max_error'] for r in rows),rows=rows,torch_version=torch.__version__,
                  new_model_loads=0,language_model_parameter_updates=0,
                  note='Tiny differentiable logits only; no rollout, optimizer or 1.7B model constructed.',
                  source_hashes={str(p):sha(p) for p in [Path(__file__).resolve(),ROOT/'scripts/agent_expert_episodic_objective.py']})
    save(output,report)
    print({k:v for k,v in report.items() if k not in ('rows','source_hashes')})


if __name__ == '__main__':
    run()
