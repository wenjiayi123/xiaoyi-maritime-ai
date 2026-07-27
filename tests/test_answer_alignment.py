from dataclasses import replace

from app.answer_verification import verify_answer
from app.model_gateway import ModelGateway
from app.models import ChatResponse, Evidence, SubquestionSupport
from app.settings import Settings
from app.xiaoyi import XiaoyiAI


def _evidence(
    snippet: str,
    *,
    title: str = "港航证据",
    citation_role: str = "supporting",
) -> Evidence:
    return Evidence(
        id="evidence-1",
        source="source.md",
        title=title,
        score=100.0,
        snippet=snippet,
        citation_role=citation_role,
    )


def test_exact_claim_evidence_alignment_passes() -> None:
    verification = verify_answer(
        "托运人负责取得并提交 VGM。[E1]",
        [_evidence("托运人负责取得并提交 VGM，用于编制积载计划。")],
        grounded=True,
    )

    assert verification.status == "passed"
    assert verification.evidence_alignment == 1.0
    assert verification.claims[0].alignment_basis == "exact"


def test_valid_citation_with_unrelated_claim_is_blocked() -> None:
    verification = verify_answer(
        "该船舶已经获得免检资格。[E1]",
        [_evidence("VGM 用于集装箱配载与安全作业。")],
        grounded=True,
    )

    assert verification.status == "needs_review"
    assert verification.claims[0].citation_valid is True
    assert verification.claims[0].supported is False
    assert any("词面主题对齐不足" in issue for issue in verification.issues)


def test_invented_percentage_is_blocked() -> None:
    verification = verify_answer(
        "该措施可把等待时间降低 25%。[E1]",
        [_evidence("该措施用于协调靠泊计划，需在现场验证实际效果。")],
        grounded=True,
    )

    assert verification.status == "needs_review"
    assert verification.numeric_integrity == 0.0
    assert verification.claims[0].unsupported_numeric_tokens == ["25%"]


def test_equivalent_date_formats_are_canonicalized() -> None:
    verification = verify_answer(
        "该通告自 2026年8月15日 生效。[E1]",
        [_evidence("该通告自 2026-08-15 生效。")],
        grounded=True,
    )

    assert verification.status == "passed"
    assert verification.claims[0].numeric_tokens == ["date:2026-08-15"]
    assert verification.numeric_integrity == 1.0


def test_wrong_date_is_blocked_even_when_topic_aligns() -> None:
    verification = verify_answer(
        "该通告自 2026年8月16日 生效。[E1]",
        [_evidence("该通告自 2026年8月15日 生效。")],
        grounded=True,
    )

    assert verification.status == "needs_review"
    assert verification.claims[0].unsupported_numeric_tokens == [
        "date:2026-08-16"
    ]


def test_leading_decimal_version_is_not_treated_as_a_list_number() -> None:
    verification = verify_answer(
        "[E1] 2.0 实施指南提供 OpenAPI 材料。",
        [_evidence("2.0 实施指南提供 OpenAPI 材料。")],
        grounded=True,
    )

    assert verification.status == "passed"
    assert verification.claims[0].numeric_tokens == ["2.0"]


def test_locator_only_evidence_cannot_support_a_claim() -> None:
    verification = verify_answer(
        "该规则已经生效。[E1]",
        [
            _evidence(
                "官方目录可用于定位正式文本。",
                citation_role="locator_only",
            )
        ],
        grounded=True,
    )

    assert verification.status == "needs_review"
    assert verification.citation_validity == 0.0


def test_multiple_citations_can_jointly_support_one_claim() -> None:
    evidence = [
        _evidence("VGM 是核实的集装箱总重量。"),
        Evidence(
            id="evidence-2",
            source="source-2.md",
            title="责任主体",
            score=99.0,
            snippet="托运人负责取得并提交 VGM。",
        ),
    ]

    verification = verify_answer(
        "VGM 是核实的集装箱总重量，托运人负责取得并提交 VGM。[E1][E2]",
        evidence,
        grounded=True,
    )

    assert verification.status == "passed"
    assert verification.claims[0].evidence_ids == ["evidence-1", "evidence-2"]


def test_non_factual_request_for_more_context_does_not_require_citation() -> None:
    verification = verify_answer(
        (
            "保留原 ETA，并记录更新时间和变更原因。[E1]\n"
            "若需进一步细化，需补充具体港口、对象或日期。"
        ),
        [_evidence("保留原 ETA，并记录更新时间和变更原因。")],
        grounded=True,
    )

    assert verification.status == "passed"
    assert verification.claim_count == 1


