"""Low-cost macOS resource guard; no model imports, no unowned process control."""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import sys
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import file_lease as fcntl
EXPERT = ROOT / ".codex_artifacts/agent-rl-expert-expansion-20261102"
OWNER = "xiaoyi-resource-guard-001"
PRIORITY_SCOPE = getattr(os, "PRIO_PROCESS", None)


def current_owner():
    getuid = getattr(os, "getuid", None)
    return getuid() if getuid is not None else None


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temp.replace(path)


def command(args):
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=5, check=False)
        return proc.stdout.strip() if proc.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def thermal_state():
    """OS thermal category, NOT a temperature sensor in Celsius."""
    try:
        ctypes.CDLL('/System/Library/Frameworks/Foundation.framework/Foundation')
        objc = ctypes.CDLL('/usr/lib/libobjc.A.dylib')
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p
        obj = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(('objc_msgSend', objc))
        integer = ctypes.CFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p)(('objc_msgSend', objc))
        info = obj(objc.objc_getClass(b'NSProcessInfo'), objc.sel_registerName(b'processInfo'))
        state = integer(info, objc.sel_registerName(b'thermalState'))
        return state if state in range(4) else None
    except (OSError, AttributeError):
        return None


def processes():
    raw = command(['ps', '-axo', 'pid=,ppid=,uid=,ni=,%cpu=,rss=,lstart=,command=']) or ''
    rows = []
    for line in raw.splitlines():
        cells = line.strip().split(None, 11)
        if len(cells) != 12:
            continue
        try:
            row = dict(pid=int(cells[0]), ppid=int(cells[1]), uid=int(cells[2]),
                       nice=int(cells[3]), cpu_percent=float(cells[4]), rss_kb=int(cells[5]),
                       started=' '.join(cells[6:11]), command=cells[11])
            if 'agent_expert' in row['command'] and 'scripts/' in row['command']:
                cwd = command(['/usr/sbin/lsof', '-a', '-p', str(row['pid']), '-d', 'cwd', '-Fn']) or ''
                escaped_cwd = next((line[1:] for line in cwd.splitlines() if line.startswith('n')), None)
                row['cwd'] = decode_lsof_path(escaped_cwd) if escaped_cwd is not None else None
            rows.append(row)
        except ValueError:
            continue
    return rows


def decode_lsof_path(value):
    # lsof may print Chinese UTF8 bytes as literal backslash-x escapes.
    return re.sub(r'(?:\\x[0-9a-fA-F]{2})+',
                  lambda m: bytes.fromhex(m[0].replace('\\x', '')).decode('utf-8', errors='surrogateescape'), value)


def owned_model(row, config):
    owner = current_owner()
    if owner is None or row['uid'] != owner or row['pid'] in (os.getpid(), os.getppid()):
        return False
    if row.get('cwd') != str(ROOT):
        return False
    try:
        argv = shlex.split(row['command'])
    except ValueError:
        return False
    if len(argv) < 2 or not Path(argv[0]).name.lower().startswith('python'):
        return False
    script = Path(argv[1])
    script = script if script.is_absolute() else ROOT / script
    for allowed in config['allowed_models']:
        if script.resolve() != (ROOT / allowed['script']).resolve():
            continue
        try:
            index = argv.index(allowed['path_flag'])
            artifact = Path(argv[index + 1])
            artifact = artifact if artifact.is_absolute() else ROOT / artifact
            artifact.resolve().relative_to(EXPERT.resolve())
            # Both process arguments and current workspace must identify the experiment.
            return artifact.exists()
        except (ValueError, IndexError):
            continue
    return False


def same_identity(before, after):
    return all(before.get(k) == after.get(k) for k in ('pid', 'uid', 'started', 'command', 'cwd'))


def sample(config):
    thermal = thermal_state()
    pmset = command(['pmset', '-g', 'therm'])
    speed = re.search(r'CPU_Speed_Limit\s*=\s*(\d+)', pmset or '')
    pressure = command(['sysctl', '-n', 'kern.memorystatus_vm_pressure_level'])
    return dict(time=now(), thermal_state=thermal,
                thermal_name=['nominal', 'fair', 'serious', 'critical'][thermal] if thermal is not None else 'unknown',
                temperature_celsius=None, temperature_source='NSProcessInfo category and pmset; no Celsius sensor',
                cpu_speed_limit=int(speed[1]) if speed else None,
                memory_pressure=int(pressure) if pressure and pressure.isdigit() else None,
                swap=command(['sysctl', '-n', 'vm.swapusage']),
                free_disk_gib=shutil.disk_usage(ROOT).free / 2**30,
                model_processes=[p for p in processes() if owned_model(p, config)],
                pmset=pmset)


