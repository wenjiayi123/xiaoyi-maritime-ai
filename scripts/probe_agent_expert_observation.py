"""Frozen training-only diagnostic of an explicit observation format, no training."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.agent_training.expert_environment import ExpertTask, RecordedEnergyProvider  # noqa: E402
from app.agent_training.registered_receipts import read_receipt  # noqa: E402
from app.agent_training.expert_observation_v2 import ObservedFactsEnvironment, REVISION  # noqa: E402
from app.agent_training.live import local_request  # noqa: E402
from scripts.agent_expert_evaluation_support import canonical, validate_decision, outcome_metrics  # noqa: E402
from scripts.evaluate_agent_expert_continuation import EXPERT, DATA, REGISTRY, verify as verify_old  # noqa: E402


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    temp.replace(path)


def now():
    return datetime.now(timezone.utc).isoformat()


def make_env(case):
    return ObservedFactsEnvironment(ExpertTask(**case['task']),
                                    RecordedEnergyProvider([read_receipt(p) for p in case['receipt_files']]))


def prepare(out):
    verify_old(EXPERT / 'evaluation-002')
    if read(EXPERT / 'evaluation-002/STATUS.json')['phase'] != 'complete':
        raise ValueError('Complete prior evaluation before new diagnostic')
    out.mkdir(parents=True, exist_ok=False)
    cases = read(DATA / 'train/tasks.json')
    assert len(cases) == 24
    gold = read(DATA / 'train/oracle-labels.json')
    registry = read(REGISTRY)
    config = dict(time=now(), purpose='training_only_observation_diagnostic', revision=REVISION,
                  groups=['D_expert_rl2', 'E_expert_sft2'], cases=24, attempts=48,
                  models={g: registry['groups'][g] for g in ['D_expert_rl2', 'E_expert_sft2']},
                  registry_sha256=sha(REGISTRY), worker='http://127.0.0.1:18781',
                  parameter_updates=0, new_base_models=0, final_test_opened=False,
                  interpretation='Prompt engineering with fixed trained adapters. All24 are TRAINING cases; no generalization or RL improvement claim. Every failure retained.',
                  changes='Only readable observed state and observed action history. Same13 actions, transitions, rewards, receipts and task goals; no hidden oracle selection or action masking.')
    save(out / 'CONFIG.json', config)
    save(out / 'CASES.json', cases)
    save(out / 'GOLD.json', gold)
    paths = [Path(__file__).resolve(), ROOT / 'app/agent_training/expert_observation_v2.py',
             ROOT / 'tests/test_agent_expert_observation_v2.py', ROOT / 'app/agent_training/expert_environment.py',
             ROOT / 'scripts/agent_expert_evaluation_support.py', DATA / 'train/tasks.json', DATA / 'train/oracle-labels.json', REGISTRY]
    paths += sorted({Path(p) for c in cases for p in c['receipt_files']})
    source = {}
    for path in paths:
        path = path.resolve()
        source[str(path)] = sha(path)
        target = out / 'sources' / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    save(out / 'SOURCES.json', source)
    save(out / 'LOCK.json', {name: sha(out / name) for name in ['CONFIG.json', 'CASES.json', 'GOLD.json', 'SOURCES.json']})
    save(out / 'STATUS.json', dict(time=now(), phase='ready_not_started'))


def verify(out):
    verify_old(EXPERT / 'evaluation-002')
    for name, expected in read(out / 'LOCK.json').items():
        if sha(out / name) != expected:
            raise ValueError('Diagnostic configuration drift: ' + name)
    for path, expected in read(out / 'SOURCES.json').items():
        if sha(path) != expected:
            raise ValueError('Diagnostic source drift: ' + path)
    return read(out / 'CONFIG.json')


def resource_check(out):
    if (EXPERT / 'PAUSE').exists() or (out / 'PAUSE').exists():
        raise RuntimeError('Paused; partial training diagnostic retained')
    status = read(EXPERT / 'resource-guard-001/STATUS.json')
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(status['time'])).total_seconds()
    if age > 90 or status['decision']['pause'] or len(status['model_processes']) != 1:
        raise RuntimeError('Resource guard stale, interrupted or model count invalid')


def audit(case, job):
    env = make_env(case)
    for step in job['steps']:
        if step['prompt'] != env.prompt():
            raise ValueError('Observed prompt differs on independent replay')
        validate_decision(step['model'], job['group'], job['fingerprint'])
        if canonical(env.step(step['model']['choice'])) != step['transition']:
            raise ValueError('Transition differs from recorded physical receipts')
    if outcome_metrics(env, job['gold']) != job['metrics'] or canonical(env.report) != job['report']:
        raise ValueError('Unsupported completion')
    return dict(passed=True, decisions=len(job['steps']), no_rule_action_substitution=True, new_model_calls=0)


def run(out):
    cfg = verify(out)
    if (out / 'STARTED.json').exists():
        raise ValueError('Prior diagnostic preserved; no automatic rerun')
    resource_check(out)
    health = local_request(cfg['worker'], '/health', timeout=8)
    if health['registry_sha256'] != cfg['registry_sha256'] or health['base_model_instances'] != 1:
        raise ValueError('Worker identity mismatch')
    if any(health['weights'][g] != cfg['models'][g]['parameter_fingerprint'] for g in cfg['groups']):
        raise ValueError('Adapter identity mismatch')
    save(out / 'STARTED.json', dict(time=now(), health=health, protocol_sha256=sha(out / 'LOCK.json')))
    gold = {g['case_id']: g for g in read(out / 'GOLD.json')}
    results = []
    for case in read(out / 'CASES.json'):
        for group in cfg['groups']:
            resource_check(out)
            folder = out / 'episodes' / (case['task']['case_id'] + '-' + group)
            env = make_env(case)
            job = dict(case_id=env.task.case_id, group=group, task=case['task'],
                       fingerprint=cfg['models'][group]['parameter_fingerprint'], gold=gold[env.task.case_id],
                       steps=[], phase='running')
            save(out / 'STATUS.json', dict(time=now(), phase='running', completed=len(results), registered=48,
                                         active=folder.name, training_only=True, parameter_updates=0))
            save(folder / 'trajectory.json', job)
            while not env.done:
                resource_check(out)
                prompt = env.prompt()
                response = local_request(cfg['worker'], '/decide', dict(prompt=prompt, group=group), timeout=120)
                job['pending_decision'] = dict(prompt=prompt, model=response)
                save(folder / 'trajectory.json', job)
                validate_decision(response, group, job['fingerprint'])
                transition = canonical(env.step(response['choice']))
                job['steps'].append(dict(prompt=prompt, model=response, transition=transition))
                job.pop('pending_decision')
                save(folder / 'trajectory.json', job)
            job.update(phase='complete', metrics=outcome_metrics(env, job['gold']), report=canonical(env.report))
            save(folder / 'trajectory.json', job)
            proof = audit(case, job)
            save(folder / 'AUDIT.json', proof)
            results.append(dict(case_id=env.task.case_id, group=group, metrics=job['metrics'], steps=len(job['steps']),
                                trajectory=str(folder / 'trajectory.json'), sha256=sha(folder / 'trajectory.json'), audit=proof))
            save(out / 'PROGRESS.json', dict(time=now(), completed=len(results), registered=48, results=results))
    verify(out)
    summary = {g: dict(correct=sum(r['metrics']['decision_correct'] for r in results if r['group'] == g), attempted=24)
               for g in cfg['groups']}
    save(out / 'RESULTS.json', dict(time=now(), training_only=True, groups=summary, results=results, parameter_updates=0))
    save(out / 'STATUS.json', dict(time=now(), phase='complete', completed=48, groups=summary, accepted_final=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['prepare', 'run'])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.mode == 'prepare':
        prepare(args.output.resolve())
    else:
        try:
            run(args.output.resolve())
        except BaseException as exc:
            save(args.output / 'FAILURE.json', dict(time=now(), error=repr(exc), traceback=traceback.format_exc()))
            save(args.output / 'process-exit.json', dict(time=now(), exit_code=1))
            raise
        save(args.output / 'process-exit.json', dict(time=now(), exit_code=0))