def test_factual_claim_after_conditional_prefix_is_still_checked() -> None:
    verification = verify_answer(
        "若需进一步确认，该船已经获得免检资格。[E1]",
        [_evidence("VGM 用于集装箱配载与安全作业。")],
        grounded=True,
    )

    assert verification.status == "needs_review"
    assert verification.claim_count == 1


def test_model_rewrite_cannot_replace_index_locked_conclusion() -> None:
    configuration = replace(
        Settings.from_env(),
        model_provider="openai_compatible",
        model_base_url="https://model.example.test/v1",
        model_name="approved-model",
        model_api_key="fixture-value",
        model_external_data_allowed=True,
        model_max_retries=0,
    )
    gateway = ModelGateway(configuration)
    gateway._request = lambda question, response: "该船舶已获免检资格。[E1]"  # type: ignore[method-assign]
    local = ChatResponse(
        app="小懿",
        mode="expert",
        intent="knowledge_qa",
        question="VGM 是什么？",
        answer="VGM 是核实的集装箱总重量。[E1]",
        evidence=[_evidence("VGM 是核实的集装箱总重量。")],
        confidence="high",
        next_questions=[],
        grounded=True,
        source_quality="internal_curated",
    )

    result = gateway.enhance(local.question, local)

    assert result.answer.startswith(
        "证据锁定结论：\nVGM 是核实的集装箱总重量。[E1]"
    )
    assert "该船舶已获免检资格" not in result.answer
    assert "模型综合建议（需人工复核）：" in result.answer
    assert "建议先明确业务对象与执行责任人" in result.answer
    assert result.generation_fallback is False
    assert "索引锁定关键事实" in (result.generation_notice or "")


def test_identity_uses_generation_with_locked_developer_identity(
    monkeypatch,
) -> None:
    configuration = replace(
        Settings.from_env(),
        model_provider="openai_compatible",
        model_base_url="http://127.0.0.1:11435/v1",
        model_name="xiaoyi-local-4b",
        model_max_retries=0,
        minimum_answer_review_seconds=3.0,
    )
    gateway = ModelGateway(configuration)
    sleeps: list[float] = []
    calls: list[str] = []
    monkeypatch.setattr("app.model_gateway.time.sleep", sleeps.append)
    gateway._request = lambda question, response: (  # type: ignore[method-assign]
        calls.append(question)
        or "我可以提供港航知识问答、运营建议与来源追溯。"
    )
    local = ChatResponse(
        app="小懿",
        mode="expert",
        intent="identity",
        question="你来自哪里？",
        answer="你好，我是小懿AI港航行业智能助手，由AI博士温家懿研发。",
        evidence=[],
        confidence="low",
        next_questions=[],
        grounded=False,
        refusal_reason="insufficient_index_evidence",
        completion_status="refused",
    )

    result = gateway.enhance(local.question, local)

    assert "由AI博士温家懿研发" in result.answer
    assert "独立研发" not in result.answer
    assert "随时可交流的港航数字同事" in result.answer
    assert "未检索到可支持当前结论的本地证据索引" not in result.answer
    assert result.refusal_reason is None
    assert result.completion_status == "complete"
    assert result.generation_fallback is False
    assert result.generation_provider == "openai_compatible"
    assert calls == [local.question]
    assert sleeps == [3.0]
    assert "混合链路" in (result.generation_notice or "")


def test_grounded_daily_operations_question_uses_hybrid_generation() -> None:
    configuration = replace(
        Settings.from_env(),
        model_provider="openai_compatible",
        model_base_url="http://127.0.0.1:11435/v1",
        model_name="xiaoyi-local-4b",
        model_max_retries=0,
    )
    gateway = ModelGateway(configuration)
    calls: list[str] = []
    gateway._request = lambda question, response: (  # type: ignore[method-assign]
        calls.append(question)
        or "先定位峰值贡献设备，划分可移峰负荷并复核生产约束。[E1]"
    )
    local = ChatResponse(
        app="小懿",
        mode="expert",
        intent="energy_carbon",
        question="如何削峰？",
        answer="先定位峰值贡献设备，再划分可移峰负荷并复核生产约束。[E1]",
        evidence=[
            Evidence(
                id="peak-1",
                source="energy.md",
                title="港口如何削峰",
                score=100.0,
                snippet="先定位峰值贡献设备，再划分可移峰负荷并复核生产约束。",
            )
        ],
        confidence="medium",
        next_questions=[],
        grounded=True,
        evidence_coverage=1.0,
    )

    result = gateway.enhance(local.question, local)

    assert result.answer.startswith(f"证据锁定结论：\n{local.answer}")
    assert "模型综合建议（需人工复核）：" in result.answer
    assert "划分可移峰负荷并复核生产约束" in result.answer
    assert calls == [local.question]
    assert result.generation_provider == "openai_compatible"
    assert result.generation_model == "xiaoyi-local-4b"
    assert result.generation_fallback is False


