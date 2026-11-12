import os
from pathlib import Path

import pytest

from scripts import watch_agent_expert_resources as guard


CFG = dict(sustained_samples=2, stop_after_samples=4, pause_disk_gib=5,
           nice_on_warning=10, allowed_models=[dict(script='scripts/serve_agent_expert_registry.py', path_flag='--registry')])


def reading(**kwargs):
    result = dict(thermal_state=0, memory_pressure=1, cpu_speed_limit=100,
                  free_disk_gib=20, model_processes=[])
    return {**result, **kwargs}


def row():
    return dict(pid=999999, uid=guard.current_owner(), started='Tue Nov 3 06:00:00 2026', nice=0, cwd=str(guard.ROOT),
                command='/usr/bin/python3 scripts/serve_agent_expert_registry.py --registry '
                '.codex_artifacts/agent-rl-expert-expansion-20261102/continuation-002/live-registration-003/REGISTRY.json')


@pytest.fixture(autouse=True)
def fixture_process_owner(monkeypatch):
    # The tests use a synthetic process table and injected signal/priority functions.
    monkeypatch.setattr(guard,"current_owner",lambda:173)
    monkeypatch.setattr(guard,"PRIORITY_SCOPE",0)


def test_missing_process_identity_cannot_establish_ownership(monkeypatch):
    record=row()
    monkeypatch.setattr(guard,"current_owner",lambda:None)
    assert not guard.owned_model(record,CFG)


def test_normal_no_action_even_with_old_swap():
    d = guard.decide(reading(swap='used=14GB'), {}, CFG)
    assert not d['pause'] and not d['lower_priority'] and not d['emergency_terminate']


def test_lsof_utf8_path_decode():
    assert guard.decode_lsof_path(r'/tmp/fixture/\xe5\xb0\x8f\xe6\x87\xbfAI') == '/tmp/fixture/小懿AI'
    escaped_new = ''.join(f'\\x{byte:02x}' for byte in '舷鸥'.encode('utf-8'))
    assert guard.decode_lsof_path('/tmp/fixture/'+escaped_new) == '/tmp/fixture/舷鸥'
    assert guard.decode_lsof_path('/tmp/fixture/舷鸥 · GullMate') == '/tmp/fixture/舷鸥 · GullMate'


def test_fair_only_reduces_priority():
    d = guard.decide(reading(thermal_state=1), {}, CFG)
    assert d['lower_priority'] and not d['pause'] and not d['emergency_terminate']


def test_serious_requires_persistence_then_stops():
    s = {}
    for i in range(4):
        d = guard.decide(reading(thermal_state=2), s, CFG)
        s = d['streaks']
        assert d['pause'] == (i >= 1)
        assert d['emergency_terminate'] == (i >= 3)
    assert guard.decide(reading(), s, CFG)['streaks']['serious'] == 0


@pytest.mark.parametrize('data,reason', [
    (dict(thermal_state=3), 'critical_thermal'),
    (dict(free_disk_gib=4.99), 'low_disk'),
    (dict(model_processes=[{}, {}]), 'multiple_registered_model_processes'),
])
def test_immediate_pause(data, reason):
    d = guard.decide(reading(**data), {}, CFG)
    assert d['pause'] and reason in d['reasons']


def test_memory_pressure_and_missing_sensor_checks():
    d = guard.decide(reading(memory_pressure=4), {}, CFG)
    assert not d['pause']
    assert guard.decide(reading(memory_pressure=4), d['streaks'], CFG)['pause']
    unknown = reading(thermal_state=None, memory_pressure=None, cpu_speed_limit=None)
    s = {}
    for _ in range(3):
        d = guard.decide(unknown, s, CFG)
        s = d['streaks']
    assert d['pause'] and not d['emergency_terminate']


def test_pause_never_overwrites_user_file(tmp_path):
    pause = tmp_path / 'PAUSE'
    pause.write_text('user asked to pause')
    assert guard.request_pause(pause, ['heat']) == 'existing_pause_preserved'
    assert pause.read_text() == 'user asked to pause'


def test_owned_process_rejects_unrelated_script_shell_and_outside_path(monkeypatch):
    monkeypatch.setattr(Path, 'exists', lambda self: True)
    r = row()
    assert guard.owned_model(r, CFG)
    for cmd in ['/bin/bash -c "python3 scripts/serve_agent_expert_registry.py"',
                '/usr/bin/python3 scripts/unrelated.py --registry ' + str(guard.EXPERT / 'x'),
                '/usr/bin/python3 scripts/serve_agent_expert_registry.py --registry /tmp/x.json']:
        assert not guard.owned_model({**r, 'command': cmd}, CFG)
    assert not guard.owned_model({**r, 'uid': guard.current_owner() + 1}, CFG)
    assert not guard.owned_model({**r, 'cwd': '/tmp'}, CFG)


def test_pid_reuse_not_signalled(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, 'exists', lambda self: True)
    r = row()
    calls = []
    d = guard.decide(reading(thermal_state=3), {}, CFG)
    actions = guard.act(d, reading(model_processes=[r]), CFG, tmp_path / 'PAUSE',
                        process_reader=lambda: [{**r, 'started': 'different'}],
                        send_signal=lambda *args: calls.append(args))
    assert not calls and actions[-1]['action'] == 'identity_changed_skip'


def test_critical_terminates_only_exact_owned_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, 'exists', lambda self: True)
    r = row()
    calls = []
    d = guard.decide(reading(thermal_state=3), {}, CFG)
    guard.act(d, reading(model_processes=[r]), CFG, tmp_path / 'PAUSE',
              process_reader=lambda: [r], send_signal=lambda *args: calls.append(args))
    assert calls == [(r['pid'], guard.signal.SIGTERM)]


def test_warning_priority_reduction_only(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, 'exists', lambda self: True)
    r = row()
    calls = []
    d = guard.decide(reading(thermal_state=1), {}, CFG)
    guard.act(d, reading(model_processes=[r]), CFG, tmp_path / 'PAUSE',
              process_reader=lambda: [r], setpriority=lambda *args: calls.append(args))
    assert calls == [(guard.PRIORITY_SCOPE, r['pid'], 10)]
