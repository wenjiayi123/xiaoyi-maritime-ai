from fastapi.testclient import TestClient
from app.main import app
from app.visual_evidence import search_figures


def test_figure_window_is_bound_to_the_displayed_dataset():
    result=search_figures("higher demand delay",0)
    hit=next(r for r in result["hits"] if r["id"]=="stress")
    source=hit["source_evidence"]
    window=source["selected_window"]
    assert len(window["source_row_ids"])==24
    assert window["index"]==0 and source["window_count"]==12
    assert source["dataset_package_sha256"]==hit["edges"][-1]["to"].removeprefix("sha256:")
    assert set(window["values"])==set(hit["values_from_source"])


def test_unknown_figure_window_is_rejected():
    with TestClient(app,base_url="http://127.0.0.1") as client:
        assert client.get("/api/knowledge/figures",params={"q":"higher demand delay","window":12}).status_code==422