def test_grounded_locked_core_keeps_distinct_steps_from_same_evidence() -> None:
    local = ChatResponse(
        app="小懿",
        mode="expert",
        intent="sop",
        question="港口着火怎么办？",
        answer=(
            "建议执行顺序：\n"
            "1. 立即报警并启动消防应急预案。[E1]\n"
            "2. 疏散人员并建立警戒区。[E1]\n"
            "3. 切断相关能源和设备运行。[E1]"
        ),
        evidence=[
            _evidence(
                "立即报警并启动消防应急预案。疏散人员并建立警戒区。"
                "切断相关能源和设备运行。"
            )
        ],
        confidence="medium",
        next_questions=[],
        grounded=True,
    )

    core = ModelGateway._grounded_locked_core(local)

    assert "立即报警" in core
    assert "疏散人员" in core
    assert "切断相关能源" in core
    assert core.count("[E1]") == 3


def test_uncited_model_advisory_does_not_dilute_evidence_verification() -> None:
    verification = verify_answer(
        (
            "证据锁定结论：\n"
            "立即报警并启动消防应急预案。[E1]\n\n"
            "模型综合建议（需人工复核）：\n"
            "建议由现场负责人结合人员暴露情况复核处置顺序。"
        ),
        [_evidence("立即报警并启动消防应急预案。")],
        grounded=True,
    )

    assert verification.status == "passed"
    assert verification.claim_count == 1
    assert "不得作为已核验事实" in verification.scope_notice


def test_grounded_model_advisory_is_limited_to_two_paragraphs() -> None:
    configuration = replace(
        Settings.from_env(),
        model_provider="openai_compatible",
        model_base_url="http://127.0.0.1:11435/v1",
        model_name="xiaoyi-local-4b",
        model_max_retries=0,
    )
    gateway = ModelGateway(configuration)
    gateway._request = lambda *_args, **_kwargs: (  # type: ignore[method-assign]
        "建议由现场负责人统一协调消防、安全和调度岗位。"
        "先明确执行顺序与反馈渠道。"
        "执行过程中保持信息同步并记录关键节点。"
        "处置后复核现场条件与恢复边界。"
        "发现异常时由责任岗位重新评估处置顺序。"
        "确认风险受控后再进入后续闭环。"
    )
    local = ChatResponse(
        app="小懿",
        mode="expert",
        intent="sop",
        question="港口着火怎么办？",
        answer="立即报警并启动消防应急预案。[E1]",
        evidence=[_evidence("立即报警并启动消防应急预案。")],
        confidence="medium",
        next_questions=[],
        grounded=True,
    )

    result = gateway.enhance(local.question, local)
    advisory = result.answer.split("模型综合建议（需人工复核）：\n", 1)[1]

    assert len(advisory.split("\n\n")) == 2
    assert all(
        paragraph.count("。") == 3
        for paragraph in advisory.split("\n\n")
    )
    assert "统一协调消防、安全和调度岗位" in advisory
    assert "确认风险受控后再进入后续闭环" in advisory


