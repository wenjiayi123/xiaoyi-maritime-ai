import json
from types import SimpleNamespace

import pytest
from app import policy_negotiation as deal
from app.specialist_orders import EvidenceError, journal


def book(scope):
    base = dict(
        cost=100,
        carbon_kg=50,
        processed_teu=99,
        delay_minutes=5,
        safety_violations=0,
        peak_kw=30,
        ending_battery_soc=0.5,
    )
    out = {"period": "2025-01", "dataset": "fixture", "base": base, "candidates": {}}
    for name, cost, peak in [
        ("initial", 99, 35),
        ("learned", 97, 30),
        ("greedy", 96, 29),
    ]:
        c = {
            "metrics": dict(base, cost=cost, peak_kw=peak),
            "source": "signed-test-source",
        }
        out["candidates"][name] = c
        c["published_checks"] = {
            k: k not in deal.failures(deal.role_packet(out, name, r))
            for r in deal.CRITERIA
            for k in deal.CRITERIA[r]
        }
    return out


class TestDriver:
    __test__ = False

    def __init__(self):
        self.calls = 0

    def complete(self, name, system, payload, schema, budget):
        self.calls += 1
        if "可选提案" in payload:
            offers = payload["可选提案"]
            result = {
                "choice": min(
                    offers, key=lambda k: offers[k]["measurements"]["cost"]["candidate"]
                )
            }
        elif "待审提案" in payload:
            packet = payload["待审提案"]
            failed = deal.failures(packet)
            result = {
                "checks": {
                    k: "veto" if k in failed else "pass" for k in packet["measurements"]
                },
                "verdict": "veto" if failed else "pass",
            }
        else:
            winner = next(
                (
                    r["候选"]
                    for r in payload["各轮投票"]
                    if all(v == "pass" for v in r["三岗回函"].values())
                ),
                "baseline",
            )
            result = {
                "action": "保留对照" if winner == "baseline" else "送人工复核-" + winner
            }
        return result, {"id": "test-" + str(self.calls)}


@pytest.mark.parametrize(
    ("alternatives", "winner"),
    [("initial", "baseline"), ("trained", "learned"), ("all", "greedy")],
)
def test_veto_counteroffer_and_idempotent_review(
    tmp_path, monkeypatch, alternatives, winner
):
    monkeypatch.setattr(deal, "historical_candidates", book)
    model = TestDriver()
    gw = SimpleNamespace(
        actor="alice",
        tools={"policy.energy", "policy.operations", "policy.safety", "policy.release"},
    )
    order = deal.negotiate(
        tmp_path,
        gw,
        model,
        "test-deal",
        {"window": 0},
        alternatives,
        notify=lambda _: None,
    )
    assert order["decision"]["choice"] == winner and not order["production_authority"]
    assert order["rounds"][0]["opinions"]["safety"]["failed"] == ["peak"]
    calls = model.calls
    if winner != "baseline":
        assert (
            order["turns"]["2-offer"]["packet"]["历轮岗位回函"][0]["opinions"]
            == order["rounds"][0]["opinions"]
        )
    again = deal.negotiate(tmp_path, gw, model, "test-deal", notify=lambda _: None)
    assert again == order and model.calls == calls
    with pytest.raises(ValueError):
        deal.negotiate(
            tmp_path, gw, model, "test-deal", {"window": 2}, notify=lambda _: None
        )
    path = journal(tmp_path / "negotiations", "alice", "test-deal")
    corrupt = json.loads(path.read_bytes())
    corrupt["rounds"][0]["passes"] = True
    path.write_text(json.dumps(corrupt), encoding="utf-8")
    with pytest.raises(EvidenceError):
        deal.negotiate(tmp_path, gw, model, "test-deal", notify=lambda _: None)


def test_review_requires_read_permissions(tmp_path):
    with pytest.raises(PermissionError):
        deal.negotiate(
            tmp_path,
            SimpleNamespace(actor="alice", tools=set()),
            None,
            "work-test",
            {"window": 0},
        )


