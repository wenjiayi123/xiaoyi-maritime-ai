"""Negotiate over scoped historical candidates using signed, paired CarbonOps receipts."""

from __future__ import annotations
import hashlib
import json
from pathlib import Path
from urllib.request import Request, build_opener

from app.harness.contracts import digest
from app.harness.local_lock import ProcessLease
from app.harness.model import NoRedirect
from app.policy_release import PolicySelection, compare
from app.specialist_orders import EvidenceError, journal, save

PUBLISHED = (
    "http://127.0.0.1:8010/web/policy-evidence/constrained-dispatch-20261108.json"
)
RELEASE_SHA = "49c974460b3fbec1a0345d39084de33862cc3dfa96614b071ad97205edce451a"
OPTIONS = {
    "initial": ["initial"],
    "trained": ["initial", "learned"],
    "all": ["initial", "learned", "greedy"],
}
CRITERIA = {
    "energy": {"cost": ("cost", "lower"), "carbon": ("carbon_kg", "at_most")},
    "dispatch": {
        "service": ("processed_teu", "at_least"),
        "delay": ("delay_minutes", "at_most"),
    },
    "safety": {
        "safety": ("safety_violations", "zero"),
        "peak": ("peak_kw", "at_most"),
        "terminal_soc": ("ending_battery_soc", "at_least"),
    },
}


class HumanReviewRequested(EvidenceError):
    def __init__(self, key, role):
        super().__init__("独立复核员要求人工核对：" + role)
        self.key = key
        self.role = role


def historical_candidates(scope):
    old = compare(scope)
    opener = build_opener(NoRedirect)
    with opener.open(Request(PUBLISHED), timeout=12) as response:
        blob = response.read(2_000_001)
    if len(blob) > 2_000_000 or hashlib.sha256(blob).hexdigest() != RELEASE_SHA:
        raise EvidenceError("新候选发布原件校验失败")
    new = json.loads(blob)
    if (
        new["dataset"] != old["dataset_sha256"]
        or new["production_authority"] is not False
    ):
        raise EvidenceError("新旧策略的评测数据或权限不匹配")
    group = new["groups"][scope.baseline + "-" + scope.scenario]
    ref = group["base"][scope.window]
    if old["period"] != f"{ref['period']} / {ref['start']}":
        raise EvidenceError("新旧窗口不匹配")
    if any(
        abs(old["baseline_metrics"][k] - v) > 1e-5 for k, v in ref["metrics"].items()
    ):
        raise EvidenceError("新旧对照指标不匹配")
    candidates = {
        "initial": {
            "id": old["strategy"],
            "metrics": old["policy_metrics"],
            "published_checks": old["checks"],
            "source": old["release_sha256"],
            "weights": old["policy_sha256"],
        }
    }
    for key in ("learned", "greedy"):
        row = group["policies"][key][scope.window]
        if row["period"] != ref["period"] or row["start"] != ref["start"]:
            raise EvidenceError("候选窗口与对照不匹配")
        candidates[key] = {
            "id": "q59-protected" if key == "learned" else "hourly-enumeration",
            "metrics": row["metrics"],
            "published_checks": row["checks"],
            "source": RELEASE_SHA,
            "experiment": group["source_sha256"],
            "weights": new["weight"] if key == "learned" else None,
        }
    return {
        "selection": scope.model_dump(),
        "period": old["period"],
        "dataset": new["dataset"],
        "base": ref["metrics"],
        "candidates": candidates,
    }


def role_packet(book, choice, role):
    cand = book["candidates"][choice]
    measurements = {}
    for rule, (metric, direction) in CRITERIA[role].items():
        a, b = cand["metrics"][metric], book["base"][metric]
        measurements[rule] = {
            "metric": metric,
            "rule": direction,
            "candidate": a,
            "baseline": b,
            "candidate_minus_baseline": a - b,
        }
    return {
        "candidate": choice,
        "measurements": measurements,
        "source_sha256": cand["source"],
        "period": book["period"],
    }


def failures(packet):
    failed = []
    for key, v in packet["measurements"].items():
        a, b = v["candidate"], v["baseline"]
        passed = {
            "zero": a == 0,
            "lower": a < b,
            "at_most": a <= b + 1e-6,
            "at_least": a + 1e-6 >= b,
        }[v["rule"]]
        if not passed:
            failed.append(key)
    return failed


