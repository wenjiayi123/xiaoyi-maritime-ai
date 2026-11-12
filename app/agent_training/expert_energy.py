"""Explicit tool adapter for new energy evidence; never chooses the next action.

Read, compare, recover and verify are separate operations. A lost response
remains pending across restarts until the caller requests receipt readback.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from app.durable_file import publish_file

from .expert_contracts import assess_energy_option
from .live import local_request

API = "/api/optimization/expert-comparisons"


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def check_context(context):
    body = {k: v for k, v in context.items() if k != "source_version"}
    if (
        context.get("schema") != "expert-energy-source.v1"
        or context.get("production_authority") is not False
        or digest(body) != context.get("source_version")
    ):
        raise ValueError("invalid source context")


def check_receipt(receipt, expected):
    body = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
    if (
        receipt.get("schema") != "expert-energy-comparison.v1"
        or digest(body) != receipt.get("receipt_sha256")
        or receipt.get("parameters") != expected
        or receipt.get("request_id") != expected["request_id"]
        or receipt.get("request_sha256") != digest(expected)
        or receipt.get("production_authority") is not False
    ):
        raise ValueError("receipt identity, parameters or checksum mismatch")
    check_context(receipt["source_context"])
    if receipt["source_context"]["source_version"] != expected["expected_source_version"]:
        raise ValueError("receipt source differs from requested source")
    native = receipt["native_receipt"]
    if digest({k: v for k, v in native.items() if k != "receipt_sha256"}) != native.get("receipt_sha256"):
        raise ValueError("native receipt checksum mismatch")
    native_expected = {
        **expected,
        "expected_source_version": receipt["source_context"]["legacy_context"]["source_version"],
    }
    if native.get("parameters") != native_expected or native.get("request_sha256") != digest(native_expected):
        raise ValueError("native calculation parameters mismatch")
    alternatives = receipt["alternatives"]
    if len(alternatives) != 2 or len(native["alternatives"]) != 2:
        raise ValueError("expected two alternatives")
    for i, entry in enumerate(alternatives):
        params = {
            "green": expected["baseline_green_preference" if i == 0 else "green_preference"],
            "carbon": expected["carbon_price_cny_per_ton"],
        }
        raw = native["alternatives"][i]["raw"]
        if (
            entry["parameters"] != params
            or native["alternatives"][i]["parameters"] != params
            or entry["facts"]["raw_snapshot_sha256"] != digest(raw)
            or entry["facts"].get("production_authority") is not False
        ):
            raise ValueError("alternative identity or provenance mismatch")
    return [entry["facts"] for entry in alternatives]


class ExpertEnergyBackend:
    def __init__(self, folder, base="http://127.0.0.1:18810"):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.base = base
        self.path = self.folder / "energy-journal.json"
        self.state = {"base": base, "context": None, "pending": None, "receipt": None, "events": []}
        if self.path.exists():
            self.state = json.loads(self.path.read_text())
            if self.state["base"] != base:
                raise ValueError("saved endpoint differs")

    def save(self, operation, outcome):
        self.state["events"].append({"operation": operation, "outcome": outcome})
        temporary = self.path.with_suffix(".tmp")
        with temporary.open("w") as stream:
            json.dump(self.state, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        publish_file(temporary, self.path)

    def request(self, path, payload=None):
        return local_request(self.base, path, payload, timeout=60)

    def read_context(self):
        context = self.request(API + "/source-context")
        check_context(context)
        self.state["context"] = context
        self.save("read_context", {"source_version": context["source_version"]})
        return context

    def compare(self, parameters, request_id, *, withhold_response=False):
        if self.state["pending"]:
            raise RuntimeError("pending write requires explicit readback; no automatic resubmission")
        if not self.state["context"]:
            raise ValueError("read context before comparison")
        if set(parameters) != {"baseline_green_preference", "green_preference", "carbon_price_cny_per_ton"}:
            raise ValueError("explicit complete parameters required")
        payload = {
            **parameters,
            "request_id": request_id,
            "expected_source_version": self.state["context"]["source_version"],
        }
        self.state["pending"] = payload
        self.save("compare_intent", {"payload": payload})
        try:
            response = self.request(API, payload)
        except HTTPError as exc:
            if exc.code in {400, 401, 403, 409, 422}:
                self.state["pending"] = None
            self.save("compare_http_error", {"status": exc.code, "pending": bool(self.state["pending"])})
            raise
        except Exception as exc:
            self.save("compare_response_unknown", {"exception_type": type(exc).__name__})
            raise
        if withhold_response:
            path = self.folder / ("withheld-" + digest(payload) + ".json")
            path.write_text(json.dumps(response, ensure_ascii=False, indent=2) + "\n")
            self.save("response_withheld_by_engineering_probe", {"request_id": request_id})
            return {"response_received": False, "injected_response_loss": True}
        self.accept(response["receipt"], payload)
        return response

    def accept(self, receipt, expected):
        check_receipt(receipt, expected)
        self.state["receipt"] = receipt
        self.state["pending"] = None
        self.save("accept_receipt", {"receipt_sha256": receipt["receipt_sha256"]})

    def recover(self):
        expected = self.state["pending"]
        if not expected:
            raise ValueError("no pending calculation")
        response = self.request(API + "/" + expected["request_id"])
        self.accept(response["receipt"], expected)
        self.save("explicit_readback_recovery", {"new_calculation_performed": False})
        return response

    def verify(self, requirements):
        if self.state["pending"] or not self.state["receipt"]:
            raise ValueError("completed receipt required; recover pending result explicitly")
        saved = self.state["receipt"]
        response = self.request(API + "/" + saved["request_id"])
        if response["receipt"] != saved:
            raise ValueError("readback differs from persisted receipt")
        current = response["source_context_now"]
        check_context(current)
        if current["source_version"] != saved["source_context"]["source_version"]:
            raise ValueError("source changed; reread and recalculate before reporting")
        facts = check_receipt(saved, saved["parameters"])
        issues = [issue for fact in facts for issue in fact.get("issues", [])]
        if facts[0].get("scenario_id") != facts[1].get("scenario_id") or not facts[0].get("scenario_id"):
            issues.append("scenario_identity_missing_or_inconsistent")
        assessment = assess_energy_option(*facts, requirements)
        if issues:
            assessment["status"] = "needs_evidence"
            assessment["issues"].extend(issues)
        self.save("verify_business_requirements", assessment)
        return {
            "assessment": assessment,
            "alternatives": facts,
            "receipt_sha256": saved["receipt_sha256"],
            "decision_producer": "caller; this adapter does not select tools",
            "adapter_model_calls": 0,
            "production_authority": False,
        }