def test_disputed_votes_require_a_separate_signed_model_reply(tmp_path, monkeypatch):
    monkeypatch.setattr(deal, "historical_candidates", book)

    class Reviewer(TestDriver):
        def complete(self, name, system, payload, schema, budget):
            if "独立复核表" in payload:
                self.calls += 1
                sheet = payload["独立复核表"]
                checks = {
                    k: "pass" if row["已核算是否满足"] else "veto"
                    for k, row in sheet.items()
                }
                return {
                    "checks": checks,
                    "verdict": "veto" if "veto" in checks.values() else "pass",
                }, {"id": "second-" + str(self.calls)}
            answer, trace = super().complete(name, system, payload, schema, budget)
            if (
                payload.get("本岗") == "safety"
                and payload["待审提案"]["candidate"] == "initial"
            ):
                return {
                    "checks": dict.fromkeys(answer["checks"], "pass"),
                    "verdict": "pass",
                }, trace
            return answer, trace

    model = Reviewer()
    gw = SimpleNamespace(
        actor="a",
        tools={"policy.energy", "policy.operations", "policy.safety", "policy.release"},
    )
    result = deal.negotiate(
        tmp_path,
        gw,
        model,
        "veto-test",
        {"window": 0},
        "trained",
        notify=lambda _: None,
    )
    assert (
        len(result["turns"]["1-safety"]["attempts"]) == 2
        and "accepted" not in result["turns"]["1-safety"]
    )
    assert result["turns"]["1-safety-reconcile"]["accepted"]["checks"]["peak"] == "veto"
    count = model.calls
    assert (
        result
        == deal.negotiate(tmp_path, gw, model, "veto-test", notify=lambda _: None)
        and count == model.calls
    )


@pytest.mark.parametrize("verdict", ["attest", "refer"])
def test_numeric_arbiter_retains_disagreement_and_respects_referral(tmp_path, verdict):
    def evaluate(a):
        if a != {"choice": "cheap"}:
            raise ValueError("原件成本较低者为 cheap")

    class Actor:
        def __init__(self):
            self.calls = 0

        def complete(self, name, system, payload, schema, budget):
            self.calls += 1
            response = (
                {"decision": verdict}
                if "计算所得处置" in payload
                else {"choice": "expensive"}
            )
            return response, {"id": "model-" + str(self.calls)}

    model = Actor()
    state = {"status": "running", "turns": {}}
    path = tmp_path / "order.json"

    def attempt():
        return deal.adjudicated_turn(
            state,
            path,
            model,
            "2-offer",
            "energy",
            "比较成本",
            {"cheap": 3, "expensive": 4},
            deal.object_schema({"choice": {"enum": ["cheap", "expensive"]}}),
            evaluate,
            lambda: {"cheap": 3, "expensive": 4},
            lambda: {"choice": "cheap"},
        )

    if verdict == "refer":
        with pytest.raises(EvidenceError, match="人工"):
            attempt()
        assert not state.get("arbitrations")
    else:
        assert attempt() == {"choice": "cheap"}
        assert state["arbitrations"]["2-offer"]["model_receipt"] == "model-5"
        assert attempt() == {"choice": "cheap"} and model.calls == 5
    assert not state["turns"]["2-offer"].get("accepted") and not state["turns"][
        "2-offer-reconcile"
    ].get("accepted")


def test_manual_referral_replays_without_resampling_or_release(tmp_path, monkeypatch):
    monkeypatch.setattr(deal, "historical_candidates", book)

    class CautiousReviewer(TestDriver):
        def complete(self, name, system, payload, schema, budget):
            if "各轮投票" in payload or "独立复核表" in payload:
                self.calls += 1
                return {"action": "送人工复核-initial"}, {"id": "m-" + str(self.calls)}
            if "计算所得处置" in payload:
                self.calls += 1
                return {"decision": "refer"}, {"id": "r-" + str(self.calls)}
            return super().complete(name, system, payload, schema, budget)

    gw = SimpleNamespace(
        actor="alice",
        tools={"policy.energy", "policy.operations", "policy.safety", "policy.release"},
    )
    model = CautiousReviewer()
    state = deal.negotiate(
        tmp_path, gw, model, "referral", {"window": 0}, "initial", notify=lambda _: None
    )
    assert state["status"] == "needs_human_review" and not state["production_authority"]
    assert state["decision"] == {
        "choice": "no_change",
        "decision": "hold_for_human_review",
    }
    calls = model.calls
    assert (
        state == deal.negotiate(tmp_path, gw, model, "referral", notify=lambda _: None)
        and model.calls == calls
    )
    path = journal(tmp_path / "negotiations", "alice", "referral")
    state["manual_review"]["reviewer_trace"] = "changed"
    path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(EvidenceError):
        deal.negotiate(tmp_path, gw, model, "referral", notify=lambda _: None)


def test_unsigned_candidate_release_is_refused_before_a_proposal(monkeypatch):
    from io import BytesIO
    from app.policy_release import PolicySelection

    monkeypatch.setattr(deal, "compare", lambda scope: {"dataset_sha256": "registered"})
    monkeypatch.setattr(
        deal,
        "build_opener",
        lambda *_: SimpleNamespace(open=lambda *a, **kw: BytesIO(b"{}")),
    )
    with pytest.raises(EvidenceError, match="原件校验"):
        deal.historical_candidates(PolicySelection(window=0))