def object_schema(fields):
    return {
        "type": "object",
        "properties": fields,
        "required": list(fields),
        "additionalProperties": False,
    }


def record_turn(state, path, model, key, role, instruction, payload, schema, validate):
    stamp = digest([role, instruction, payload, schema])
    if state["status"] == "completed" and not state["turns"].get(key, {}).get(
        "accepted"
    ):
        raise EvidenceError("已归档的模型回函缺失")
    entry = state["turns"].setdefault(
        key, {"role": role, "packet": payload, "request_digest": stamp, "attempts": []}
    )
    if (
        entry["request_digest"] != stamp
        or entry["packet"] != payload
        or entry["role"] != role
    ):
        raise EvidenceError("已登记的谈判轮次输入发生变化")
    if entry.get("accepted") is not None:
        if (
            not entry["attempts"]
            or entry["attempts"][-1]["answer"] != entry["accepted"]
            or not entry["attempts"][-1]["trace"].get("id")
        ):
            raise EvidenceError("岗位回函缺少相应模型记录")
        validate(entry["accepted"])
        return entry["accepted"]
    prior = entry["attempts"]
    # Two fresh responses at most per resumption. A failed model turn is
    # auditable and never overrides the independent business check.
    for _ in range(2):
        data = {**payload}
        if prior:
            data["上次未通过原因"] = prior[-1]["error"]
        answer, trace = model.complete(
            "port_bargaining_turn", instruction, data, schema, 190
        )
        attempt = {"answer": answer, "trace": trace}
        try:
            validate(answer)
        except (KeyError, ValueError, TypeError) as exc:
            attempt["error"] = str(exc)
            prior.append(attempt)
            save(path, state)
            continue
        prior.append(attempt)
        entry["accepted"] = answer
        save(path, state)
        return answer
    raise EvidenceError("岗位输出连续两次与原始回执不符：" + role)


def reconciled_turn(
    state, path, model, key, role, instruction, payload, schema, validate, make_brief
):
    original = state["turns"].get(key)
    if (
        not original
        or original.get("accepted") is not None
        or len(original["attempts"]) < 2
    ):
        try:
            return record_turn(
                state, path, model, key, role, instruction, payload, schema, validate
            )
        except EvidenceError:
            original = state["turns"].get(key)
            if (
                not original
                or original.get("accepted") is not None
                or len(original["attempts"]) < 2
            ):
                raise
    if (
        original["request_digest"] != digest([role, instruction, payload, schema])
        or original["role"] != role
        or original["packet"] != payload
        or not all(x.get("error") for x in original["attempts"])
    ):
        raise EvidenceError("分歧必须能够回溯到同一任务的原始失败回函")
    # The secondary reviewer receives a deterministic arithmetic worksheet and
    # must issue a fresh, independently validated model decision. Record both.
    brief = {
        "来源输入": digest(payload),
        "首次岗位意见": original["attempts"][-1]["answer"],
        "独立复核表": make_brief(),
    }
    return record_turn(
        state,
        path,
        model,
        key + "-reconcile",
        role,
        instruction
        + " 本轮需纠正与已校验原件不一致的意见。以独立复核表逐项确认，再出具完整的新回函。",
        brief,
        schema,
        validate,
    )


