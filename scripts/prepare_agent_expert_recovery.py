"""Build training-only reference and learner-visited recovery states for stage003.

No model is loaded and no held-out file is parsed. References are programmatic
training demonstrations, never action substitutions in model execution.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.agent_training.expert_environment import reference_action  # noqa: E402
from scripts.probe_agent_expert_observation import make_env, verify, read, save, sha, EXPERT  # noqa: E402


def prepare(out):
    probe = EXPERT / 'continuation-003/observation-probe-001'
    verify(probe)
    results = read(probe / 'RESULTS.json')
    if len(results['results']) != 48 or read(probe / 'process-exit.json')['exit_code'] != 0:
        raise ValueError('Complete all registered training diagnostics first')
    out.mkdir(parents=True, exist_ok=False)
    cases = read(probe / 'CASES.json')
    by_id = {c['task']['case_id']: c for c in cases}
    states, prompt_index, duplicates = [], {}, []
    sources = {str(probe / name): sha(probe / name) for name in ['CONFIG.json', 'CASES.json', 'GOLD.json', 'RESULTS.json', 'LOCK.json']}

    def add(prompt, target, origin, proof):
        key = hashlib.sha256(prompt.encode()).hexdigest()
        if key in prompt_index:
            existing = states[prompt_index[key]]
            if existing['target'] != target:
                raise ValueError('Conflicting targets for identical observed prompt')
            duplicates.append(dict(existing_state_id=existing['state_id'], origin=origin, proof=proof))
            return
        prompt_index[key] = len(states)
        states.append(dict(state_id=f'state-{len(states):04d}', prompt=prompt, prompt_sha256=key,
                           target=target, origin=origin, proof=proof))

    reference_traces = []
    for case in cases:
        env, history = make_env(case), []
        while not env.done:
            action = reference_action(env)
            add(env.prompt(), action, 'new_reference', dict(case_id=env.task.case_id, history=history.copy(), provider='recorded_native_receipts'))
            env.step(action)
            history.append(action)
        if not env.success:
            raise ValueError('Reference cannot complete training task')
        reference_traces.append(dict(case_id=env.task.case_id, actions=history, success=env.success, outcome=env.outcome))
    selected_history_lengths = (1, 3, 5)
    recovery_proofs = []
    for row in results['results']:
        path = Path(row['trajectory'])
        if sha(path) != row['sha256'] or not row['audit']['passed']:
            raise ValueError('Learner trajectory integrity failure')
        sources[str(path)] = sha(path)
        job = read(path)
        env, history = make_env(by_id[row['case_id']]), []
        for step in job['steps']:
            if env.prompt() != step['prompt']:
                raise ValueError('Learner-visited prompt replay mismatch')
            if len(history) in selected_history_lengths:
                target = reference_action(env)
                proof = dict(case_id=env.task.case_id, group=row['group'], trajectory=str(path),
                             trajectory_sha256=sha(path), history=history.copy(), label_source='programmatic_reference_for_training_only')
                add(env.prompt(), target, 'new_learner_recovery', proof)
                recovery_proofs.append(dict(**proof, target=target))
            actual = env.step(step['model']['choice'])
            if json.loads(json.dumps(actual, ensure_ascii=False)) != step['transition']:
                raise ValueError('Learner transition replay mismatch')
            history.append(step['model']['choice'])

    prior = EXPERT / 'continuation-002'
    labels = read(prior / 'SFT_LABELS.json')
    for record in read(prior / 'STATES.json'):
        if record['origin'] == 'legacy_core24_full_trajectory_retention':
            add(record['prompt'], labels[record['state_id']], 'legacy_retention',
                dict(case_id=record['case_id'], state_id=record['state_id'], source=str(prior / 'STATES.json')))
    for path in [prior / 'STATES.json', prior / 'SFT_LABELS.json', prior / 'TRAINING_COMPLETE.json',
                 Path(__file__).resolve(), ROOT / 'app/agent_training/expert_observation_v2.py']:
        sources[str(path)] = sha(path)
    for case in cases:
        for path in case['receipt_files']:
            sources[path] = sha(path)
    parent = read(prior / 'TRAINING_COMPLETE.json')['routes']['E_sft']
    origin_counts = dict(Counter(s['origin'] for s in states))
    if not all(origin_counts.get(k, 0) > 0 for k in ('new_reference', 'new_learner_recovery', 'legacy_retention')):
        raise ValueError('All required training strata must be present')
    save(out / 'STATES.json', states)
    save(out / 'CASES.json', cases)
    save(out / 'TRAIN_GOLD.json', read(probe / 'GOLD.json'))
    save(out / 'REFERENCE_TRACES.json', reference_traces)
    save(out / 'RECOVERY_PROOFS.json', recovery_proofs)
    save(out / 'DEDUPLICATION.json', duplicates)
    save(out / 'SOURCE_MANIFEST.json', sources)
    audit = dict(time=datetime.now(timezone.utc).isoformat(), passed=True, states=len(states),
                 origin_counts=origin_counts, targets=dict(Counter(s['target'] for s in states)),
                 unique_prompts=len(prompt_index), duplicate_records_retained=len(duplicates),
                 conflicting_targets=0, training_scenarios=24, learner_episodes=48,
                 learner_recovery_samples=len(recovery_proofs), selected_history_lengths=list(selected_history_lengths),
                 new_model_calls=0, parameter_updates=0, heldout_files_parsed=0,
                 physical_windows=1, reference_demonstrations_are_programmatic=True,
                 no_inference_action_substitution=True, training_protocol_frozen=False)
    save(out / 'DATA_PREPARATION_AUDIT.json', audit)
    design = dict(time=audit['time'], status='proposed_not_frozen_or_started', common_warm_start_parent=parent,
                  parent_reason='Fixed-final002 supervised route retains learnable new-state label signal; selected from training logs, no heldout checkpoint search.',
                  warm_start=dict(max_updates=512, batch_size=12, new_states_per_batch=8, old_states_per_batch=4,
                                  new_sampling='balanced over nonempty target classes, full state coverage recorded',
                                  learning_rate_initial=0.0002, learning_rate_final=0.00002, schedule='cosine',
                                  weight_decay=0, gradient_clip=1, objective='cross_entropy_training_demonstrations',
                                  checkpoint_interval=1, train_rollout_gate_interval=64,
                                  gate='new24 and oldcore24 all complete at two consecutive registered training checkpoints',
                                  selection='Stop at second consecutive passing training gate, else fixed final512 marked not ready'),
                  subsequent_RL='Separately freeze full current-policy sampled episodes with REINFORCE leave-one-out feedback and matched normal SFT comparison after warm readiness; no separate critic/base model.',
                  constraints=['Resource guard required; one1.7B and4threads',
                               'Freeze training data/code/order/holdout before any parameter updates',
                               'Do not open a final test until training-side complete-task readiness',
                               'Keep all old failures, unopened old tests and successful baseline unchanged'],
                  launch_allowed=False)
    save(out.parent / 'RECOVERY_DESIGN.json', design)
    print(json.dumps(audit, ensure_ascii=False))


if __name__ == '__main__':
    prepare(EXPERT / 'continuation-003/recovery-data-001')