def test_partial_compound_answer_generates_advice_for_uncovered_followup() -> None:
    configuration = replace(
        Settings.from_env(),
        model_provider="openai_compatible",
        model_base_url="http://127.0.0.1:11435/v1",
        model_name="xiaoyi-local-4b",
        model_max_retries=0,
    )
    gateway = ModelGateway(configuration)
    calls: list[str] = []
    gateway._request = lambda question, response: (  # type: ignore[method-assign]
        calls.append(question)
        or (
            "危险货物管理岗位通常负责核对货物识别信息和处置方案。"
            "安全管理岗位应复核警戒隔离与人员防护条件。"
            "现场负责人负责汇总各岗位意见并确认指令一致。"
            "具体签字权限仍需对照本港应急预案和授权清单。"
            "信息不完整时应维持隔离并补齐资料后再次评估。"
            "只有授权岗位确认风险受控后才能进入后续闭环。"
        )
    )
    local = ChatResponse(
        app="小懿",
        mode="expert",
        intent="compound_analysis",
        question="危险品箱渗漏怎么处置？追问：那谁负责复核？",
        answer=(
            "### 子问题 1：危险品箱渗漏怎么处置\n\n"
            "不能凭经验直接转移，应停止无关作业并控制人员接近。[E1]\n\n"
            "### 子问题 2：追问：那谁负责复核？\n\n"
            "当前索引未找到足够匹配且可审计的证据。"
        ),
        evidence=[
            _evidence("不能凭经验直接转移，应停止无关作业并控制人员接近。")
        ],
        confidence="medium",
        next_questions=[],
        grounded=True,
        refusal_reason="partial_evidence",
        completion_status="partial",
        subquestion_support=[
            SubquestionSupport(
                question="危险品箱渗漏怎么处置",
                covered=True,
                evidence_ids=["evidence-1"],
            ),
            SubquestionSupport(
                question="追问：那谁负责复核？",
                covered=False,
                refusal_reason="insufficient_index_evidence",
            ),
        ],
    )

    result = gateway.enhance(local.question, local)
    advisory = result.answer.split("模型综合建议（需人工复核）：\n", 1)[1]

    assert calls == [local.question]
    assert result.generation_fallback is False
    assert "危险货物管理岗位通常负责" in advisory
    assert len(advisory.split("\n\n")) == 2
    assert all(paragraph.count("。") == 3 for paragraph in advisory.split("\n\n"))
    assert "具体责任人和签批权限仍应以本港制度" in advisory
    assert "追问：那谁负责复核？" in gateway._messages(
        local.question,
        local,
    )[-1]["content"]


def test_partial_compound_official_full_text_boundary_still_skips_model() -> None:
    configuration = replace(
        Settings.from_env(),
        model_provider="openai_compatible",
        model_base_url="http://127.0.0.1:11435/v1",
        model_name="xiaoyi-local-4b",
        model_max_retries=0,
    )
    gateway = ModelGateway(configuration)
    calls: list[str] = []
    gateway._request = lambda question, response: calls.append(question) or "不应调用"  # type: ignore[method-assign]
    local = ChatResponse(
        app="小懿",
        mode="expert",
        intent="compound_analysis",
        question="VGM 的目的是什么，同时 SOLAS VI/2 的条款原文是什么？",
        answer="VGM 用于集装箱配载与安全作业。[E1]",
        evidence=[_evidence("VGM 用于集装箱配载与安全作业。")],
        confidence="medium",
        next_questions=[],
        grounded=True,
        refusal_reason="partial_evidence",
        completion_status="partial",
        subquestion_support=[
            SubquestionSupport(
                question="VGM 的目的是什么？",
                covered=True,
                evidence_ids=["evidence-1"],
            ),
            SubquestionSupport(
                question="SOLAS VI/2 的条款原文是什么？",
                covered=False,
                refusal_reason="official_full_text_required",
            ),
        ],
    )

    result = gateway.enhance(local.question, local)

    assert calls == []
    assert result.generation_fallback is True
    assert "严格证据边界已触发" in (result.generation_notice or "")


def test_stream_yields_empty_heartbeats_without_exposing_unverified_text(
    monkeypatch,
) -> None:
    configuration = replace(
        Settings.from_env(),
        model_provider="openai_compatible",
        model_base_url="http://127.0.0.1:11435/v1",
        model_name="xiaoyi-local-4b",
        model_max_retries=0,
    )
    gateway = ModelGateway(configuration)
    local = ChatResponse(
        app="小懿",
        mode="expert",
        intent="energy_carbon",
        question="如何削峰？",
        answer="先定位峰值贡献设备并复核生产约束。[E1]",
        evidence=[
            Evidence(
                id="peak-1",
                source="energy.md",
                title="港口如何削峰",
                score=100.0,
                snippet="先定位峰值贡献设备并复核生产约束。",
            )
        ],
        confidence="medium",
        next_questions=[],
        grounded=True,
        evidence_coverage=1.0,
    )
    gateway._request_stream = lambda *_args, **_kwargs: iter(  # type: ignore[method-assign]
        ["先定位峰值贡献设备，", "并复核生产约束。[E1]"]
    )
    clock = iter([0.0, 0.0, 0.6, 0.7])
    monkeypatch.setattr("app.model_gateway.time.monotonic", lambda: next(clock))

    stream = gateway.enhance_stream(local.question, local)
    prefix = next(stream)
    heartbeat = next(stream)
    suffix = next(stream)

    assert prefix.startswith("证据锁定结论：")
    assert heartbeat == ""
    assert "先定位峰值贡献设备" in suffix