def adjudicated_turn(
    state,
    path,
    model,
    key,
    role,
    instruction,
    payload,
    schema,
    validate,
    make_brief,
    computed,
):
    """Keep dissent visible. An independent reviewer can attest or refer the signed calculation."""
    secondary = state["turns"].get(key + "-reconcile", {})
    exhausted = len(secondary.get("attempts", [])) >= 2 and not secondary.get(
        "accepted"
    )
    if not exhausted:
        try:
            return reconciled_turn(
                state,
                path,
                model,
                key,
                role,
                instruction,
                payload,
                schema,
                validate,
                make_brief,
            )
        except EvidenceError:
            secondary = state["turns"].get(key + "-reconcile", {})
            if len(secondary.get("attempts", [])) < 2 or secondary.get("accepted"):
                raise
    first = state["turns"][key]
    if first["packet"] != payload or first["request_digest"] != digest(
        [role, instruction, payload, schema]
    ):
        raise EvidenceError("原始意见与本次核验输入不符")
    brief = make_brief()
    answer = computed()
    previous = {
        "来源输入": digest(payload),
        "首次岗位意见": first["attempts"][-1]["answer"],
        "独立复核表": brief,
    }
    if (
        secondary["packet"] != previous
        or secondary["role"] != role
        or first.get("accepted")
        or not all(
            a.get("error") and a.get("trace", {}).get("id")
            for a in first["attempts"] + secondary["attempts"]
        )
    ):
        raise EvidenceError("分歧记录缺少同一证据版本的原始岗位回函与复核回函")
    validate(answer)
    audit = {
        "待核实岗位": role,
        "原始来源": digest(payload),
        "复核数据": brief,
        "计算所得处置": answer,
        "签收范围": "仅确认历史数据的数值或表决结果；资料不支持时请转人工，现场授权始终关闭。",
    }

    def disposition(a):
        if a.get("decision") not in ("attest", "refer"):
            raise ValueError("必须签收计算或转人工核验")

    checked = record_turn(
        state,
        path,
        model,
        key + "-arbitration",
        "independent_review",
        "你是独立复核员。核对复核数据是否支持计算所得处置；能据此确认历史回执则 attest，数据互相矛盾、缺证或无法判断则 refer。不要把模拟送审当作生产执行。",
        audit,
        object_schema({"decision": {"enum": ["attest", "refer"]}}),
        disposition,
    )
    if checked["decision"] != "attest":
        raise HumanReviewRequested(key, role)
    note = {
        "source": "verified_calculation_with_independent_model_attestation",
        "disputed_role": role,
        "input_sha256": digest(payload),
        "computed_decision": answer,
        "model_receipt": state["turns"][key + "-arbitration"]["attempts"][-1]["trace"][
            "id"
        ],
    }
    if (
        state["status"] == "completed"
        and state.get("arbitrations", {}).get(key) != note
    ):
        raise EvidenceError("归档的仲裁依据不符")
    if state["status"] != "completed":
        state.setdefault("arbitrations", {})[key] = note
        save(path, state)
    return answer


