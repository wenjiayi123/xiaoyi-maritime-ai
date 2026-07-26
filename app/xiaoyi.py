from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import date

from app.config import APP_NAME, KNOWLEDGE_CATALOG_PATH
from app.knowledge_policy import (
    QueryEvidencePolicy,
    build_query_policy,
    requires_official_evidence,
    source_is_applicable,
    source_review_status,
)
from app.models import ChatResponse, Evidence, Mode
from app.operator_assistant import (
    clarification_for,
    is_sandbox_runtime_question,
    normalize_operator_question,
    operator_next_questions,
    sandbox_runtime_answer,
)
from app.retrieval import KnowledgeBase, SearchHit, get_shared_knowledge_base


INCIDENT_GROUP_TERMS = {
    "fire": ["火灾", "失火", "着火", "起火", "火情", "冒烟", "浓烟", "烟雾", "爆燃", "消防", "人员疏散"],
    "spill": ["油污泄漏", "漏油", "溢油", "油品泄漏", "水域污染", "围油栏", "吸油毡", "MARPOL"],
    "dangerous_goods": ["危险品", "DG", "IMDG", "UN编号", "MSDS", "危险品泄漏", "异味", "漏液"],
    "injury": ["人员受伤", "有人受伤", "伤人", "工伤", "急救", "摔伤", "夹伤", "触电", "机械伤害"],
    "vehicle": ["车辆事故", "交通事故", "集卡碰撞", "撞车", "车撞", "剐蹭", "侧翻"],
}

INCIDENT_PLAYBOOK_SOURCES = {
    "33_vessel_navigation_incident_playbooks.md",
    "34_terminal_operations_incident_playbooks.md",
    "35_energy_equipment_incident_playbooks.md",
    "36_customs_security_environment_playbooks.md",
    "40_decision_risk_sop_qa.md",
    "44_common_incident_qa.md",
}

GENERIC_SOURCES = {
    "00_knowledge_catalog.md",
    "00_knowledge_map.md",
    "01_port_basics.md",
    "37_port_qa_form_taxonomy.md",
}

SMALLTALK_INTENTS = {"greeting", "identity", "capability", "thanks", "farewell"}
MIN_EVIDENCE_COVERAGE = 0.30
MIN_LOCATOR_EVIDENCE_COVERAGE = 0.05

REALTIME_BOUNDARY_TERMS = {
    "实时数据", "无实时数据", "未接入实时", "未接入", "当前无", "未连接实时", "无法获取当前",
    "无法查询当前", "需要连接", "需连接", "需要接入", "需接入",
    "no real-time data", "no realtime data", "no verified real-time", "not connected", "not connected to live",
    "cannot access current", "requires a connection", "connect to",
}

REALTIME_SYSTEM_TERMS = {
    "TOS", "PCS", "AIS", "VTS", "EMS", "EAM", "生产系统", "港口系统",
    "泊位计划", "船期系统", "闸口系统", "预约系统", "统计系统",
    "设备系统", "车队系统", "能源系统", "计量系统", "集装箱跟踪",
    "live system", "operational system", "container tracking", "schedule system",
}