def decide(reading, streaks, config):
    thermal, memory = reading['thermal_state'], reading['memory_pressure']
    speed = reading['cpu_speed_limit']
    conditions = dict(serious=thermal is not None and thermal >= 2,
                      memory_critical=memory == 4,
                      throttled=speed is not None and speed < 70,
                      sensors_unknown=thermal is None and memory is None and speed is None)
    next_streaks = {k: streaks.get(k, 0) + 1 if v else 0 for k, v in conditions.items()}
    reasons = []
    if thermal == 3:
        reasons.append('critical_thermal')
    if next_streaks['serious'] >= config['sustained_samples']:
        reasons.append('sustained_serious_thermal')
    if next_streaks['memory_critical'] >= config['sustained_samples']:
        reasons.append('sustained_critical_memory_pressure')
    if next_streaks['throttled'] >= config['sustained_samples']:
        reasons.append('sustained_cpu_throttling')
    if reading['free_disk_gib'] < config['pause_disk_gib']:
        reasons.append('low_disk')
    if next_streaks['sensors_unknown'] >= 3:
        reasons.append('resource_sensors_unavailable')
    if len(reading['model_processes']) > 1:
        reasons.append('multiple_registered_model_processes')
    lower_priority = bool(thermal is not None and thermal >= 1 or memory == 2 or speed is not None and speed < 100)
    emergency = (thermal == 3 or next_streaks['serious'] >= config['stop_after_samples']
                 or next_streaks['memory_critical'] >= config['stop_after_samples'])
    return dict(pause=bool(reasons), reasons=reasons, lower_priority=lower_priority,
                emergency_terminate=emergency, streaks=next_streaks)


def request_pause(path, reasons):
    # Never overwrite/remove a user pause. Evaluation interruption is retained,
    # not relabelled as semantic failure or automatically rerun.
    record = dict(owner=OWNER, time=now(), reasons=reasons,
                  action='cooperative_stop_at_next_existing_boundary', auto_resume=False)
    try:
        with path.open('x') as stream:
            stream.write(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
        return 'created_owned_pause'
    except FileExistsError:
        return 'existing_pause_preserved'


def act(decision, reading, config, pause_path=EXPERT / 'PAUSE', process_reader=processes,
        setpriority=None, send_signal=os.kill):
    actions = []
    if decision['pause']:
        actions.append(dict(action=request_pause(pause_path, decision['reasons']), reasons=decision['reasons']))
    for row in reading['model_processes']:
        current = next((p for p in process_reader() if p['pid'] == row['pid']), None)
        if current is None or not same_identity(row, current) or not owned_model(current, config):
            actions.append(dict(action='identity_changed_skip', pid=row['pid']))
            continue
        try:
            if decision['emergency_terminate']:
                send_signal(row['pid'], signal.SIGTERM)
                actions.append(dict(action='sigterm_owned_model_resource_emergency', pid=row['pid']))
            elif decision['lower_priority'] and current['nice'] < config['nice_on_warning']:
                apply_priority = setpriority if setpriority is not None else getattr(os, 'setpriority', None)
                if PRIORITY_SCOPE is None or apply_priority is None:
                    actions.append(dict(action='priority_api_unavailable', pid=row['pid']))
                    continue
                apply_priority(PRIORITY_SCOPE, row['pid'], config['nice_on_warning'])
                actions.append(dict(action='lower_owned_model_scheduling_priority', pid=row['pid'],
                                    nice=config['nice_on_warning']))
        except (OSError, ProcessLookupError) as exc:
            actions.append(dict(action='control_error', pid=row['pid'], error=str(exc)))
    return actions


def main():
    if sys.platform != "darwin":
        raise SystemExit("This resource guard uses macOS thermal and process APIs. The Windows deployment uses its managed maintenance supervisor.")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text())
    out = args.config.parent
    with (out / 'guard.lock').open('a+') as guard_lock:
        fcntl.flock(guard_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        atomic_json(out / 'STARTED.json', dict(time=now(), pid=os.getpid(), config=str(args.config), model_loads=0))
        streaks = {}
        while not (out / 'STOP').exists():
            # Future experiment versions register their exact script here before
            # launch. Sensor/action thresholds remain recorded in each sample.
            cfg_raw = args.config.read_bytes()
            cfg = json.loads(cfg_raw)
            if cfg['interval_seconds'] != 30 or cfg['pause_disk_gib'] < 5 or cfg['sustained_samples'] > 2:
                raise ValueError('Resource configuration weakened unexpectedly')
            reading = sample(cfg)
            decision = decide(reading, streaks, cfg)
            streaks = decision['streaks']
            actions = act(decision, reading, cfg)
            record = dict(**reading, guard_pid=os.getpid(), decision=decision, actions=actions,
                          global_pause_exists=(EXPERT / 'PAUSE').exists(), automatic_resume=False,
                          config_sha256=hashlib.sha256(cfg_raw).hexdigest())
            # Log only a few KB per minute, retain all actions. No Torch/model import.
            with (out / 'samples.jsonl').open('a') as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + '\n')
            atomic_json(out / 'STATUS.json', record)
            if actions:
                with (out / 'actions.jsonl').open('a') as stream:
                    stream.write(json.dumps(dict(time=now(), actions=actions), ensure_ascii=False) + '\n')
            if args.once:
                break
            time.sleep(cfg['interval_seconds'])
        atomic_json(out / 'process-exit.json', dict(time=now(), pid=os.getpid(), exit_code=0))


if __name__ == '__main__':
    main()
