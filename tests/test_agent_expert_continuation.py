"""No-model checks for the continuation protocol and model handoff."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts import run_agent_expert_continuation_queue as queue
from scripts.agent_expert_continuation_objective import numpy_audit

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".codex_artifacts/agent-rl-expert-expansion-20261102/continuation-002"


def test_training_schedule_covers_all_states_with_matched_exposure():
    states = {r["state_id"]: r for r in json.loads((OUT / "STATES.json").read_text())}
    order = json.loads((OUT / "ORDER.json").read_text())
    cfg = json.loads((OUT / "CONFIG.json").read_text())
    assert len(states) == 279 and len(order) == 64
    assert cfg["parents"]["E_sft"] == cfg["parents"]["D_rl"]
    assert {s for item in order for s in item["states"]} == set(states)
    for item in order:
        assert len(item["states"]) == 8
        assert sum(states[s]["origin"] == "new_reference_visited_state" for s in item["states"]) == 4


def test_rl_rejects_demonstration_target():
    with pytest.raises(ValueError, match="RL input contract"):
        numpy_audit([0.0] * 13, [0.0] * 13, route="D_rl", target=0, returns=[0.0] * 13)


def test_sft_rejects_rl_returns():
    with pytest.raises(ValueError, match="SFT input contract"):
        numpy_audit([0.0] * 13, [0.0] * 13, route="E_sft", target=0, returns=[0.0] * 13)


def test_handoff_never_stops_an_unrecognized_worker(tmp_path, monkeypatch):
    monkeypatch.setattr(queue, "listener", lambda: 1234)
    monkeypatch.setattr(queue, "health", lambda: {"registry_sha256": "other", "base_model_instances": 1})
    kill = Mock()
    monkeypatch.setattr(queue.os, "kill", kill)
    with pytest.raises(RuntimeError, match="Unexpected model service"):
        queue.stop_verified_worker(tmp_path)
    kill.assert_not_called()


def test_handoff_never_stops_an_unrecognized_process(tmp_path, monkeypatch):
    monkeypatch.setattr(queue, "listener", lambda: 1234)
    monkeypatch.setattr(queue, "health", lambda: {"registry_sha256": queue.ORIGINAL_SHA, "base_model_instances": 1})
    monkeypatch.setattr(queue.subprocess, "check_output", lambda *a, **kw: "unrelated_process")
    kill = Mock()
    monkeypatch.setattr(queue.os, "kill", kill)
    with pytest.raises(RuntimeError, match="Listener process identity mismatch"):
        queue.stop_verified_worker(tmp_path)
    kill.assert_not_called()


def test_handoff_requires_verified_process_exit(tmp_path, monkeypatch):
    listeners = iter([1234, None])
    monkeypatch.setattr(queue, "listener", lambda: next(listeners))
    monkeypatch.setattr(queue, "health", lambda: {"registry_sha256": queue.ORIGINAL_SHA, "base_model_instances": 1})
    monkeypatch.setattr(
        queue.subprocess, "check_output", lambda *a, **kw: "python scripts/serve_agent_expert_registry.py --port 18781"
    )
    monkeypatch.setattr(queue, "process_alive", lambda pid: False)
    kill = Mock()
    monkeypatch.setattr(queue.os, "kill", kill)
    queue.stop_verified_worker(tmp_path)
    kill.assert_called_once_with(1234, queue.signal.SIGTERM)
    assert json.loads((tmp_path / "WORKER_STOPPED.json").read_text())["confirmed_gone"]


def test_restore_refuses_to_load_second_model(tmp_path, monkeypatch):
    monkeypatch.setattr(queue, "listener", lambda: 1234)
    popen = Mock()
    monkeypatch.setattr(queue.subprocess, "Popen", popen)
    with pytest.raises(RuntimeError, match="do not load another model"):
        queue.restore_worker(tmp_path, tmp_path / "registry.json")
    popen.assert_not_called()