class XiaoyiAI:
    def __init__(self, kb: KnowledgeBase | None = None) -> None:
        self._uses_shared_kb = kb is None
        self.kb = kb or get_shared_knowledge_base()

    def ask(
        self,
        question: str,
        mode: Mode = "expert",
        top_k: int = 5,
        strict_evidence: bool = True,
        jurisdiction: str | None = None,
        as_of_date: date | None = None,
    ) -> ChatResponse:
        if self._uses_shared_kb:
            self.kb = get_shared_knowledge_base()
        original_question = question
        question = normalize_operator_question(question)
        clarification = clarification_for(question)
        if clarification:
            answer, followups = clarification
            return ChatResponse(
                app=APP_NAME,
                mode=mode,
                intent="operator_clarification",
                question=original_question,
                answer=answer,
                evidence=[],
                confidence="low",
                next_questions=followups,
                strict_evidence=strict_evidence,
                grounded=False,
                coverage=0.0,
                source_quality="not_applicable",
                refusal_reason="business_object_required",
            )
        intent = self._detect_intent(question, mode)
        realtime_question = self._is_realtime_question(question)
        official_required = self._requires_official_evidence(question, intent)
        if (
            is_sandbox_runtime_question(question)
            and not official_required
        ):
            answer = sandbox_runtime_answer(question)
            return ChatResponse(
                app=APP_NAME,
                mode=mode,
                intent="operator_runtime_assist",
                question=original_question,
                answer=answer,
                evidence=[
                    Evidence(
                        id="runtime:XIAOYI-PORT-SANDBOX",
                        source="XIAOYI-PORT-SANDBOX",
                        title="港口运营沙箱动态事件流",
                        score=1.0,
                        snippet="生产形态字段、事件时间、质量码和适配器边界已就绪；当前为动态合成数据。",
                        institution="小懿AI本地运营沙箱",
                        version="port-ops.v1",
                        provenance_type="synthetic_runtime",
                        official=False,
                        verification_status="synthetic_validated",
                        source_quality="sandbox_runtime",
                    )
                ],
                confidence="medium",
                next_questions=operator_next_questions(question),
                strict_evidence=strict_evidence,
                grounded=True,
                coverage=1.0,
                source_quality="sandbox_runtime",
                refusal_reason="sandbox_not_production",
            )
        policy = build_query_policy(
            question,
            official_required=official_required,
            requested_jurisdiction=jurisdiction,
            as_of_date=as_of_date,
        )
        raw_hits = self.kb.search(
            question,
            top_k=max(top_k * 4, 20),
            jurisdictions=policy.jurisdictions or None,
        )
        hits = self._filter_hits(question, intent, raw_hits)
        if not hits and raw_hits:
            hits = raw_hits
        hits = self._rank_evidence_hits(question, hits)
        if realtime_question:
            # A live-state question must never be grounded by a generic definition or
            # an old dashboard snapshot.  Only indexed data-boundary guidance remains
            # eligible until a verified production connector supplies current values.
            hits = [hit for hit in hits if self._is_realtime_boundary_hit(hit)]

        is_smalltalk = intent in SMALLTALK_INTENTS
        refusal_reason: str | None = None
        grounding_hits: list[SearchHit] = []
        display_hits: list[SearchHit] = []
        enforce_evidence_policy = strict_evidence or policy.official_required
        if enforce_evidence_policy and not is_smalltalk:
            qualified_hits = [
                hit
                for hit in hits
                if self._is_sufficient_evidence(question, hit)
                or (
                    policy.locator_facts_allowed
                    and hit.chunk.provenance.official
                    and hit.coverage >= MIN_LOCATOR_EVIDENCE_COVERAGE
                    and hit.score >= 12.0
                )
            ]
            grounding_hits = [
                hit
                for hit in qualified_hits
                if source_is_applicable(hit.chunk.provenance, policy)
            ][:top_k]

            requested_local = set(policy.jurisdictions) - {"GLOBAL"}
            missing_local_source = bool(
                policy.official_required
                and requested_local
                and not any(
                    requested_local.intersection(hit.chunk.provenance.jurisdictions)
                    for hit in grounding_hits
                )
            )
            if missing_local_source:
                grounding_hits = []

            grounded = bool(grounding_hits)
            if grounded:
                display_hits = grounding_hits
                answer = self._compose_indexed_answer(grounding_hits, policy)
            else:
                locator_policy = replace(
                    policy,
                    evidence_requirement="official_summary",
                    full_text_required=False,
                    locator_facts_allowed=True,
                )
                if policy.official_required and not realtime_question:
                    locator_candidates = [
                        hit
                        for hit in hits
                        if hit.score > 0
                        and source_is_applicable(hit.chunk.provenance, locator_policy)
                    ]
                    display_hits = self._unique_source_hits(locator_candidates)[:top_k]
                answer = (
                    self._realtime_data_boundary_answer(question)
                    if realtime_question
                    else self._insufficient_evidence_answer(policy, display_hits)
                )
                refusal_reason = (
                    "live_data_connection_required"
                    if realtime_question
                    else (
                        "official_full_text_required"
                        if policy.full_text_required
                        else (
                            "jurisdiction_source_required"
                            if missing_local_source
                            else (
                                "official_source_required"
                                if policy.official_required
                                else "insufficient_index_evidence"
                            )
                        )
                    )
                )
            if realtime_question:
                # Indexed documents can explain the connector boundary, but they
                # cannot substantiate a current operational value. Until a verified
                # live adapter supplies that value, every live-state query fails
                # closed regardless of textual retrieval quality.
                grounding_hits = []
                display_hits = self._unique_source_hits(hits)[:top_k]
                grounded = False
                answer = self._realtime_data_boundary_answer(question)
                refusal_reason = "live_data_connection_required"
        else:
            display_hits = hits[:top_k]
            grounding_hits = [
                hit
                for hit in display_hits
                if self._is_sufficient_evidence(question, hit)
            ]
            grounded = bool(grounding_hits)
            answer = self._compose_answer(question, mode, intent, display_hits)

        supporting_ids = {hit.chunk.id for hit in grounding_hits}
        evidence = [
            Evidence(
                id=hit.chunk.id,
                source=hit.chunk.source,
                title=hit.chunk.title,
                score=hit.score,
                snippet=hit.snippet,
                source_url=hit.chunk.provenance.source_url,
                institution=hit.chunk.provenance.institution,
                version=hit.chunk.provenance.version,
                checksum_sha256=hit.chunk.document_hash or None,
                chunk_checksum_sha256=hit.chunk.content_hash or None,
                provenance_type=hit.chunk.provenance.provenance_type,
                official=hit.chunk.provenance.official,
                verification_status=hit.chunk.provenance.verification_status,
                source_quality=hit.chunk.provenance.source_quality,
                jurisdictions=list(hit.chunk.provenance.jurisdictions),
                content_scope=hit.chunk.provenance.content_scope,
                legal_force=hit.chunk.provenance.legal_force,
                effective_from=hit.chunk.provenance.effective_from,
                effective_to=hit.chunk.provenance.effective_to,
                last_verified_at=hit.chunk.provenance.last_verified_at,
                review_due_at=hit.chunk.provenance.review_due_at,
                review_status=source_review_status(
                    hit.chunk.provenance,
                    policy.as_of_date,
                ),
                citation_role=(
                    "supporting" if hit.chunk.id in supporting_ids else "locator_only"
                ),
            )
            for hit in display_hits
        ]
        coverage = round(max((hit.coverage for hit in grounding_hits), default=0.0), 4)
        source_quality = (
            self._source_quality(display_hits) if not is_smalltalk else "not_applicable"
        )
        if grounded and source_quality == "official_verified" and coverage >= 0.75:
            confidence = "high"
        elif grounded and coverage >= 0.45:
            confidence = "medium"
        else:
            confidence = "low"
        return ChatResponse(
            app=APP_NAME,
            mode=mode,
            intent=intent,
            question=original_question,
            answer=answer,
            evidence=evidence,
            confidence=confidence,
            next_questions=self._next_questions(intent),
            strict_evidence=strict_evidence,
            grounded=grounded if not is_smalltalk else False,
            coverage=coverage,
            source_quality=source_quality,
            refusal_reason=refusal_reason,
            jurisdictions=list(policy.jurisdictions),
            evidence_requirement=policy.evidence_requirement,
            requires_human_review=policy.requires_human_review,
            policy_notice=self._policy_notice(policy, display_hits),
            as_of_date=policy.as_of_date,
        )

    def _requires_official_evidence(self, question: str, intent: str) -> bool:
        # Ordinary terminology such as VGM, B/L or manifest may be answered from a
        # registered curated glossary.  Claims about rules, mandatory clauses,
        # regulators or conventions still require a verified official source.
        return requires_official_evidence(question, intent)

    def _is_realtime_question(self, question: str) -> bool:
        compact = re.sub(r"[\s，。！？、,.!?'-]", "", question).lower()
        if any(
            marker in compact
            for marker in (
                "官方程序", "程序入口", "法规入口", "官方入口", "目录在哪里",
                "核验入口", "从哪里查", "哪里核验", "如何办理", "办理程序", "申报程序",
            )
        ):
            return False
        explicit_now = any(
            marker in compact
            for marker in (
                "现在", "当前", "今天", "今日", "几点", "什么时候",
                "还要多久", "排队多久", "到哪了", "在哪里", "在线吗",
                "rightnow", "currently", "today", "wherenow", "whereismy",
                "whenwill", "isitonlinenow",
            )
        )
        live_object = any(
            marker in compact
            for marker in (
                "港口", "船", "船舶", "靠泊", "eta", "etb", "etd", "箱号", "箱子",
                "集装箱", "闸口", "吞吐量", "agv", "设备", "岸桥", "能耗",
                "container", "vessel", "berth", "throughput", "queue", "crane",
            )
        )
        return explicit_now and live_object

    def _is_realtime_boundary_hit(self, hit: SearchHit) -> bool:
        haystack = f"{hit.chunk.title}\n{hit.chunk.text}".casefold()
        has_boundary = any(term.casefold() in haystack for term in REALTIME_BOUNDARY_TERMS)
        has_system = any(term.casefold() in haystack for term in REALTIME_SYSTEM_TERMS)
        return has_boundary and has_system

    def _rank_evidence_hits(self, question: str, hits: list[SearchHit]) -> list[SearchHit]:
        compact_question = re.sub(r"[\s，。！？、,.!?]", "", question).lower()
        acronym_terms = {
            term.lower()
            for term in re.findall(r"[A-Za-z][A-Za-z0-9_/-]{1,}", question)
        }

        def rank(hit: SearchHit) -> tuple[float, float, float]:
            compact_title = re.sub(r"[\s，。！？、,.!?]", "", hit.chunk.title).lower()
            exact_bonus = 300.0 if (
                compact_title
                and (compact_title in compact_question or compact_question in compact_title)
            ) else 0.0
            acronym_bonus = 200.0 * sum(
                1 for term in acronym_terms if term in compact_title
            )
            return (
                exact_bonus + acronym_bonus + hit.coverage * 100.0 + hit.score,
                hit.coverage,
                hit.score,
            )

        return sorted(hits, key=rank, reverse=True)

    def _is_sufficient_evidence(self, question: str, hit: SearchHit) -> bool:
        chunk = hit.chunk
        provenance = chunk.provenance
        auditable = (
            len(chunk.content_hash) == 64
            and len(chunk.document_hash) == 64
            and provenance.provenance_type != "unregistered"
            and provenance.verification_status != "unregistered"
        )
        if not auditable:
            return False

        compact_question = re.sub(r"[\s，。！？、,.!?]", "", question).lower()
        compact_title = re.sub(r"[\s，。！？、,.!?]", "", chunk.title).lower()
        exact_title_match = bool(
            compact_title
            and (compact_title in compact_question or compact_question in compact_title)
        )
        acronym_terms = {
            term.lower()
            for term in re.findall(r"[A-Za-z][A-Za-z0-9_/-]{1,}", question)
        }
        acronym_title_match = any(term in compact_title for term in acronym_terms)
        return (
            (hit.coverage >= MIN_EVIDENCE_COVERAGE and hit.score > 0)
            or exact_title_match
            or (acronym_title_match and hit.coverage >= 0.12 and hit.score >= 6.0)
        )

    def _source_quality(self, hits: list[SearchHit]) -> str:
        qualities = {
            hit.chunk.provenance.source_quality or "unverified"
            for hit in hits
        }
        if not qualities:
            return "unverified"
        if len(qualities) == 1:
            return next(iter(qualities))
        return "mixed"

    @staticmethod
    def _unique_source_hits(hits: list[SearchHit]) -> list[SearchHit]:
        unique: list[SearchHit] = []
        seen: set[str] = set()
        for hit in hits:
            if hit.chunk.source in seen:
                continue
            seen.add(hit.chunk.source)
            unique.append(hit)
        return unique

    def _compose_indexed_answer(
        self,
        hits: list[SearchHit],
        policy: QueryEvidencePolicy,
    ) -> str:
        for hit in hits:
            for line in hit.chunk.text.splitlines():
                clean = line.strip().lstrip("-").strip()
                if not clean.startswith("直接回答："):
                    continue
                direct_answer = clean.removeprefix("直接回答：").strip()
                if not direct_answer:
                    continue
                status = (
                    "来源状态：该回答来自已登记的项目内部整理资料，非官方原文；"
                    "涉及生产、安全或合规决策时，必须复核有效的监管文件和现场制度。"
                    if not hit.chunk.provenance.official
                    else (
                        "来源状态：该回答来自已登记的官方发布来源资料；"
                        f"本地内容范围为 {hit.chunk.provenance.content_scope}，"
                        "请通过原始链接核对正式文本、版本和有效期。"
                    )
                )
                return (
                    f"{direct_answer}\n\n"
                    f"我核对的索引依据是《{hit.chunk.title}》（仅摘录当前检索索引）。\n\n"
                    f"{status}\n\n"
                    "当前证据没有覆盖的专业结论，我先不扩写；如果你补充具体港口、对象或日期，我可以继续缩小范围。"
                )

        extracts: list[str] = []
        seen: set[str] = set()
        for evidence_index, hit in enumerate(hits, start=1):
            selected = 0
            for line in hit.chunk.text.splitlines():
                clean = line.strip().lstrip("-").strip()
                if not clean or clean == hit.chunk.title or clean.startswith("#"):
                    continue
                if clean.startswith("关键词") or clean in {"处置步骤：", "回答要点："}:
                    continue
                if len(clean) < 8 or clean in seen:
                    continue
                seen.add(clean)
                extracts.append(f"[E{evidence_index}] {clean}")
                selected += 1
                if selected >= 4 or len(extracts) >= 8:
                    break
            if len(extracts) >= 8:
                break

        if not extracts:
            return self._insufficient_evidence_answer(policy, hits)

        official_count = sum(hit.chunk.provenance.official for hit in hits)
        if official_count == len(hits):
            status = "来源状态：命中的是已登记的官方发布来源事实摘要；请通过原始链接核对正式文本、版本和有效期。"
        elif official_count:
            status = (
                f"来源状态：本次同时命中 {official_count} 条官方发布来源资料和 {len(hits) - official_count} 条项目内部整理资料；"
                "官方摘要或目录只用于其登记范围，具体操作仍须复核正式文本、强制标准和现场制度。"
            )
        else:
            status = (
                "来源状态：当前命中资料在来源清单中登记为项目内部整理资料，"
                "非官方原文；涉及生产、安全或合规决策时，必须复核有效的监管文件和现场制度。"
            )
        return (
            "根据当前索引，我能确认的重点是：\n\n"
            + "\n".join(f"- {item}" for item in extracts)
            + f"\n\n{status}\n\n"
            "上述片段没有覆盖的专业结论，我先不补写；你可以继续指定港口、业务对象或适用日期。"
        )

    def _insufficient_evidence_answer(
        self,
        policy: QueryEvidencePolicy,
        locator_hits: list[SearchHit] | None = None,
    ) -> str:
        if policy.full_text_required:
            message = (
                "当前只找到官方发布页摘要或目录定位，未索引可合法使用且适用于本问题的"
                "官方全文/授权摘录，因此不能回答具体条款、罚则、限值、豁免或法律责任。"
            )
        elif policy.official_required and policy.explicit_jurisdiction:
            message = (
                "当前索引没有找到同时匹配目标辖区、有效日期和问题主题的官方证据，"
                "不能把国际框架或其他港口规则直接外推为当地要求。"
            )
        elif policy.official_required:
            message = (
                "当前索引没有找到足够匹配且仍在复核期内的官方证据，"
                "无法在严格证据模式下给出专业结论。"
            )
        else:
            message = "当前索引未找到足够匹配且可审计的证据，无法在严格证据模式下回答。"

        locator_notice = (
            "\n\n下方证据仅用于定位官方页面，citation_role=locator_only，不构成答案依据。"
            if locator_hits
            else ""
        )
        return (
            f"{message}{locator_notice}\n\n"
            "请补充具体业务对象、辖区、适用日期或法规/标准名称，"
            "或将经授权、可核验的正式资料登记并通过复核后再回答。"
        )

    def _policy_notice(
        self,
        policy: QueryEvidencePolicy,
        hits: list[SearchHit],
    ) -> str:
        scopes = sorted({hit.chunk.provenance.content_scope for hit in hits})
        scope_notice = (
            f"本地命中内容范围：{', '.join(scopes)}。"
            if scopes
            else "本地没有满足条件的证据。"
        )
        review_warnings = sum(
            source_review_status(hit.chunk.provenance, policy.as_of_date)
            in {"review_due", "review_date_missing", "review_date_invalid"}
            for hit in hits
        )
        review_notice = (
            f"其中 {review_warnings} 条来源需要补充或更新复核日期。"
            if review_warnings
            else "命中来源未发现已到复核期的记录。"
        )
        return (
            f"适用日期：{policy.as_of_date.isoformat()}。"
            f"{policy.jurisdiction_notice} {scope_notice}{review_notice}"
        )

    def _realtime_data_boundary_answer(self, question: str) -> str:
        compact = re.sub(r"\s+", "", question).lower()
        english_question = bool(re.search(r"[A-Za-z]{3,}", question)) and not bool(
            re.search(r"[\u4e00-\u9fff]", question)
        )
        if english_question:
            if "container" in compact:
                target_en = "the TOS / PCS container-tracking interface and a container number"
            elif any(term in compact for term in ("vessel", "berth", "eta", "etb", "etd")):
                target_en = "the TOS berth plan, AIS / VTS, or the vessel schedule system"
            elif any(term in compact for term in ("gate", "queue")):
                target_en = "the gate, appointment, or TOS production system"
            elif any(term in compact for term in ("energy", "crane", "power")):
                target_en = "the EMS or the site metering system"
            elif any(term in compact for term in ("agv", "equipment", "online")):
                target_en = "TOS, EAM, or the equipment fleet system"
            elif "throughput" in compact:
                target_en = "the TOS production or statistics system"
            else:
                target_en = "a verified TOS / PCS or other live port operational system"
            return (
                "No verified real-time production data is connected to the current knowledge-chat session, "
                "so I cannot confirm the current status or value.\n\n"
                f"Answering this requires a connection to {target_en}, including the latest timestamp and "
                "the relevant business-object identifier. Until that interface returns verified data, "
                "Xiaoyi will not present dashboard demo values as live results."
            )
        if any(term in compact for term in ("箱号", "箱子", "集装箱", "container")):
            target = "TOS / PCS 的集装箱跟踪接口，并提供箱号"
        elif any(term in compact for term in ("靠泊", "eta", "etb", "船", "vessel", "berth")):
            target = "TOS 泊位计划、AIS / VTS 或船期系统"
        elif any(term in compact for term in ("闸口", "排队", "queue", "gate")):
            target = "闸口系统、预约系统或 TOS 生产系统"
        elif any(term in compact for term in ("能耗", "energy", "电耗", "岸桥")):
            target = "EMS 能源系统或现场计量系统"
        elif any(term in compact for term in ("agv", "设备", "online")):
            target = "TOS、EAM 设备系统或车队系统"
        elif any(term in compact for term in ("吞吐量", "throughput")):
            target = "TOS 生产系统或统计系统"
        else:
            target = "TOS / PCS 等港口生产系统"
        return (
            "当前知识问答没有已验证的实时生产数据，因此不能确认当前状态或数值。\n\n"
            f"要回答这个问题，需要连接{target}，读取最新时间戳和业务对象标识。"
            "在真实接口返回前，小懿不会把演示看板数字当成实时结果。"
        )

    def _detect_intent(self, question: str, mode: Mode) -> str:
        text = question.lower()
        compact = re.sub(r"[\s，。！？、,.!?]", "", question.lower())
        if any(word in compact for word in ["你是谁", "你叫什", "叫什么", "名字", "xiaoyi是谁", "小懿是谁", "谁开发", "谁创建", "研发者", "作者是谁", "温家懿"]):
            return "identity"
        if any(word in compact for word in ["你能做什么", "你会什么", "能干嘛", "能做啥", "有什么用", "功能"]):
            return "capability"
        if any(word in compact for word in ["谢谢", "感谢", "辛苦了", "thanks", "thankyou"]):
            return "thanks"
        if any(word in compact for word in ["再见", "拜拜", "bye", "goodbye"]):
            return "farewell"
        if compact in {"你好", "您好", "hello", "hi", "嗨"} or compact.startswith(("你好", "您好", "hello", "hi", "嗨")):
            return "greeting"
        if self._incident_groups(question):
            return "sop"
        if any(word in compact for word in ["港航圈知识体系", "港航知识体系", "知识体系包括", "知识体系大类", "知识目录", "知识全景"]):
            return "knowledge_catalog"
        if any(word in compact for word in ["问答形式", "问法类型", "问题形式", "问法有哪些"]):
            return "qa_forms"
        if "模板" in question:
            return "template"
        if any(word in question for word in ["如何计算", "怎么计算", "计算", "公式", "口径"]):
            return "metric_calculation"
        if any(word in question for word in ["为什么", "原因", "根因", "怎么导致"]):
            return "cause_analysis"
        if any(word in question for word in ["有什么区别", "区别", "对比", "分别是什么"]):
            return "comparison"
        if any(word in question for word in ["数据源", "证据", "审计记录", "审计证据"]):
            return "evidence_data"
        if any(word in question for word in ["接口", "对接", "交互", "同步"]):
            return "system_interface"
        if any(word in question for word in ["是否应该", "要不要", "能不能", "优先", "先处理"]):
            return "decision_priority"
        process_terms = ["流程是什么", "流程有哪些", "流程", "步骤是什么", "作业步骤"]
        emergency_terms = ["启动", "应急", "处置", "异常", "告警", "故障", "预警", "SOP"]
        if any(word in question for word in process_terms) and not any(word in question for word in emergency_terms):
            return "process_flow"
        if any(word in question for word in ["是什么", "什么是"]):
            return "definition"
        if any(word in question for word in ["费用争议", "费用", "客户说明", "客户沟通", "向客户", "运行提示", "SLA"]):
            return "commercial_communication"
        handling_terms = [
            "SOP",
            "步骤",
            "怎么处理",
            "如何处理",
            "该如何处理",
            "怎么办",
            "如何应对",
            "处理办法",
            "处置",
            "处置建议",
            "应急",
            "排查",
            "恢复",
            "故障处理",
            "异常处理",
        ]
        if mode == "sop" or any(word in question for word in handling_terms):
            return "sop"
        if any(word in question for word in ["告警", "异常", "风险", "超标", "故障", "降级"]):
            return "alert_explain"
        if any(word in question for word in ["提单", "舱单", "D/O", "B/L", "Manifest", "报关", "通关", "清关", "查验", "放行", "VGM", "单证"]):
            return "customs_docs"
        if any(word in question for word in ["海铁联运", "多式联运", "驳船", "内陆港", "无水港", "腹地", "集疏运", "拖车"]):
            return "intermodal_logistics"
        if any(word in question for word in ["MTBF", "MTTR", "点检", "维护", "保养", "备件", "预测性维护", "预防性维护"]):
            return "maintenance"
        if any(word in question for word in ["介绍", "架构", "能力", "定位", "系统价值", "核心能力"]):
            return "system_intro"
        if any(word in question for word in ["岸电", "能耗", "碳", "冷站", "THDi", "电"]):
            return "energy_carbon"
        if any(word in question for word in ["TOS", "EDI", "堆场", "闸口", "泊位", "调度"]):
            return "terminal_ops"
        if any(word in question for word in ["船", "航线", "班轮", "货代", "船代"]):
            return "shipping"
        if any(word in question for word in ["法规", "合规", "海关", "海事", "审计"]):
            return "compliance"
        if "expert" in text:
            return "system_intro"
        return "port_knowledge"

    def _compose_answer(self, question: str, mode: Mode, intent: str, hits: list[SearchHit]) -> str:
        if intent in {"greeting", "identity", "capability", "thanks", "farewell"}:
            return self._smalltalk_answer(intent, hits)

        if not hits:
            return (
                "一句话结论：这个问题超出了当前本地知识库的直接命中范围，可以先按港口业务、系统模块、风险边界三个维度拆解。\n\n"
                "专业说明：小懿以港航知识库、检索增强和业务规则为基础，适合回答港口作业、航运基础、TOS、岸电、碳排和安全应急等核心问题。\n\n"
                "One-line conclusion: This question is not directly covered by the current local knowledge base, so it should be broken down by port business context, system modules, and risk boundaries.\n\n"
                "Professional note: Xiaoyi is built on a port and shipping knowledge base, retrieval enhancement, and business rules. It is suitable for port operations, shipping basics, TOS, shore power, carbon management, and safety response questions."
            )

        key_points = self._collect_key_points(hits)
        source_titles = "、".join(dict.fromkeys(hit.chunk.title for hit in hits[:4]))

        if intent == "knowledge_catalog":
            return self._knowledge_catalog_answer(source_titles)
        if intent == "qa_forms":
            return self._qa_forms_answer(source_titles)
        if mode == "brief":
            return self._brief_answer(question, intent, key_points, source_titles)
        if mode == "sop" or intent in {"sop", "alert_explain"}:
            return self._sop_answer(question, intent, key_points, source_titles, hits)
        if mode == "ops":
            return self._ops_answer(question, intent, key_points, source_titles)
        return self._expert_answer(question, intent, key_points, source_titles)

    def _smalltalk_answer(self, intent: str, hits: list[SearchHit]) -> str:
        document_count = len({chunk.source for chunk in self.kb.chunks})
        chunk_count = len(self.kb.chunks)
        official_count = len({
            chunk.source for chunk in self.kb.chunks
            if chunk.provenance.official and chunk.provenance.source_quality == "official_verified"
        })
        identity_profile = (
            "你好，我是小懿AI港航行业智能助手。\n\n"
            "我由港航AI交叉方向博士温家懿独立完成产品设计、港航知识体系、RAG检索、后端服务、交互界面与安全边界的全流程研发。"
            f"当前正式索引包含 {document_count} 份港航专业文档、{chunk_count} 个可检索知识片段，其中 {official_count} 份为已登记并核验发布机构的官方来源资料；"
            "这些官方资料包含发布页摘要、目录定位与发布方指南，不自动等同于法规或标准全文；"
            "每条专业证据均保留来源、版本、机构和内容校验哈希。\n\n"
            "我聚焦港口调度、船舶运营、航运SOP规范、能碳优化、海事合规五大场景，可提供严格证据知识问答、标准流程生成、设备告警处置建议、航运数据辅助决策、结构化报告，以及学术研究中的术语梳理、资料检索线索和论文框架辅助。\n\n"
            "除回答问题外，我还能把一句自然语言指令拆解为可视化、可暂停、可审计的工作台操作链，自动完成页面跳转、数据读取、知识检索、来源核验、任务推进、报告生成和结果回写。项目已经预留 TOS、PCS、EMS、EAM、VTS、AIS、气象海洋与国际贸易单一窗口等真实港口接口契约，也为港航数字孪生和强化学习训练实验室保留协同入口。\n\n"
            "我的原则是专业结论有索引依据，实时状态有可追溯数据源依据，生产写操作有当前授权依据。未接入真实系统时，我会明确标注运营沙箱动态合成数据；涉及安全、调度、设备控制和对外申报时，我只完成辅助分析与写操作预检，不绕过人工确认和生产系统权限。"
        )
        if intent == "identity":
            return identity_profile
        if intent == "capability":
            return (
                f"{identity_profile}\n\n"
                "您可以直接这样指挥我：\n"
                "1. “帮我在知识库中搜索岸电安全操作规程。”——我会完成检索、来源核验、证据问答并把规程回写对话区。\n"
                "2. “分析未来7日港口能耗并生成报告。”——我会切换数据范围、读取指标、推进分析任务、校验报告并交付结果。\n"
                "3. “检查泊位冲突并给出调度建议。”——我会读取约束、创建模拟优化任务、逐步评估并保留人工确认边界。\n"
                "4. “查看真实港口接口装配状态。”——我会检查连接器、字段映射、健康状态与写操作门禁。"
            )
        if intent == "thanks":
            return (
                "不客气。我可以继续帮你查询港航知识、解释运行异常，或者把某个港口业务问题整理成 SOP。\n\n"
                "You are welcome. I can continue helping you search port and shipping knowledge, explain operational exceptions, or turn a port business issue into an SOP."
            )
        if intent == "farewell":
            return (
                "再见。后续如果需要继续查询港航知识、生成 SOP 或分析港口运行问题，我可以继续协助。\n\n"
                "Goodbye. If you need to search port and shipping knowledge, generate SOPs, or analyze port operations later, I can continue to help."
            )
        return identity_profile

    def _filter_hits(self, question: str, intent: str, hits: list[SearchHit]) -> list[SearchHit]:
        smalltalk_intents = {"greeting", "identity", "capability", "thanks", "farewell"}
        filtered: list[SearchHit] = []
        question_terms = set(re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]{2,}", question))
        incident_groups = self._incident_groups(question)

        if intent in {"sop", "alert_explain"} and incident_groups:
            incident_hits = self._filter_incident_hits(question, hits, incident_groups)
            if incident_hits:
                return incident_hits

        for hit in hits:
            source = hit.chunk.source
            title = hit.chunk.title

            if intent not in smalltalk_intents and source == "11_common_chat.md":
                continue

            if intent == "knowledge_catalog" and source not in {
                "00_knowledge_catalog.md",
                "00_knowledge_map.md",
                "37_port_qa_form_taxonomy.md",
            }:
                continue
            if intent == "knowledge_catalog" and title not in {
                "港航圈知识体系大类",
                "知识库范围",
                "15. 问答形式与回答结构",
                "港航问答形式全景",
            }:
                continue

            if intent == "qa_forms" and source not in {
                "37_port_qa_form_taxonomy.md",
                "00_knowledge_catalog.md",
                "00_knowledge_map.md",
            }:
                continue

            if intent == "definition" and any(word in title for word in ["原因", "异常", "故障", "如何处理", "该如何处理", "流程", "SOP", "模板"]):
                continue

            if intent in {"process_flow", "metric_calculation", "cause_analysis", "comparison", "decision_priority", "system_interface", "template", "commercial_communication"}:
                if source == "11_common_chat.md":
                    continue

            filtered.append(hit)

        if filtered:
            return filtered

        if intent in smalltalk_intents:
            return hits

        # Last resort: keep hits that share at least one meaningful term with the question.
        for hit in hits:
            if hit.chunk.source == "11_common_chat.md":
                continue
            haystack = f"{hit.chunk.title} {hit.chunk.text}"
            if any(term in haystack for term in question_terms):
                filtered.append(hit)
        return filtered

    def _incident_groups(self, question: str) -> set[str]:
        compact = re.sub(r"[\s，。！？、,.!?]", "", question.lower())
        groups: set[str] = set()
        for group, terms in INCIDENT_GROUP_TERMS.items():
            if any(term.lower() in compact for term in terms):
                groups.add(group)
        if "危险品" in question and groups.intersection({"fire", "spill"}):
            groups.add("dangerous_goods")
        return groups

    def _filter_incident_hits(self, question: str, hits: list[SearchHit], groups: set[str]) -> list[SearchHit]:
        terms = [term for group in groups for term in INCIDENT_GROUP_TERMS[group]]
        question_compact = re.sub(r"[\s，。！？、,.!?]", "", question.lower())
        ranked: list[SearchHit] = []

        for hit in hits:
            source = hit.chunk.source
            title = hit.chunk.title
            title_compact = re.sub(r"[\s，。！？、,.!?]", "", title.lower())
            exact_title_match = bool(title_compact and (title_compact in question_compact or question_compact in title_compact))
            haystack = f"{title}\n{hit.chunk.text}"
            haystack_lower = haystack.lower()
            matched_terms = [term for term in terms if term.lower() in haystack_lower]
            source_is_playbook = source in INCIDENT_PLAYBOOK_SOURCES

            if not matched_terms and not exact_title_match:
                continue
            if source in GENERIC_SOURCES and not matched_terms:
                continue

            score = hit.score
            score += len(matched_terms) * 8.0
            if source == "44_common_incident_qa.md":
                score += 60.0
            elif source_is_playbook:
                score += 32.0
            if exact_title_match:
                score += 90.0
            if "该如何处理" in title or "怎么办" in title or "处置步骤" in hit.chunk.text:
                score += 14.0
            if source in GENERIC_SOURCES:
                score -= 35.0
            if any(word in title for word in ["定义", "流程是什么", "知识体系", "知识库范围"]) and not source_is_playbook:
                score -= 30.0

            if score > 0:
                ranked.append(
                    SearchHit(
                        chunk=hit.chunk,
                        score=round(score, 2),
                        snippet=hit.snippet,
                        matched_terms=hit.matched_terms,
                        coverage=hit.coverage,
                    )
                )

        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked

    def _knowledge_catalog_answer(self, titles: str) -> str:
        try:
            catalog = json.loads(KNOWLEDGE_CATALOG_PATH.read_text(encoding="utf-8"))
            categories = catalog.get("categories", [])
            summary = catalog.get("coverage_summary", {}).get("topics", {})
            lines = [
                f"{index}. {item['name']}（{item['coverage_status']}）"
                for index, item in enumerate(categories, start=1)
            ]
            return (
                f"当前正式港航知识目录按 {len(categories)} 个类别、"
                f"{catalog.get('topic_count', 0)} 个主题维护：\n\n"
                + "\n".join(lines)
                + "\n\n"
                f"主题覆盖：已索引 {summary.get('indexed', 0)} 个、部分覆盖 {summary.get('partial', 0)} 个、"
                f"待建设 {summary.get('planned', 0)} 个。partial/indexed 只表示本地存在资料，"
                "不代表已经收齐全球全部法规、标准或港口制度。\n\n"
                f"知识依据：{titles}。"
            )
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, KeyError):
            return (
                "港航知识目录当前无法通过完整性读取；请先检查机器目录文件，再回答覆盖范围。\n\n"
                f"当前检索依据：{titles}。"
            )

    def _qa_forms_answer(self, titles: str) -> str:
        return (
            "港航问答可以按 26 类组织：\n\n"
            "1. 概念定义类：回答 TOS、VGM、PCS、ETA 等是什么。\n"
            "2. 术语缩写类：解释 TEU、FEU、D/O、B/L、AIS、VTS 等缩写。\n"
            "3. 流程说明类：回答靠泊、进闸、装船、查验、离港等流程。\n"
            "4. 角色职责类：区分港口、船公司、船代、货代、海关、海事等职责。\n"
            "5. 对比辨析类：比较 TOS 与 PCS、堆存费与滞箱费、海铁与公路集疏运。\n"
            "6. 指标解释类：解释泊位利用率、船时效率、桥吊效率、翻箱率等含义。\n"
            "7. 指标计算类：说明单位 TEU 能耗、碳排、船时效率等计算口径。\n"
            "8. 原因分析类：分析堆场拥堵、闸口排队、TOS 响应慢等原因。\n"
            "9. 影响评估类：评估船期延误、设备故障、封航、查验滞留的影响。\n"
            "10. 风险判断类：判断告警等级、停机必要性、隔离条件和升级阈值。\n"
            "11. 异常处置类：回答某某情况该如何处理。\n"
            "12. SOP 生成类：生成台风、岸电、TOS 降级、危险品等 SOP。\n"
            "13. 决策建议类：判断是否调整泊位、启用备用闸口或切换人工派单。\n"
            "14. 优先级排序类：处理多船晚到、多设备告警、多堆场堵点的排序。\n"
            "15. 检查清单类：生成岸电接入、危险品进港、交接班等清单。\n"
            "16. 数据源与证据类：列出判断所需数据源和审计证据。\n"
            "17. 系统接口类：说明 TOS、EDI、OCR、PCS、单一窗口之间如何交互。\n"
            "18. 数据质量类：处理箱号不一致、OCR 误识别、EDI 缺失和主数据异常。\n"
            "19. 合规审计类：判断海关、海事、MARPOL、ISPS、危险品相关要求。\n"
            "20. 商务费用类：解释 THC、堆存费、滞箱费、SLA 和费用争议。\n"
            "21. 客户沟通类：生成船期延误、查验滞留、闸口拥堵等客户说明。\n"
            "22. 汇报摘要类：把运行状态或异常事件整理成汇报。\n"
            "23. 复盘改进类：沉淀根因、效果、改进项和责任闭环。\n"
            "24. 预测预警类：提前识别堆场、冷藏箱、船期、设备等风险。\n"
            "25. 培训说明类：面向新员工或非技术人员解释港航概念。\n"
            "26. 模板生成类：生成交接班、异常处置、客户通知等记录模板。\n\n"
            f"知识依据：{titles}。\n\n"
            "Port and shipping Q&A can be organized into 26 forms:\n\n"
            "1. Concept definition: explain what TOS, VGM, PCS, ETA, and similar terms mean.\n"
            "2. Abbreviation explanation: explain TEU, FEU, D/O, B/L, AIS, VTS, and related terms.\n"
            "3. Process explanation: describe berthing, gate-in, loading, inspection, and departure flows.\n"
            "4. Role responsibility: distinguish responsibilities among port operators, carriers, agents, forwarders, customs, and maritime authorities.\n"
            "5. Comparison: compare TOS and PCS, storage fee and demurrage, rail-sea intermodal and road drayage.\n"
            "6. KPI interpretation: explain berth utilization, vessel productivity, crane productivity, and rehandling rate.\n"
            "7. KPI calculation: describe calculation scopes for energy per TEU, emissions, and vessel productivity.\n"
            "8. Cause analysis: analyze yard congestion, gate queues, and slow TOS response.\n"
            "9. Impact assessment: assess schedule delay, equipment failure, navigation restriction, and customs hold impact.\n"
            "10. Risk judgement: judge alert level, shutdown necessity, isolation condition, and escalation threshold.\n"
            "11. Exception handling: answer how to handle a specific situation.\n"
            "12. SOP generation: generate SOPs for typhoon response, shore power, TOS degradation, and dangerous goods.\n"
            "13. Decision advice: judge whether to adjust berth, open backup gates, or switch to manual dispatch.\n"
            "14. Priority ranking: rank multiple delayed vessels, equipment alerts, or yard bottlenecks.\n"
            "15. Checklist: generate checklists for shore power connection, dangerous goods entry, and shift handover.\n"
            "16. Data and evidence: list required data sources and audit evidence.\n"
            "17. System interface: explain how TOS, EDI, OCR, PCS, and single-window systems interact.\n"
            "18. Data quality: handle container-number mismatch, OCR error, missing EDI, and master-data inconsistency.\n"
            "19. Compliance audit: explain customs, maritime, MARPOL, ISPS, and dangerous-goods requirements.\n"
            "20. Commercial fee: explain THC, storage fee, container detention, SLA, and fee disputes.\n"
            "21. Customer communication: draft explanations for schedule delay, customs hold, and gate congestion.\n"
            "22. Briefing summary: turn operational status or incidents into concise reports.\n"
            "23. Review and improvement: capture root causes, response effectiveness, improvement items, and ownership.\n"
            "24. Forecast and warning: identify risks in yard, reefer, schedule, and equipment operations.\n"
            "25. Training explanation: explain port and shipping concepts to new staff or non-technical users.\n"
            "26. Template generation: create handover, exception-handling, and customer-notice templates."
        )

    def _collect_key_points(self, hits: list[SearchHit]) -> list[str]:
        points: list[str] = []
        seen: set[str] = set()
        for hit in hits:
            for line in hit.chunk.text.splitlines():
                clean = line.strip().lstrip("-").strip()
                if clean == hit.chunk.title:
                    continue
                if not clean or clean.startswith("#"):
                    continue
                if clean.startswith("关键词"):
                    continue
                if clean.startswith(("问答形式", "典型问法", "回答要点")):
                    continue
                if len(clean) < 8:
                    continue
                if clean in seen:
                    continue
                seen.add(clean)
                points.append(clean)
                if len(points) >= 8:
                    return points
        return points

    def _expert_answer(self, question: str, intent: str, points: list[str], titles: str) -> str:
        bullets = self._format_bullets(points[:5])
        conclusion = points[0] if points else "该问题需要结合港航知识库和现场数据判断。"
        return (
            f"结论：{conclusion}\n\n"
            f"依据：{titles}。\n\n"
            f"关键知识点：\n{bullets}\n\n"
            "现场应用：落地时需要结合具体对象、时间窗口、系统数据、现场记录和人工确认要求。"
        )

    def _ops_answer(self, question: str, intent: str, points: list[str], titles: str) -> str:
        bullets = self._format_bullets(points[:5])
        return (
            "结论：需要结合港口现场状态、系统数据、设备状态和人工确认来判断。\n\n"
            f"依据知识：{titles}。\n\n"
            f"主要判断点：\n{bullets}\n\n"
            "建议动作：先确认现场对象和时间窗口，再核对系统数据与设备状态；涉及安全、合规、计费或生产影响时进入人工确认闭环。"
        )

    def _sop_answer(self, question: str, intent: str, points: list[str], titles: str, hits: list[SearchHit]) -> str:
        bullets = self._format_bullets(points[:4])
        steps = self._extract_numbered_steps(hits)
        groups = self._incident_groups(question)
        conclusion = self._sop_conclusion(groups, intent)
        step_block = self._format_numbered(steps) if steps else (
            "1. 确认对象：明确船舶、泊位、设备、系统模块和时间窗口。\n"
            "2. 核对数据：对比 TOS、设备监控、能源计量、告警日志和人工记录。\n"
            "3. 分级处置：低风险先观察，中风险进入复核，高风险先冻结高影响动作并通知负责人。\n"
            "4. 人工确认：涉及安全、合规、计费、客户承诺、系统降级或生产影响时必须人工确认。\n"
            "5. 审计沉淀：记录原因、动作、负责人、结果和可复用 playbook。"
        )
        return (
            f"处理结论：{conclusion}\n\n"
            f"知识依据：{titles}。\n\n"
            f"现场检查点：\n{bullets}\n\n"
            f"处置步骤：\n{step_block}\n\n"
            "人工确认与记录：涉及人员安全、消防、危险品、能源切断、监管通报、客户承诺或复工恢复时，必须由值班长、专业负责人或合规人员确认，并保留时间、地点、对象、动作、负责人和证据链。"
        )

    def _brief_answer(self, question: str, intent: str, points: list[str], titles: str) -> str:
        one_line = re.sub(r"\s+", " ", points[0]) if points else "当前问题需要结合港航知识库进一步判断。"
        return (
            f"简报结论：{one_line}\n\n"
            f"问题类型：{intent}\n"
            f"知识来源：{titles}\n"
            "建议：用于汇报时突出业务背景、关键指标、处置动作和人工确认边界。"
        )

    def _format_bullets(self, points: list[str]) -> str:
        return "\n".join(f"- {point}" for point in points) if points else "- 当前知识库没有足够细节，需要补充现场数据。"

    def _extract_numbered_steps(self, hits: list[SearchHit], limit: int = 6) -> list[str]:
        steps: list[str] = []
        seen: set[str] = set()
        for hit in hits[:3]:
            for line in hit.chunk.text.splitlines():
                match = re.match(r"^\s*\d+[.．]\s*(.+?)\s*$", line)
                if not match:
                    continue
                step = match.group(1)
                if len(step) < 6 or step in seen:
                    continue
                seen.add(step)
                steps.append(step)
                if len(steps) >= limit:
                    return steps
        return steps

    def _format_numbered(self, steps: list[str]) -> str:
        return "\n".join(f"{index}. {step}" for index, step in enumerate(steps, start=1))

    def _sop_conclusion(self, groups: set[str], intent: str) -> str:
        if "dangerous_goods" in groups and "fire" in groups:
            return "这属于危险品相关火情或冒烟事件，应先隔离人员和风险区域，再按危险品消防应急流程处置。"
        if "fire" in groups:
            return "这属于港区火灾或疑似火情，应立即报警、疏散人员、切断相关能源并启动消防应急预案。"
        if "spill" in groups:
            return "这属于油污或污染泄漏事件，应先切断泄漏源、围控污染扩散并通知环保和海事相关责任人。"
        if "injury" in groups:
            return "这属于港区人员伤害事件，应优先救人、停止相关作业并防止二次伤害。"
        if "vehicle" in groups:
            return "这属于港区车辆或交通事故，应先确认人员安全、封控道路并保留现场证据。"
        return f"该问题属于 {intent}，建议按“确认、隔离、处置、复盘”四步执行。"

    def _english_sop_block(self, groups: set[str]) -> dict[str, str]:
        if "dangerous_goods" in groups and "fire" in groups:
            return {
                "conclusion": "This is a dangerous-goods smoke or fire-related incident. Isolate the area first, then handle it through the dangerous-goods firefighting response process.",
                "steps": (
                    "1. Isolate the container or cargo and evacuate unprotected personnel.\n"
                    "2. Check the UN number, IMDG class, MSDS, segregation requirements, and firefighting restrictions.\n"
                    "3. Do not open, move, flush, or approach the cargo blindly.\n"
                    "4. Notify firefighting, safety, dangerous-goods, maritime, environmental, carrier, and agent contacts.\n"
                    "5. Choose cooling, ventilation, containment, absorption, transfer, or specialist handling according to the material.\n"
                    "6. Record container number, location, temperature, smoke, odor, actions, and notifications."
                ),
            }
        if "fire" in groups:
            return {
                "conclusion": "This is a port fire or suspected fire incident. Report it immediately, evacuate personnel, isolate energy sources, and activate the port firefighting emergency plan.",
                "steps": (
                    "1. Report the fire and activate the firefighting emergency plan.\n"
                    "2. Evacuate personnel, cordon the area, and keep fire access routes open.\n"
                    "3. Cut relevant power, fuel, gas, shore-power, charging, or high-risk equipment sources.\n"
                    "4. Identify the fire source, cargo type, dangerous-goods exposure, nearby risks, and wind direction.\n"
                    "5. Notify firefighting, port safety, dispatch, maritime, environmental, and duty management teams.\n"
                    "6. After control, monitor reignition risk, assess losses, preserve evidence, and review the incident."
                ),
            }
        if "spill" in groups:
            return {
                "conclusion": "This is an oil spill or pollution incident. Stop the source, contain the spread, and notify environmental and maritime response owners.",
                "steps": (
                    "1. Confirm the source, product type, volume, spread direction, and whether water is affected.\n"
                    "2. Stop the related operation and isolate the leak source.\n"
                    "3. Deploy booms, absorbent pads, diversion, or temporary containment.\n"
                    "4. Notify environmental, maritime, safety, dispatch, and emergency response teams.\n"
                    "5. Collect and dispose of pollutants according to rules.\n"
                    "6. Record pollution scope, materials used, monitoring results, notification times, and responsibility chain."
                ),
            }
        if "injury" in groups:
            return {
                "conclusion": "This is a personnel injury incident. Protect life first, stop the related operation, and prevent secondary harm.",
                "steps": (
                    "1. Stop the related operation and protect life safety first.\n"
                    "2. Call emergency medical support, HSE, safety staff, and the duty lead.\n"
                    "3. Isolate the area to prevent secondary harm from vehicles, machinery, lifting gear, or electricity.\n"
                    "4. Preserve the scene, video, equipment status, and work permits without delaying rescue.\n"
                    "5. Notify relevant departments, contractors, and management as required.\n"
                    "6. Complete investigation, corrective actions, work-resumption checks, and training review."
                ),
            }
        if "vehicle" in groups:
            return {
                "conclusion": "This is a port traffic or vehicle incident. Confirm personnel safety first, control the road, and preserve evidence.",
                "steps": (
                    "1. Stop vehicles and control the accident road section.\n"
                    "2. Check injuries first and call medical help if needed.\n"
                    "3. Notify traffic, safety, dispatch, equipment, and duty management teams.\n"
                    "4. Preserve video, plate numbers, driver information, route, equipment status, and photos.\n"
                    "5. Adjust gates, roads, yard equipment, and traffic diversion according to impact.\n"
                    "6. Complete incident handling, responsibility assessment, road recovery, and review."
                ),
            }
        return {
            "conclusion": "This is an operational exception that should be handled through confirm, isolate, handle, and review steps.",
            "steps": (
                "1. Confirm the object, location, system module, and time window.\n"
                "2. Verify system data, monitoring data, logs, and manual records.\n"
                "3. Isolate high-risk actions and notify responsible owners.\n"
                "4. Handle according to risk level and operational impact.\n"
                "5. Record causes, actions, responsible persons, results, and reusable playbooks."
            ),
        }

    def _next_questions(self, intent: str) -> list[str]:
        if intent in {"greeting", "identity", "capability", "thanks", "farewell"}:
            return [
                "你能做什么？",
                "小懿的核心能力是什么？",
                "TOS 系统在码头运营里负责什么？",
            ]
        if intent == "qa_forms":
            return [
                "出口箱从进闸到装船的流程是什么？",
                "泊位利用率如何计算和解释？",
                "判断这个问题需要哪些数据源？",
            ]
        if intent in {"process_flow", "metric_calculation", "cause_analysis", "comparison"}:
            return [
                "这个问题涉及哪些业务指标？",
                "需要哪些数据源支撑这个判断？",
                "这个问题在港口现场怎么落地？",
            ]
        if intent in {"decision_priority", "evidence_data", "system_interface", "template"}:
            return [
                "这个判断需要谁人工确认？",
                "哪些证据需要进入审计记录？",
                "如何把它整理成 SOP？",
            ]
        if intent == "system_intro":
            return [
                "小懿的系统架构是什么？",
                "小懿和通用大模型有什么区别？",
                "如何把它接入真实港口系统？",
            ]
        if intent == "alert_explain":
            return [
                "这个告警需要哪些人工确认？",
                "如何生成一份 SOP？",
                "哪些证据需要进入审计记录？",
            ]
        return [
            "这个问题在港口现场怎么落地？",
            "这个问题涉及哪些业务指标？",
            "需要哪些数据源支撑这个判断？",
        ]