def test_local_model_request_disables_hidden_thinking_tokens() -> None:
    configuration = replace(
        Settings.from_env(),
        model_provider="openai_compatible",
        model_base_url="http://127.0.0.1:11435/v1",
        model_name="xiaoyi-local-4b",
    )
    gateway = ModelGateway(configuration)
    local = ChatResponse(
        app="小懿",
        mode="expert",
        intent="energy_carbon",
        question="如何削峰？",
        answer="先定位峰值贡献设备并复核生产约束。[E1]",
        evidence=[
            Evidence(
                id="peak-1",
                source="energy.md",
                title="港口如何削峰",
                score=100.0,
                snippet="先定位峰值贡献设备并复核生产约束。",
            )
        ],
        confidence="medium",
        next_questions=[],
        grounded=True,
        evidence_coverage=1.0,
    )

    request_body = gateway._request_body(
        local.question,
        local,
        stream=True,
    )

    assert request_body["chat_template_kwargs"] == {
        "enable_thinking": False,
    }


def test_grounded_answer_holds_configured_review_window(monkeypatch) -> None:
    configuration = replace(
        Settings.from_env(),
        model_provider="openai_compatible",
        model_base_url="http://127.0.0.1:11435/v1",
        model_name="xiaoyi-local-4b",
        minimum_answer_review_seconds=3.0,
    )
    gateway = ModelGateway(configuration)
    sleeps: list[float] = []
    monkeypatch.setattr("app.model_gateway.time.sleep", sleeps.append)
    gateway._request = lambda *_args, **_kwargs: "按船期划分移峰窗口。[E1]"  # type: ignore[method-assign]
    local = ChatResponse(
        app="小懿",
        mode="expert",
        intent="energy_carbon",
        question="如何削峰？",
        answer="先定位峰值贡献设备，再划分可移峰负荷并复核生产约束。[E1]",
        evidence=[
            Evidence(
                id="peak-1",
                source="energy.md",
                title="港口如何削峰",
                score=100.0,
                snippet="先定位峰值贡献设备，再划分可移峰负荷并复核生产约束。",
            )
        ],
        confidence="medium",
        next_questions=[],
        grounded=True,
        evidence_coverage=1.0,
    )

    result = gateway.enhance(local.question, local)

    assert sleeps == [3.0]
    assert result.generation_provider == "openai_compatible"
    assert "索引锁定关键事实" in (result.generation_notice or "")


def test_general_answer_uses_model_but_strict_boundary_skips_generation(
    monkeypatch,
) -> None:
    configuration = replace(
        Settings.from_env(),
        model_provider="openai_compatible",
        model_base_url="http://127.0.0.1:11435/v1",
        model_name="xiaoyi-local-4b",
        minimum_answer_review_seconds=3.0,
    )
    gateway = ModelGateway(configuration)
    sleeps: list[float] = []
    calls: list[str] = []
    monkeypatch.setattr("app.model_gateway.time.sleep", sleeps.append)
    gateway._request = lambda question, response: (  # type: ignore[method-assign]
        calls.append(question)
        or (
            "应先报告值班负责人并避免承担高风险岗位。"
            if response.intent == "workforce_daily"
            else "请向法规主管取得现行官方全文并由责任岗位复核。"
        )
    )
    workforce = ChatResponse(
        app="小懿",
        mode="expert",
        intent="workforce_daily",
        question="我昨晚没睡好",
        answer="先休息，再评估港航高风险岗位是否需要替岗。",
        evidence=[],
        confidence="medium",
        next_questions=[],
        grounded=False,
    )
    boundary = ChatResponse(
        app="小懿",
        mode="expert",
        intent="port_knowledge",
        question="某法规具体限值是多少？",
        answer="需要现行官方全文才能确认。",
        evidence=[],
        confidence="low",
        next_questions=[],
        grounded=False,
        refusal_reason="official_full_text_required",
    )

    workforce_result = gateway.enhance(workforce.question, workforce)
    boundary_result = gateway.enhance(boundary.question, boundary)

    assert sleeps == [3.0, 3.0]
    assert calls == [workforce.question]
    assert workforce_result.generation_provider == "openai_compatible"
    assert boundary_result.generation_provider == "openai_compatible"
    assert boundary_result.generation_fallback is True
    assert "严格证据边界已触发" in (boundary_result.generation_notice or "")
    assert boundary_result.refusal_reason == "official_full_text_required"
    assert boundary_result.answer == "需要现行官方全文才能确认。"


