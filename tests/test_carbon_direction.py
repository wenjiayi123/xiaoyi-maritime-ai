from app.shore_carbon_direction import directions
from app.shore_evidence import review_shore,ShoreQuery


def test_claim_polarity_and_contributor():
    r=review_shore(ShoreQuery(week="2026-04-02"));goal={"goal":"联合调度少排还是多排多少 kg？"}
    assert directions("联合调度比待机少排了 34.493 kg 碳排放。",r,goal)==(["34.493"],[])
    assert directions("联合调度增加 34.493 kg 碳排放。",r,goal)[1]
    assert directions("联合调度少排 34.495 kg。",r,goal)[1]
    assert directions("电池少排了 34.493 kg。",r,goal)[1]
    assert directions("只是查询，没有数值。",r,goal)==([],[])


def test_multiple_cited_weeks_use_the_named_week_if_present():
    r=review_shore(ShoreQuery(week="2026-04-02"))
    s=review_shore(ShoreQuery(week="2026-01-01"))
    assert directions("2026-04-02 联合调度少排 34.493 kg。",[r,s],{})==(["34.493"],[])
    assert directions("2026-01-01 联合调度少排 34.493 kg。",[r,s],{})[1]
