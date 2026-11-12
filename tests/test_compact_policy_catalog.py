from app.harness.model import compact_tool_menu
from app.harness.tools import catalog


def test_compact_menu_retains_authorized_tools_approval_required_names_and_enums():
    items=catalog("operator",["linked.action","policy.vessel_schedule","policy.shore_storage","research.parallel"])
    compact=compact_tool_menu(items)
    assert [v["name"] for v in compact]==[v["name"] for v in items]
    for entry,source in zip(compact,items,strict=True):
        assert entry["requires_approval"]==source["requires_approval"]
        assert entry["required"]==source["parameters"].get("required",[])
        assert entry["description"]==source["description"]
        assert set(entry["fields"])==set(source["parameters"]["properties"])
    assert next(v for v in compact if v["name"]=="linked.action")["requires_approval"]
    assert "repair" in next(v for v in compact if v["name"]=="policy.vessel_schedule")["fields"]["method"]