def test_generated_stream_holds_only_before_first_token(monkeypatch) -> None:
    configuration = replace(
        Settings.from_env(),
        model_provider="openai_compatible",
        model_base_url="http://127.0.0.1:11435/v1",
        model_name="xiaoyi-local-4b",
        minimum_answer_review_seconds=3.0,
    )
    gateway = ModelGateway(configuration)
    sleeps: list[float] = []
    monkeypatch.setattr("app.model_gateway.time.sleep", sleeps.append)
    gateway._request_stream = lambda *_args, **_kwargs: iter(["你", "好"])  # type: ignore[method-assign]
    local = ChatResponse(
        app="小懿",
        mode="expert",
        intent="greeting",
        question="你好",
        answer="你好",
        evidence=[],
        confidence="low",
        next_questions=[],
        grounded=False,
    )

    stream = gateway.enhance_stream(local.question, local)

    assert next(stream) == "你好"
    assert sleeps == [3.0]


def test_grounded_stream_emits_locked_conclusion_before_model_synthesis(
    monkeypatch,
) -> None:
    configuration = replace(
        Settings.from_env(),
        model_provider="openai_compatible",
        model_base_url="http://127.0.0.1:11435/v1",
        model_name="xiaoyi-local-4b",
        minimum_answer_review_seconds=3.0,
    )
    gateway = ModelGateway(configuration)
    sleeps: list[float] = []
    upstream_events: list[str] = []
    monkeypatch.setattr("app.model_gateway.time.sleep", sleeps.append)

    def generated(*_args, **_kwargs):
        upstream_events.append("started")
        yield "先定位峰值贡献设备。[E1]"

    gateway._request_stream = generated  # type: ignore[method-assign]
    local = ChatResponse(
        app="小懿",
        mode="expert",
        intent="energy_carbon",
        question="如何削峰？",
        answer="先定位峰值贡献设备并划分可移峰负荷。[E1]",
        evidence=[
            Evidence(
                id="peak-1",
                source="energy.md",
                title="港口削峰",
                score=100.0,
                snippet="先定位峰值贡献设备并划分可移峰负荷。",
            )
        ],
        confidence="medium",
        next_questions=[],
        grounded=True,
    )

    stream = gateway.enhance_stream(local.question, local)

    first = next(stream)
    assert first.startswith("证据锁定结论：")
    assert local.answer in first
    assert "模型综合建议（需人工复核）：" in first
    assert upstream_events == []
    assert sleeps == []

    second = next(stream)
    assert second == "先定位峰值贡献设备。"
    assert sleeps == [3.0]
    assert upstream_events == ["started"]
    assert f"{first}{second}".startswith(
        f"证据锁定结论：\n{local.answer}"
    )


def test_identity_stream_emits_complete_humanized_answer_without_partial_gap(
    monkeypatch,
) -> None:
    configuration = replace(
        Settings.from_env(),
        model_provider="openai_compatible",
        model_base_url="http://127.0.0.1:11435/v1",
        model_name="xiaoyi-local-4b",
        minimum_answer_review_seconds=3.0,
    )
    gateway = ModelGateway(configuration)
    sleeps: list[float] = []
    monkeypatch.setattr("app.model_gateway.time.sleep", sleeps.append)
    gateway._request_stream = lambda *_args, **_kwargs: iter(  # type: ignore[method-assign]
        ["我能提供港航知识问答、运营建议和来源追溯。"]
    )
    local = ChatResponse(
        app="小懿",
        mode="expert",
        intent="identity",
        question="你是谁？",
        answer="你好，我是小懿AI。",
        evidence=[],
        confidence="medium",
        next_questions=[],
        grounded=False,
    )

    stream = gateway.enhance_stream(local.question, local)
    first = next(stream)
    second = next(stream)
    answer = f"{first}{second}"

    assert answer.startswith("你好，很高兴认识你。")
    assert "由AI博士温家懿研发" in answer
    assert "独立研发" not in answer
    assert "为你梳理信息、分析风险并给出清晰、可执行的建议" in answer
    assert "我能提供港航知识问答、运营建议和来源追溯" in answer
    assert "领域LoRA" in answer
    assert "人工确认环节" in answer
    assert sleeps == [3.0]


