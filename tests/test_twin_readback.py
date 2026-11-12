import copy
import pytest
from app.shore_evidence import ShoreQuery,review_shore
from app.twin_readback import check_response


def test_twin_comparison_rejects_model_or_metric_substitution():
    r=review_shore(ShoreQuery(week="2026-01-01"))
    a=r["audited"]
    m={"schema":"twin.shore-storage-week.v1","week":r["week"],"part":r["part"],"weight_sha256":r["weight"],
       "hours":168,"production_authority":False,"methods":{"idle":r["baseline"],"best_fixed":r["fixed"],
            "selected":{**r["candidate"],"terminal_soc_error":a["terminal_soc_error"],"terminal_flex_backlog_kwh":a["terminal_queue_kwh"],"guardrail_violations":a["guardrail_violations"]}},
       "carbon_delta_by_component":{"battery_kg":a["battery_carbon_kg"],"flex_kg":a["flex_carbon_kg"]}}
    assert check_response(r,m)["fields"]==14
    for bad in ({**m,"production_authority":True},{**m,"hours":167},{**m,"part":"validation"},{**m,"weight_sha256":"00"}):
        with pytest.raises(ValueError):check_response(r,bad)
    altered=copy.deepcopy(m);altered["methods"]["selected"]["peak_kw"]+=.05
    with pytest.raises(ValueError,match="peak_kw"):check_response(r,altered)
