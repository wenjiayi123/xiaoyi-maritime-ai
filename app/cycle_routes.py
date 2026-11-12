from typing import Literal
from fastapi import APIRouter,HTTPException,Request
from pydantic import Field
from app import cycle_workflow as workflow
from app.harness.contracts import StrictModel
from app.harness.api import perform
from app.access_control import has_permission
from app.security import request_identity

router=APIRouter(prefix="/api/decision-cycles",tags=["自主决策工单"])


class SandboxRequest(StrictModel):
    scope:Literal["historical_sandbox"]
    proposal_sha:str=Field(pattern=r"^[0-9a-f]{64}$")
    state_sha:str=Field(pattern=r"^[0-9a-f]{64}$")
    request_key:str=Field(pattern=r"^[a-zA-Z0-9_-]{8,90}$")
    reason:str=Field(min_length=1,max_length=240)
    evaluation_sha:str|None=Field(default=None,pattern=r"^[0-9a-f]{64}$")


def identity(request,permission):
    person=request_identity(request)
    if not has_permission(person.role,permission):
        raise HTTPException(403,"当前身份缺少对应权限")
    return person


@router.get("")
def catalog(request:Request):
    identity(request,"chat.use")
    return perform(workflow.catalog)


@router.get("/{case_id}")
def status(case_id:str,request:Request,scenario:str|None=None):
    identity(request,"chat.use")
    return perform(lambda:workflow.read_status(case_id,scenario))


@router.post("/{case_id}/{action}")
def act(case_id:str,action:Literal["sign","execute","submit_evaluation","finish_evaluation","rollback"],payload:SandboxRequest,
        request:Request,scenario:str|None=None):
    actor=identity(request,"operations.manage")
    if not actor.authenticated:
        raise HTTPException(403,"工单签注及沙箱写入使用已认证的操作员身份")
    return perform(lambda:workflow.transact(case_id,scenario,action,payload,actor.actor_id))
