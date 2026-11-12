"""Check two narrowly scoped provisions against declared historical facts. No production actions."""
from datetime import date
import hashlib
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

ROOT=Path(__file__).resolve().parents[1]/"data/shore_case_20250701"
NOTES_HASH="1b0fe269df32ccc0070fe324e40adf53ed67a82e235bf5304adf020655b501f7"
SH_HASH="a2d8964d7dda691ca2a3a1bbd302c949b7ec67af7282c02a7882f23a8b9ca6b8"


class MinutesRange(BaseModel):
    model_config=ConfigDict(extra="forbid",allow_inf_nan=False)
    lower: float | None = Field(None,ge=0,le=525600,strict=True)
    upper: float | None = Field(None,ge=0,le=525600,strict=True)
    lower_inclusive: StrictBool = True
    upper_inclusive: StrictBool = True

    @model_validator(mode="after")
    def valid_interval(self):
        if self.lower is None and self.upper is None:
            raise ValueError("时长至少需要一个有证据的边界")
        low=0 if self.lower is None else self.lower
        if self.upper is not None and (self.upper<low or self.upper==low and
                ((self.lower is not None and not self.lower_inclusive) or not self.upper_inclusive)):
            raise ValueError("靠泊时长区间为空")
        return self


class ShoreCase(BaseModel):
    model_config=ConfigDict(extra="forbid",allow_inf_nan=False)
    as_of: date
    in_china: StrictBool | None = None
    in_shanghai_port: StrictBool | None = None
    waters: Literal["coastal","inland"] | None = None
    liquid_cargo_ship: StrictBool | None = None
    oil_chemical_terminal: StrictBool | None = None
    ship_receiver: StrictBool | None = None
    berth_supply: StrictBool | None = None
    berth_minutes: float | None = Field(None,ge=0,le=525600,strict=True)
    berth_range: MinutesRange | None = None
    effective_alternative_used: StrictBool | None = None
    unavailability_exception: Literal["none","temporary_failure","incompatible","emergency_prevents_use"] | None = None

    @model_validator(mode="after")
    def consistent_jurisdiction(self):
        if self.in_shanghai_port is True and self.in_china is False:
            raise ValueError("上海港与境外港的记录不一致")
        if self.berth_minutes is not None and self.berth_range is not None:
            raise ValueError("精确时长与范围只能登记一种")
        return self


def command(text):
    parts=text.strip().split(maxsplit=1)
    if not parts or parts[0]!="/岸电历史核对":return None
    if len(parts)!=2:raise ValueError("岸电历史核对命令需要一份 JSON 格式的历史案例")
    return ShoreCase.model_validate_json(re.split(r"\n\s*变更[：:]",parts[1],maxsplit=1)[0])


def command_change(text):
    if not re.match(r"^\s*/岸电历史核对(?:\s|$)",text):return None
    parts=re.split(r"\n\s*变更[：:]",text)
    if len(parts)==1:return None
    if len(parts)!=2 or not 2<=len(parts[1].strip())<=1000:raise ValueError("历史案例需要一段明确的变更说明")
    return parts[1].strip()


def source_notes():
    raw=(ROOT/"source-notes.json").read_bytes()
    if hashlib.sha256(raw).hexdigest()!=NOTES_HASH:raise ValueError("岸电条款资料摘要校验失败")
    notes=json.loads(raw)
    if (notes["local"]["sha256"]!=SH_HASH or hashlib.sha256((ROOT/"shanghai.html").read_bytes()).hexdigest()!=SH_HASH):
        raise ValueError("上海通知来源页校验失败")
    return notes


def inverse(value):return None if value is None else not value


def duration(waters,minutes,bounds=None):
    thresholds={"coastal":[180],"inland":[120],None:[120,180]}[waters]
    def decision(limit):
        if minutes is not None:return minutes>limit
        if bounds is None:return None
        if bounds.lower is not None and (bounds.lower>limit or bounds.lower==limit and not bounds.lower_inclusive):
            return True
        if bounds.upper is not None and bounds.upper<=limit:return False
        return None
    outcomes={decision(t) for t in thresholds}
    return next(iter(outcomes)) if len(outcomes)==1 else None


def conclusion(checks):
    disproved=[name for name,value in checks.items() if value is False]
    missing=[name for name,value in checks.items() if value is None]
    label="N" if disproved else "U" if missing else "Y"
    return {"label":label,"conditions":checks,"disproved":disproved,"missing":missing}


def evaluate(case):
    notes=source_notes()
    china=True if case.in_shanghai_port else case.in_china
    shanghai=False if case.in_china is False else case.in_shanghai_port
    if case.as_of.isoformat()!=notes["as_of"]:
        national=conclusion({"案例日与核验版本对应":None})
        local=conclusion({"案例日与核验版本对应":None})
    else:
        national=conclusion({"在中国境内":china,"船舶非液货船":inverse(case.liquid_cargo_ship),
            "船有受电设施":case.ship_receiver,"泊位具备岸电供应能力":case.berth_supply,
            "靠泊严格超过适用时长":duration(case.waters,case.berth_minutes,case.berth_range),
            "没有使用有效替代":inverse(case.effective_alternative_used),
            "已排除规定的无法接电情形":None if case.unavailability_exception is None else case.unavailability_exception=="none"})
        local=conclusion({"属于上海港":shanghai,"船舶非液货船":inverse(case.liquid_cargo_ship),
                          "码头非油气化工码头":inverse(case.oil_chemical_terminal)})
    national.update(document="港口和船舶岸电管理办法（2025年修正）",clause="第十一条第一款",url=notes["national"]["url"])
    local.update(document="沪交科〔2024〕823号",clause="第一项",url=notes["local"]["url"])
    facts=case.model_dump(mode="json")
    if case.berth_range is None:facts.pop("berth_range")
    digest=hashlib.sha256(json.dumps(facts,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    return {"schema":"gullmate.shore-history.v2" if case.berth_range else "gullmate.shore-history.v1",
            "as_of":facts["as_of"],"registered_date":notes["as_of"],"case_sha256":digest,
            "evidence_sha256":NOTES_HASH,"city_page_sha256":SH_HASH,"national":national,"local":local,
            "scope":"由用户提供历史演练事实，仅判两项具名条款；其他法律、许可、现场接电和处罚另行核验。",
            "production_authority":False}


def summary(receipt):
    texts=[]
    for topic,label in [("national","国家规章的用电义务"),("local","上海通知的平台使用义务")]:
        r=receipt[topic]
        if r["label"]=="Y":reason="所列条件成立"
        elif r["label"]=="N":reason="该具名条款不能据此确立义务，未满足条件为"+"、".join(r["disproved"])
        else:reason="资料不足，待核验"+"、".join(r["missing"])
        texts.append(f"{label}：{reason}。依据《{r['document']}》{r['clause']}。[原文]({r['url']})")
    amendment=receipt.get("amendment",{})
    bounds=amendment.get("confirmed_berth_range")
    if bounds:
        lower=bounds.get("lower");upper=bounds.get("upper")
        terms=[]
        if lower is not None:terms.append(("不少于" if bounds["lower_inclusive"] else "超过")+f" {lower:g} 分钟")
        if upper is not None:terms.append(("不超过" if bounds["upper_inclusive"] else "不足")+f" {upper:g} 分钟")
        texts.insert(0,"原文只确定靠泊时长"+"且".join(terms)+"。")
    return "按 "+receipt["as_of"]+" 的历史演练记录核对。\n"+"\n".join(texts)+"\n"+receipt["scope"]