def test_identity_generation_rejects_repetitive_or_truncated_model_text() -> None:
    configuration = replace(
        Settings.from_env(),
        model_provider="openai_compatible",
        model_base_url="http://127.0.0.1:11435/v1",
        model_name="xiaoyi-local-4b",
    )
    gateway = ModelGateway(configuration)
    gateway._request = lambda *_args, **_kwargs: (  # type: ignore[method-assign]
        "我能协助港航运营、船岸协同仿真验证、船岸协同仿真验证、"
        "船岸协同仿真验证、船岸协同"
    )
    local = ChatResponse(
        app="小懿",
        mode="expert",
        intent="identity",
        question="你是谁？",
        answer="你好，我是小懿AI。",
        evidence=[],
        confidence="medium",
        next_questions=[],
        grounded=False,
    )

    result = gateway.enhance(local.question, local)

    assert result.answer.count("船岸协同仿真验证") == 0
    assert "无论你是码头操作员、调度员、船员" in result.answer
    assert "结构化报告和多轮问题拆解" in result.answer


def test_identity_generation_does_not_repeat_locked_name_or_greeting() -> None:
    configuration = replace(
        Settings.from_env(),
        model_provider="openai_compatible",
        model_base_url="http://127.0.0.1:11435/v1",
        model_name="xiaoyi-local-4b",
    )
    gateway = ModelGateway(configuration)
    gateway._request = lambda *_args, **_kwargs: (  # type: ignore[method-assign]
        "你好，我是小懿AI港航行业智能助手。"
    )
    local = ChatResponse(
        app="小懿",
        mode="expert",
        intent="identity",
        question="你是谁？",
        answer="你好，我是小懿AI。",
        evidence=[],
        confidence="medium",
        next_questions=[],
        grounded=False,
    )

    result = gateway.enhance(local.question, local)

    assert result.answer.count("我是小懿") == 1
    assert "我是小懿AI" not in result.answer
    assert "无论你是码头操作员、调度员、船员" in result.answer


def test_identity_generation_does_not_start_a_second_self_introduction() -> None:
    configuration = replace(
        Settings.from_env(),
        model_provider="openai_compatible",
        model_base_url="http://127.0.0.1:11435/v1",
        model_name="xiaoyi-local-4b",
    )
    gateway = ModelGateway(configuration)
    local = ChatResponse(
        app="小懿",
        mode="expert",
        intent="identity",
        question="你是谁？",
        answer="你好，我是小懿AI。",
        evidence=[],
        confidence="medium",
        next_questions=[],
        grounded=False,
    )

    for model_answer in (
        "我是一个港航领域的数字助手，能协助查询船舶动态和港口信息。",
        "我叫小懿，是港航行业的数字助手，能协助查询港口信息和作业流程。",
    ):
        gateway._request = (  # type: ignore[method-assign]
            lambda *_args, _answer=model_answer, **_kwargs: _answer
        )
        result = gateway.enhance(local.question, local)

        assert result.answer.count("我是") == 1
        assert "我叫小懿" not in result.answer
        assert "无论你是码头操作员、调度员、船员" in result.answer


def test_exact_generated_evidence_answer_gets_deterministic_citation() -> None:
    configuration = replace(
        Settings.from_env(),
        model_provider="openai_compatible",
        model_base_url="http://127.0.0.1:11435/v1",
        model_name="xiaoyi-local-4b",
        model_max_retries=0,
    )
    gateway = ModelGateway(configuration)
    answer = "保留原ETA，记录新ETA、来源、更新时间和变更原因。"
    gateway._request = lambda question, response: answer  # type: ignore[method-assign]
    local = ChatResponse(
        app="小懿",
        mode="expert",
        intent="shipping",
        question="ETA变了怎么更新？",
        answer=answer,
        evidence=[
            Evidence(
                id="eta-1",
                source="eta.md",
                title="ETA更新",
                score=1.0,
                snippet=f"直接回答：{answer}",
            )
        ],
        confidence="high",
        next_questions=[],
        grounded=True,
    )

    result = gateway.enhance(local.question, local)

    assert result.answer.startswith(f"证据锁定结论：\n{answer} [E1]")
    assert "模型综合建议（需人工复核）：" in result.answer