def negotiate(root, gw, model, key, selection=None, alternatives=None, notify=print):
    needed = {"policy.energy", "policy.operations", "policy.safety", "policy.release"}
    if not needed <= gw.tools:
        raise PermissionError("当前身份不能读取全部历史策略会审工具")
    path = journal(Path(root) / "negotiations", gw.actor, key)
    lease = ProcessLease(path.with_suffix(".lock")).acquire()
    try:
        if path.exists():
            state = json.loads(path.read_bytes())
            if state["actor"] != gw.actor or state["key"] != key:
                raise PermissionError("协商工单归属不符")
            if (
                selection is not None
                and PolicySelection.model_validate(selection).model_dump()
                != state["selection"]
            ):
                raise ValueError("工单已绑定其他历史选择")
            if alternatives and alternatives != state["alternatives"]:
                raise ValueError("工单已绑定其他可选方案范围")
        else:
            scope = PolicySelection.model_validate(selection or {})
            if scope.window is None:
                raise ValueError("协商工单须指定历史窗口 0–11")
            alternatives = alternatives or "all"
            if alternatives not in OPTIONS:
                raise ValueError("未知可选方案范围")
            state = {
                "schema": 1,
                "actor": gw.actor,
                "key": key,
                "selection": scope.model_dump(),
                "alternatives": alternatives,
                "status": "running",
                "turns": {},
                "rounds": [],
                "production_authority": False,
            }
            save(path, state)
        book = historical_candidates(PolicySelection.model_validate(state["selection"]))
        identity = digest(book)
        if state.get("source_book_sha256", identity) != identity:
            raise EvidenceError("原始候选发布已改变")
        if state["status"] == "needs_human_review":
            review = state["manual_review"]
            entry = state["turns"][review["turn"] + "-arbitration"]
            if (
                state.get("book") != book
                or state["production_authority"] is not False
                or state["decision"]
                != {"choice": "no_change", "decision": "hold_for_human_review"}
                or review["disputed_role"] != state["turns"][review["turn"]]["role"]
                or entry["role"] != "independent_review"
                or review["request_sha256"] != entry["request_digest"]
                or review["reviewer_trace"] != entry["attempts"][-1]["trace"]["id"]
                or entry["accepted"] != {"decision": "refer"}
                or entry["attempts"][-1]["answer"] != entry["accepted"]
            ):
                raise EvidenceError("人工核对回执与归档来源不符")
            return state
        finished = state["status"] == "completed"
        if finished and (state.get("book") != book or not state.get("rounds")):
            raise EvidenceError("已归档协商工单与原件不符")
        prior_rounds = state["rounds"] if finished else None
        state["book"] = book
        state["source_book_sha256"] = identity
        budget = OPTIONS[state["alternatives"]]
        # Rebuild the public transcript from durable, independently validated
        # turns. A crash between a turn and the round update cannot duplicate an accepted reply.
        rounds = []
        rejected = []
        winner = "baseline"
        for number in range(1, len(budget) + 1):
            available = (
                ["initial"] if number == 1 else [k for k in budget if k not in rejected]
            )
            if not available:
                break
            offers = {k: role_packet(book, k, "energy") for k in available}
            history = [
                {"offer": r["choice"], "opinions": r["opinions"]} for r in rounds
            ]
            payload = {
                "可选提案": offers,
                "历轮岗位回函": history,
                "目标": "先评估提交方案；遭否决后从允许的其余方案选择成本最低者再审，成本相同时用列出的首项。",
            }

            def validate_choice(a):
                if a["choice"] not in available:
                    raise ValueError("提案超出允许范围")
                if a["choice"] != min(
                    available, key=lambda k: book["candidates"][k]["metrics"]["cost"]
                ):
                    raise ValueError("须比较扣除已否决方案后所有候选的实际成本")

            def ranked_costs():
                return [
                    {
                        "方案": k,
                        "实际成本": book["candidates"][k]["metrics"]["cost"],
                        "由低到高名次": i + 1,
                    }
                    for i, k in enumerate(
                        sorted(
                            available,
                            key=lambda k: book["candidates"][k]["metrics"]["cost"],
                        )
                    )
                ]

            offer = adjudicated_turn(
                state,
                path,
                model,
                f"{number}-offer",
                "energy",
                "你是能源提案岗。阅读历史反馈以及各候选的绝对成本，选择本轮提案。不得重复已否决提案。",
                payload,
                object_schema({"choice": {"enum": available}}),
                validate_choice,
                ranked_costs,
                lambda: {"choice": ranked_costs()[0]["方案"]},
            )["choice"]
            opinions = {}
            for role in CRITERIA:
                packet = role_packet(book, offer, role)
                expected = failures(packet)
                if set(expected) != {
                    k
                    for k in CRITERIA[role]
                    if not book["candidates"][offer]["published_checks"][k]
                }:
                    raise EvidenceError("独立阈值复算和已发布检查不一致")

                def validate_opinion(a):
                    wrong = [
                        k
                        for k in CRITERIA[role]
                        if a["checks"][k] != ("veto" if k in expected else "pass")
                    ]
                    if wrong:
                        raise ValueError(
                            "有数值方向须重核。请逐项重看 "
                            + ", ".join(wrong)
                            + " 的候选值减对照值。上限出现正差即失败，下限出现负差即失败。"
                        )
                    if a["verdict"] != ("veto" if expected else "pass"):
                        raise ValueError("有一项失败时整份意见必须 veto。")

                def review_sheet():
                    return {
                        k: {
                            "数值": v["candidate"],
                            "对照": v["baseline"],
                            "阈值类型": v["rule"],
                            "已核算是否满足": k not in expected,
                        }
                        for k, v in packet["measurements"].items()
                    }

                def numeric_decision():
                    return {
                        "checks": {
                            k: "veto" if k in expected else "pass"
                            for k in CRITERIA[role]
                        },
                        "verdict": "veto" if expected else "pass",
                    }

                turn_id = f"{number}-{role}"
                ack = adjudicated_turn(
                    state,
                    path,
                    model,
                    turn_id,
                    role,
                    "你是独立专业复核岗，逐行判定。candidate_minus_baseline 是候选减去对照的实算差值。对于 at_most，差值超过 0.000001 即 veto；at_least 差值小于 -0.000001 即 veto；lower 差值必须严格小于零；zero 要求候选值为零。先逐项给 checks，再给总体 verdict。任一项目 veto 即否决。资料只用于历史模拟。",
                    {"本岗": role, "待审提案": packet, "上轮分歧": history[-1:]},
                    object_schema(
                        {
                            "checks": object_schema(
                                {k: {"enum": ["pass", "veto"]} for k in CRITERIA[role]}
                            ),
                            "verdict": {"enum": ["pass", "veto"]},
                        }
                    ),
                    validate_opinion,
                    review_sheet,
                    numeric_decision,
                )
                opinions[role] = {
                    **ack,
                    "failed": [k for k, v in ack["checks"].items() if v == "veto"],
                    "receipt": digest(packet),
                    "source": packet["source_sha256"],
                }
                if turn_id in state.get("arbitrations", {}):
                    opinions[role]["basis"] = "independent_attestation"
            passed = all(v["verdict"] == "pass" for v in opinions.values())
            rounds.append(
                {
                    "round": number,
                    "choice": offer,
                    "opinions": opinions,
                    "passes": passed,
                }
            )
            if not finished:
                state["rounds"] = rounds
                save(path, state)
            notify(
                "第 "
                + str(number)
                + " 轮："
                + offer
                + (" 通过各岗复核" if passed else " 被否决")
            )
            if passed:
                winner = offer
                break
            rejected.append(offer)

        def validate_final(a):
            action = "保留对照" if winner == "baseline" else "送人工复核-" + winner
            if a["action"] != action:
                raise ValueError(
                    "请逐轮核对三份回函。只要有一个方案在同一轮获三岗通过，就选择送该方案人工复核。均未获通过才选保留对照。"
                )

        votes = [
            {
                "轮次": r["round"],
                "候选": r["choice"],
                "三岗回函": {role: v["verdict"] for role, v in r["opinions"].items()},
            }
            for r in rounds
        ]

        def tally():
            return [
                {
                    "待审候选": r["choice"],
                    "已签同意岗位": [
                        role
                        for role, v in r["opinions"].items()
                        if v["verdict"] == "pass"
                    ],
                    "否决数": sum(
                        v["verdict"] == "veto" for v in r["opinions"].values()
                    ),
                    "具备送人工复核资格": r["passes"],
                }
                for r in rounds
            ]

        answer = adjudicated_turn(
            state,
            path,
            model,
            "management",
            "management",
            "你是管理岗。从候选的逐轮投票形成一项处置。三岗都 pass 的候选送人工复核；每个候选都至少有一个 veto 时保留对照。送复核后仍须由人另行决定是否采用。",
            {"各轮投票": votes},
            object_schema(
                {"action": {"enum": ["保留对照", *["送人工复核-" + k for k in budget]]}}
            ),
            validate_final,
            tally,
            lambda: {
                "action": "保留对照" if winner == "baseline" else "送人工复核-" + winner
            },
        )
        final = {
            "choice": "baseline"
            if answer["action"] == "保留对照"
            else answer["action"].removeprefix("送人工复核-"),
            "decision": "retain_baseline"
            if answer["action"] == "保留对照"
            else "human_review",
        }
        if finished:
            if prior_rounds != rounds or state["decision"] != final:
                raise EvidenceError("重放与已交付决议不符")
            return state
        state.pop("last_error", None)
        state.update(status="completed", decision=final)
        save(path, state)
        return state
    except HumanReviewRequested as exc:
        entry = state["turns"][exc.key + "-arbitration"]
        state.update(
            status="needs_human_review",
            decision={"choice": "no_change", "decision": "hold_for_human_review"},
            manual_review={
                "turn": exc.key,
                "disputed_role": exc.role,
                "reviewer_trace": entry["attempts"][-1]["trace"]["id"],
                "request_sha256": entry["request_digest"],
            },
        )
        state.pop("last_error", None)
        save(path, state)
        return state
    except EvidenceError as exc:
        if "state" in locals() and state.get("status") not in (
            "completed",
            "needs_human_review",
        ):
            state["status"] = "needs_evidence"
            state["last_error"] = str(exc)
            save(path, state)
        raise
    finally:
        lease.release()
