"""Versioned native receipts for the readable action policy.

All action choices remain with the caller/model. The harness validates facts,
persists pending requests and exposes explicit recovery; it never chooses the
next action or silently retries a write. Synthetic source-revision shocks are
not accepted by this native adapter.
"""

import copy
import hashlib
import json
import os
from urllib.error import HTTPError

from .live import NativeBackend, digest, execution_origin, report_html, save


def canonical_sha(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


class NativeStale(ValueError):
    def __init__(self, system, detail):
        super().__init__(detail)
        self.system = system


class ResponseUnknown(RuntimeError):
    pass


class ReceiptBackend(NativeBackend):
    def __init__(self, folder):
        super().__init__(folder)
        self.urls["energy"] = os.getenv("AGENT_RL_RECEIPT_ENERGY_URL", "http://127.0.0.1:18809")
        self.urls["port"] = os.getenv("AGENT_RL_RECEIPT_PORT_URL", "http://127.0.0.1:18801")
        self.contexts, self.receipts, self.pending = {}, {}, {}
        self.decision_producer = "unspecified caller"
        journal = self.folder / "receipt-journal.json"
        if journal.exists():
            row = json.loads(journal.read_text())
            if row["urls"] != self.urls:
                raise ValueError("saved job endpoints differ from the configured endpoints")
            for key in ["contexts", "receipts", "pending", "evidence", "summaries", "clock_before", "clock_owned"]:
                setattr(self, key, row[key])

    def persist(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        row = {
            key: getattr(self, key)
            for key in [
                "urls",
                "contexts",
                "receipts",
                "pending",
                "evidence",
                "summaries",
                "clock_before",
                "clock_owned",
            ]
        }
        path = self.folder / "receipt-journal.json"
        temporary = path.with_suffix(".tmp")
        with temporary.open("w") as stream:
            json.dump(row, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
        descriptor = os.open(self.folder, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def record(self, action, data):
        result = super().record(action, data)
        self.persist()
        return result

    def read(self, target):
        if target == "port":
            raw = self.request("port", "/api/v3/runtime/agent/context")
            body = {k: v for k, v in raw.items() if k != "context_id"}
            if canonical_sha(body) != raw["context_id"] or raw.get("production_authority") is not False:
                raise ValueError("invalid port observation context")
            self.contexts[target] = raw
            self.summaries[target] = {
                "site_id": "CNSHA public benchmark",
                "observed_at": raw["captured_at"],
                "event_time": raw["snapshot"]["state"].get("source_timestamp"),
                "source_mode": raw["scope"],
                "metrics": [],
                "raw_sha256": digest(raw),
            }
        else:
            raw = super().read(target)
            if target == "energy":
                context = self.request("energy", "/api/optimization/agent-comparisons/source-context")
                if context.get("production_authority") is not False:
                    raise ValueError("invalid energy calculation context")
                self.contexts[target] = context
                raw = {"runtime_observation": raw, "calculation_context": context}
        self.persist()
        return raw

    @staticmethod
    def receipt_check(receipt, expected):
        body = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
        if (
            canonical_sha(body) != receipt.get("receipt_sha256")
            or receipt.get("parameters") != expected
            or receipt.get("request_sha256") != canonical_sha(expected)
            or receipt.get("production_authority") is not False
        ):
            raise ValueError("native receipt identity, parameters, authority or checksum mismatch")

    def accept_receipt(self, system, receipt):
        payload = self.pending[system]["payload"]
        self.receipt_check(receipt, payload)
        if system == "energy":
            from app.system_linkage import _compact_energy

            rows = receipt["alternatives"]
            if len(rows) != 2 or any(
                r["raw"].get("rl_environment", {}).get("dataset_sha256") != receipt["dataset_sha256"] for r in rows
            ):
                raise ValueError("energy receipt uses inconsistent datasets")
            self.summaries["energy_comparison"] = [
                {"parameters": r["parameters"], "summary": _compact_energy(r["raw"])} for r in rows
            ]
        else:
            raw = receipt["raw"]
            values = [float(row["kW"]) for row in raw.get("series", {}).get("p50", [])]
            if not values or raw.get("available") is not True or raw.get("scenario") != payload["scenario"]:
                raise ValueError("port receipt contains no valid calculation")
            info = {
                "parameters": payload,
                "points": len(values),
                "peak_kw": max(values),
                "average_kw": sum(values) / len(values),
            }
            source = receipt["source_context"]
            if source.get("declared_model_sha256") != source.get("loaded_model_sha256"):
                info["source_warning"] = (
                    "下游策略声明摘要与实际加载摘要不同；已同时记录，不据此认定既有港口策略版本通过验收。"
                )
            self.summaries["port_evaluation"] = info
        self.receipts[system] = receipt
        del self.pending[system]
        self.persist()

    def calculate(self, system, parameters, env, *, lose_response=False):
        if system in self.pending:
            raise ResponseUnknown("pending calculation requires receipt readback before any resubmission")
        context = self.contexts.get(system)
        if not context:
            raise NativeStale(system, "calculation context has not been read")
        if system == "energy":
            payload = {**parameters, "expected_source_version": context["source_version"]}
            path = "/api/optimization/agent-comparisons"
        else:
            payload = {**parameters, "context_id": context["context_id"]}
            path = "/api/v3/runtime/agent/evaluations"
        payload["request_id"] = (
            "xiaoyi-"
            + canonical_sha(
                {"job": self.folder.name, "task": env.task.case_id, "system": system, "parameters": payload}
            )[:48]
        )
        self.pending[system] = {"payload": payload, "path": path}
        self.persist()  # Durable intent precedes the POST.
        try:
            result = self.request(system, path, payload)
        except HTTPError as exc:
            if exc.code in {400, 403, 409, 422}:
                del self.pending[system]
                self.persist()
                if exc.code == 409:
                    raise NativeStale(system, "source context rejected; reread before recalculating") from exc
                raise
            raise ResponseUnknown("calculation response unavailable; explicit readback required") from exc
        except Exception as exc:
            raise ResponseUnknown("calculation response unavailable; explicit readback required") from exc
        if lose_response:
            # POST really ran and the native server persisted it. Hide its
            # result from the policy; only the next chosen verify may recover it.
            save(self.folder / ("withheld-" + payload["request_id"] + ".json"), result)
            return {"response_received": False, "injected_response_loss": True, "request_id": payload["request_id"]}
        self.accept_receipt(system, result["receipt"])
        return result

    def recover(self):
        recovered = {}
        for system, pending in list(self.pending.items()):
            response = self.request(system, pending["path"] + "/" + pending["payload"]["request_id"])
            self.accept_receipt(system, response["receipt"])
            self.record(
                {"tool": "energy.compare" if system == "energy" else "port.evaluate", "arguments": pending["payload"]},
                {"recovered_by_readback": True, "receipt": response["receipt"], "new_calculation_performed": False},
            )
            recovered[system] = response["receipt"]["receipt_sha256"]
        return recovered

    def verify(self, env):
        recovered = self.recover()
        if any(env.required[system] and system not in self.receipts for system in ["energy", "port"]):
            raise ValueError("required native calculation receipt is missing")
        checks = super().verify(env)
        for system, receipt in self.receipts.items():
            base = "/api/optimization/agent-comparisons" if system == "energy" else "/api/v3/runtime/agent/evaluations"
            response = self.request(system, base + "/" + receipt["request_id"])
            self.receipt_check(response["receipt"], receipt["parameters"])
            if response["receipt"] != receipt:
                raise ValueError("readback differs from persisted accepted result")
            current = (
                response["source_context_now"]["source_version"] == receipt["source_context"]["source_version"]
                if system == "energy"
                else response.get("context_current") is True
            )
            if not current:
                raise NativeStale(system, "calculation receipt expired or source changed")
            checks["checks"][system + "_durable_current_receipt"] = True
        checks["recovered_receipts"] = recovered
        return checks

    def execute(self, action, env):
        tool = action["tool"]
        if tool == "artifact.report":
            verification = self.verify(env)
            report = {
                "goal": env.task.goal(),
                "scope": "本机公开数据回放和工程模拟，非现场生产",
                "summaries": self.summaries,
                "verification": verification,
                "evidence": self.evidence.copy(),
                "decision_producer": self.decision_producer,
                "summary_producer": "deterministic renderer of verified tool facts; not free-form LLM writing",
            }
            save(self.folder / "report.json", report)
            description = {
                "rules": "本次为规则选择步骤的接口合同探针，未运行语言模型。",
                "model": "本次由语言模型选择执行步骤，无规则回退；单次完成不证明RL优于SFT。",
            }.get(self.decision_producer, "步骤由调用方选择；本记录未核实调用方是否为语言模型。")
            html = report_html(report).replace("模型负责选择执行步骤。", description)
            (self.folder / "report.html").write_text(html)
            return {
                "report": "report.json",
                "sha256": digest(report),
                "verification": verification["checks"],
                "decision_producer": self.decision_producer,
            }
        if tool in {"energy.compare", "port.evaluate"}:
            return self.calculate(tool.split(".")[0], action["arguments"], env)
        if tool == "execution.diagnose":
            return {
                "pending_receipts": list(self.pending),
                "observed_contexts": list(self.contexts),
                "guidance": "只读可重试；未知写入选择核验读回；过期计算需要重新读取。",
            }
        # Parent clock tools need the original runtime observation shape.
        if tool in {"energy.pause", "energy.restore"} or (tool == "execution.verify" and env.required["restore"]):
            raise ValueError("native V4 clock-control acceptance is not enabled yet")
        return super().execute(action, env)


def native_step(env, backend, label):
    if set(env.task.shocks) - {"read_timeout", "lost_receipt"} or env.task.require_restore:
        raise ValueError(
            "native adapter supports read timeout/real receipt loss; other dynamic events remain synthetic"
        )
    before, preview = copy.deepcopy(env), copy.deepcopy(env)
    transition = preview.step(label)
    tool = env.actions[label]["tool"]
    lost = transition["injected_event"] and tool == "energy.compare" and preview.uncertain
    execute = transition["ok"] or lost or tool == "execution.verify"
    if not execute:
        env.__dict__.update(preview.__dict__)
        transition.update(native_executed=False, backend_executed=False)
        return transition
    try:
        response = (
            backend.calculate("energy", env.actions[label]["arguments"], env, lose_response=True)
            if lost
            else backend.execute(env.actions[label], env)
        )
        evidence = backend.record(env.actions[label], response)
        if tool == "execution.verify" and response.get("recovered_receipts", {}).get("port"):
            preview.receipts["port"] = {"version": preview.current["port"], "scenario": preview.task.scenario}
            preview.verified = True
            preview.verified = all(preview.checks().values())
            preview.last = "全部结果核验通过" if preview.verified else "原生回执已读回，但任务仍有缺项"
            transition.update(ok=preview.verified, feedback=preview.last, after=preview.observation())
        env.__dict__.update(preview.__dict__)
        transition.update(
            native_executed=True,
            backend_executed=True,
            execution_origin=execution_origin(tool),
            native_evidence=evidence,
            native_result_valid=not lost,
        )
        transition["abstract_transition_result"] = transition["result"]
        transition["result"] = {
            "source": execution_origin(tool),
            "evidence_file": evidence["file"],
            "sha256": evidence["sha256"],
            "response_received": not lost,
        }
        if tool == "artifact.report":
            env.report = json.loads((backend.folder / "report.json").read_text())
        return transition
    except Exception as exc:
        if isinstance(exc, NativeStale):
            env.current[exc.system] += 1
            env.verified = False
        if isinstance(exc, ResponseUnknown) and tool == "energy.compare":
            # Keep the semantic candidate hidden until a successful readback.
            env.receipts["energy"] = {
                "version": env.current["energy"],
                "green": env.task.green,
                "carbon": env.task.carbon,
            }
            env.uncertain, env.verified = True, False
        env.last = "原生工具失败：" + str(exc)[:200]
        transition.update(
            ok=False,
            feedback=env.last,
            native_executed=True,
            backend_executed=True,
            native_result_valid=False,
            reward=None,
            reward_components={},
            after=env.observation(),
            observation=before.observation(),
        )
        env.steps.append(transition)
        env.done = len(env.steps) >= env.task.max_steps
        transition["after"]["remaining_steps"] = env.task.max_steps - len(env.steps)
        return transition
