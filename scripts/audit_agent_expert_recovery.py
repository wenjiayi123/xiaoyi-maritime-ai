"""Independent training-data replay and completed diagnostic preservation; no LM."""
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.agent_training.expert_environment import reference_action  # noqa: E402
from scripts.probe_agent_expert_observation import EXPERT, audit, make_env, now, read, save, sha, verify  # noqa: E402


def run():
    folder = EXPERT / 'continuation-003'
    data = folder / 'recovery-data-001'
    probe = folder / 'observation-probe-001'
    if (data / 'INDEPENDENT_REPLAY_AUDIT.json').exists():
        raise ValueError('Preserve the previous audit; do not overwrite')
    cfg = verify(probe)
    sources = read(data / 'SOURCE_MANIFEST.json')
    for path, expected in sources.items():
        if sha(path) != expected:
            raise ValueError('Source drift: ' + path)
    cases = {c['task']['case_id']: c for c in read(data / 'CASES.json')}
    result = read(probe / 'RESULTS.json')
    expected_pairs = {(case, group) for case in cases for group in cfg['groups']}
    pairs = {(row['case_id'], row['group']) for row in result['results']}
    if pairs != expected_pairs or len(result['results']) != len(expected_pairs):
        raise ValueError('Incomplete or duplicated diagnostic cohort')
    actions = {g: Counter() for g in cfg['groups']}
    for row in result['results']:
        job = read(row['trajectory'])
        if sha(row['trajectory']) != row['sha256']:
            raise ValueError('Diagnostic trajectory changed')
        if job['fingerprint'] != cfg['models'][row['group']]['parameter_fingerprint']:
            raise ValueError('Wrong adapter identity')
        audit(cases[row['case_id']], job)
        if row['metrics'] != job['metrics'] or row['steps'] != len(job['steps']):
            raise ValueError('Result row differs from independently replayed job')
        actions[row['group']].update(s['model']['choice'] for s in job['steps'])

    states = read(data / 'STATES.json')
    by_id = {s['state_id']: s for s in states}
    legacy = {s['state_id']: s for s in read(EXPERT / 'continuation-002/STATES.json')}
    legacy_labels = read(EXPERT / 'continuation-002/SFT_LABELS.json')
    proofs = []
    for record in states + read(data / 'DEDUPLICATION.json'):
        target_state = by_id[record['existing_state_id']] if 'existing_state_id' in record else record
        proof = record['proof']
        if record['origin'] == 'legacy_retention':
            old = legacy[proof['state_id']]
            if old['prompt'] != target_state['prompt'] or legacy_labels[proof['state_id']] != target_state['target']:
                raise ValueError('Legacy state or target drift')
        else:
            env = make_env(cases[proof['case_id']])
            for action in proof['history']:
                if env.done:
                    raise ValueError('Training state lies after a terminal outcome')
                env.step(action)
            if env.done or env.prompt() != target_state['prompt'] or reference_action(env) != target_state['target']:
                raise ValueError('Training prompt/target does not follow its recorded history')
            recovery_actions = []
            while not env.done:
                action = reference_action(env)
                recovery_actions.append(action)
                env.step(action)
            if not env.success:
                raise ValueError('Corrective training target cannot lead to a correct terminal outcome within budget')
            proofs.append(dict(state_id=target_state['state_id'], case_id=proof['case_id'],
                               history=proof['history'], remaining_reference_actions=recovery_actions,
                               final_outcome=env.outcome, correct_terminal=True))
    if len({s['prompt_sha256'] for s in states}) != len(states):
        raise ValueError('Deduplication failure')
    for state in states:
        import hashlib
        if hashlib.sha256(state['prompt'].encode()).hexdigest() != state['prompt_sha256']:
            raise ValueError('Prompt hash mismatch')

    save(data / 'CORRECTIVE_COMPLETION_PROOFS.json', proofs)
    report = dict(time=now(), passed=True, source_hashes_verified=len(sources),
                  learner_episodes_replayed=len(pairs), actual_model_decisions=sum(sum(c.values()) for c in actions.values()),
                  observed_actions={g: dict(c) for g, c in actions.items()},
                  unique_states=len(states), original_records_preserved=len(states)+len(read(data/'DEDUPLICATION.json')),
                  training_reference_and_recovery_paths_completed=len(proofs),
                  model_calls_in_this_audit=0, parameter_updates=0, heldout_files_parsed=0,
                  note='Teacher completion of training states verifies labels only, not learned-policy capability.',
                  inputs={str(data/name): sha(data/name) for name in ['STATES.json','DEDUPLICATION.json','SOURCE_MANIFEST.json']},
                  audit_source_sha256=sha(Path(__file__).resolve()))
    save(data / 'INDEPENDENT_REPLAY_AUDIT.json', report)
    save(folder / 'OBSERVATION_DIAGNOSTIC_COMPLETE.json', dict(
        time=now(), completed=48, registered=48, correct=result['groups'],
        all_trajectories_replayed=True, observed_actions=report['observed_actions'],
        actual_model_decisions=report['actual_model_decisions'], diagnostic_parameter_updates=0,
        final_test=False, result_sha256=sha(probe/'RESULTS.json'), protocol_sha256=sha(probe/'LOCK.json'),
        interpretation='Both fixed adapters failed all24 training episodes even with observed facts and history made explicit. Observation formatting alone did not solve the trained task. No new generalization or RL gain is established.',
        next='Build and separately freeze supervised recovery warm-start, then complete-policy-episode RL and normal SFT comparison. No final test opening before training readiness.'))
    print(report)


if __name__ == '__main__':
    run()
