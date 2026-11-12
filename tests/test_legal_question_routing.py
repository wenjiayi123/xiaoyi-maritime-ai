from datetime import date
from app.knowledge_policy import asks_penalty_amount_to_apply
from app.workforce_daily import is_general_workforce_question
from app.xiaoyi import XiaoyiAI


def test_national_reference_is_not_first_person_daily_advice():
    assert not is_general_workforce_question("我国海洋环境保护法当时有效吗")
    assert not is_general_workforce_question("我方应向哪个主管部门核对法律版本")
    assert is_general_workforce_question("我该怎么安排周末休息")


def test_normative_fine_needs_legal_text_not_ais():
    question = "上海港某船今天排放污水，应当确切罚款多少元？请直接裁定金额。"
    response = XiaoyiAI().ask(question,strict_evidence=True,jurisdiction="CN",as_of_date=date(2026,11,8))
    assert not response.grounded and response.refusal_reason == "official_full_text_required"
    assert response.evidence_requirement == "official_full_text"
    assert not asks_penalty_amount_to_apply("今天已缴罚款多少元？请查现有台账。")