def test_generation_context_filters_same_institution_wrong_topic_evidence() -> None:
    configuration = replace(
        Settings.from_env(),
        model_provider="openai_compatible",
        model_base_url="http://127.0.0.1:11435/v1",
        model_name="xiaoyi-local-4b",
    )
    gateway = ModelGateway(configuration)
    local = ChatResponse(
        app="小懿",
        mode="expert",
        intent="cause_analysis",
        question="出口箱缺少VGM怎么办？",
        answer=(
            "根据当前索引，我能确认的重点是：\n\n"
            "- [E1] 缺少VGM时应暂停纳入最终装船计划。\n"
            "- [E2] IMO温室气体战略包含2030年愿景。"
        ),
        evidence=[
            _evidence(
                "缺少VGM时应暂停纳入最终装船计划。",
                title="集装箱VGM操作要求",
            ),
            Evidence(
                id="carbon-2",
                source="imo-carbon.md",
                title="IMO温室气体战略",
                score=90.0,
                snippet="战略包含2030年愿景。",
            ),
        ],
        confidence="medium",
        next_questions=[],
        grounded=True,
    )

    prompt = gateway._messages(local.question, local)[-1]["content"]

    assert "[E1] 缺少VGM时应暂停纳入最终装船计划" in prompt
    assert "缺少VGM时应暂停纳入最终装船计划" in prompt
    assert "温室气体战略" not in prompt
    assert "2030年愿景" not in prompt


def test_grounded_handover_prompt_contains_retrieved_body_not_only_title() -> None:
    configuration = replace(
        Settings.from_env(),
        model_provider="openai_compatible",
        model_base_url="http://127.0.0.1:11435/v1",
        model_name="xiaoyi-local-4b",
    )
    gateway = ModelGateway(configuration)
    local = XiaoyiAI().ask(
        "港口交班要交什么？",
        mode="brief",
        strict_evidence=True,
    )

    prompt = gateway._messages(local.question, local)[-1]["content"]

    assert "登记证据：\n[E1]" in prompt
    assert "交接班哪些事项不能漏" in prompt
    assert "未闭环异常" in prompt
    assert "单证与放行卡点" in prompt
    assert "负责人和下次动作时间" in prompt


def test_sandbox_generation_prompt_contains_runtime_snapshot_body() -> None:
    configuration = replace(
        Settings.from_env(),
        model_provider="openai_compatible",
        model_base_url="http://127.0.0.1:11435/v1",
        model_name="xiaoyi-local-4b",
    )
    gateway = ModelGateway(configuration)
    local = XiaoyiAI().ask(
        "按船舶、设备、堆场、闸口、告警五部分生成当前工作台交班摘要。",
        mode="ops",
        strict_evidence=True,
    )

    prompt = gateway._messages(local.question, local)[-1]["content"]

    assert local.source_quality == "sandbox_runtime"
    assert "港口运营沙箱动态事件流" in prompt
    for section in ("1. 船舶", "2. 设备", "3. 堆场", "4. 闸口", "5. 待跟进"):
        assert section in prompt
        assert prompt.count(section) == 1


def test_identity_generation_rejects_invented_evidence_number() -> None:
    configuration = replace(
        Settings.from_env(),
        model_provider="openai_compatible",
        model_base_url="http://127.0.0.1:11435/v1",
        model_name="xiaoyi-local-4b",
    )
    gateway = ModelGateway(configuration)
    gateway._request = lambda *_args, **_kwargs: (  # type: ignore[method-assign]
        "核验路径：身份档案证据编号为2024-01-15-001。"
    )
    local = ChatResponse(
        app="小懿",
        mode="expert",
        intent="identity",
        question="你是谁？",
        answer="你好，我是小懿AI。",
        evidence=[],
        confidence="medium",
        next_questions=[],
        grounded=False,
    )

    result = gateway.enhance(local.question, local)

    assert "证据编号" not in result.answer
    assert "2024-01-15-001" not in result.answer
    assert "由AI博士温家懿研发" in result.answer
    assert "独立研发" not in result.answer
    assert "SOP生成" in result.answer
