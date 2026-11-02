import copy
from types import SimpleNamespace

import pytest

from app.agent_training.environment_v3 import DynamicTask
from app.agent_training.environment_v4 import ReadableEnvironment
from app.agent_training.live_v4 import ReceiptBackend, ResponseUnknown, canonical_sha, native_step


def environment(shocks=()):
    return ReadableEnvironment(DynamicTask("native-contract-only", "contract", "joint", 1, shocks=shocks))


class TransportProbe:
    def __init__(self):
        self.calls = []

    def execute(self, action, env):
        self.calls.append((action["tool"], False))
        return {"contract_test": True}

    def calculate(self, system, parameters, env, *, lose_response=False):
        self.calls.append((system + ".compare", lose_response))
        return {"response_received": False}

    def record(self, action, result):
        return {"file": "probe.json", "sha256": canonical_sha(result), "tool": action["tool"]}


def test_lost_response_executes_once_and_verification_is_model_selected():
    env, backend = environment(("lost_receipt",)), TransportProbe()
    native_step(env, backend, "B")
    correct = next(
        k
        for k, a in env.actions.items()
        if a["tool"] == "energy.compare"
        and a["arguments"]["green_preference"] == env.task.green
        and a["arguments"]["carbon_price_cny_per_ton"] == env.task.carbon
    )
    first = native_step(env, backend, correct)
    assert first["native_executed"] and not first["ok"] and env.uncertain
    assert backend.calls == [("energy.read", False), ("energy.compare", True)]
    native_step(env, backend, correct)
    assert len(backend.calls) == 2  # no blind retry or hidden recovery
    native_step(env, backend, "I")
    assert backend.calls[-1] == ("execution.verify", False)
    assert not env.uncertain and not env.success


def test_read_timeout_does_not_contact_backend_or_auto_retry():
    env, backend = environment(("read_timeout",)), TransportProbe()
    row = native_step(env, backend, "B")
    assert row["injected_event"] and not row["native_executed"] and backend.calls == []
    native_step(env, backend, "B")
    assert backend.calls == [("energy.read", False)]


def test_unimplemented_native_shock_is_not_claimed_as_real():
    env, backend = environment(("port_revision",)), TransportProbe()
    with pytest.raises(ValueError, match="remain synthetic"):
        native_step(env, backend, "A")
    assert backend.calls == []


def test_durable_pending_post_is_recovered_without_resubmission(tmp_path, monkeypatch):
    backend = ReceiptBackend(tmp_path)
    backend.contexts["port"] = {"context_id": "a" * 64}
    stored, calls = {}, []

    def transport(system, path, payload=None):
        calls.append((system, path, payload))
        if payload is not None:
            body = {
                "parameters": payload,
                "request_sha256": canonical_sha(payload),
                "request_id": payload["request_id"],
                "production_authority": False,
                "source_context": {"declared_model_sha256": "b" * 64, "loaded_model_sha256": "b" * 64},
                "raw": {"available": True, "scenario": payload["scenario"], "series": {"p50": [{"kW": 3.0}]}},
            }
            body["receipt_sha256"] = canonical_sha(body)
            stored["receipt"] = body
            raise TimeoutError("POST committed but response was lost")
        return stored

    monkeypatch.setattr(backend, "request", transport)
    params = {"scenario": "high_density_berthing", "horizon_min": 60, "step_min": 15}
    env = SimpleNamespace(task=SimpleNamespace(case_id="contract-probe"))
    with pytest.raises(ResponseUnknown):
        backend.calculate("port", params, env)
    restored = ReceiptBackend(tmp_path)
    monkeypatch.setattr(restored, "request", transport)
    with pytest.raises(ResponseUnknown):
        restored.calculate("port", params, env)
    assert len(calls) == 1 and "port" in restored.pending
    assert restored.recover() == {"port": stored["receipt"]["receipt_sha256"]}
    assert len(calls) == 2 and calls[1][2] is None and restored.pending == {}
    assert ReceiptBackend(tmp_path).receipts == restored.receipts
    assert restored.evidence[0]["tool"] == "port.evaluate"
    corrupt = copy.deepcopy(stored["receipt"])
    corrupt["raw"]["series"]["p50"][0]["kW"] = 999
    with pytest.raises(ValueError, match="checksum"):
        restored.receipt_check(corrupt, stored["receipt"]["parameters"])
