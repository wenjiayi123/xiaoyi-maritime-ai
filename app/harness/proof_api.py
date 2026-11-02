"""Identity-bound, finite, read-only analysis and local proof receipts."""

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from typing import Literal

from app.harness.api import perform
from app.harness.dual_api import identity_for
from app.harness import proof_v5, research_v6

router = APIRouter(prefix="/api/harness/proof", tags=["小懿实证演示"])


@router.get("/catalog")
def catalog(request: Request):
    identity = identity_for(request)
    return {**perform(proof_v5.catalog), "actor_id": identity.actor_id}


@router.get("/public-source/{port_id}")
def public_source(port_id: str, request: Request):
    identity_for(request)

    def download():
        entry = next((e for e in proof_v5.operations_v5.catalog()["entries"] if e["id"] == port_id), None)
        if entry is None:
            raise ValueError("未登记的公开数据")
        path = proof_v5.operations_v5.checked(entry["path"], entry["sha256"])
        return FileResponse(path, media_type="text/csv", filename=port_id + ".csv")

    return perform(download)


@router.post("/runs", status_code=201)
def run(payload: proof_v5.RunRequest, request: Request):
    identity = identity_for(request)
    return perform(lambda: proof_v5.run(payload, identity.actor_id))


@router.get("/research-source/{study}/{item}")
def research_source(study: Literal["rl", "history", "test"], item: int, request: Request):
    identity_for(request)

    def download():
        entry, path = research_v6.source(study, item)
        return FileResponse(
            path,
            media_type="application/gzip"
            if path.suffix == ".gz"
            else ("application/json" if entry.get("provider") == "noaa" else "text/csv"),
            filename=path.name,
            headers={"X-Content-SHA256": entry["sha256"]},
        )

    return perform(download)


@router.get("/runs/{run_id}")
def get(run_id: str, request: Request):
    identity = identity_for(request)
    return perform(lambda: proof_v5.get(run_id, identity.actor_id, identity.role == "admin"))


@router.get("/runs")
def history(request: Request):
    identity = identity_for(request)
    return {
        "items": [
            {k: v[k] for k in ["id", "kind", "created_at", "status", "parameters"]}
            for v in proof_v5.runtime_store.list_artifacts(proof_v5.KIND, limit=300)
            if v["actor_id"] == identity.actor_id or identity.role == "admin"
        ]
    }
