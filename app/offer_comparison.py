"""Evidence-bound, read-only comparison of declared berth or shore-power offers."""
from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from app.harness.contracts import StrictModel, digest

Source = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=96, pattern=r"^[^\x00-\x1f\x7f]+$")]
OfferID = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32, pattern=r"^[\w.-]+$")]
Amount = Annotated[Decimal, Field(ge=0, le=Decimal("1000000000000"), max_digits=20, decimal_places=6)]
Positive = Annotated[Amount, Field(gt=0)]
Profile = Literal["berth", "shore_power"]
UNITS = {"berth": ("CNY", "m"), "shore_power": ("CNY/kWh", "kW")}


class Offer(StrictModel):
    id: OfferID
    price: Amount | None = None
    quote_ref: Source | None = None
    limit: Amount | None = None
    assessment: Literal["pass", "fail", "unknown"] = "unknown"
    check_ref: Source | None = None
    valid_from: AwareDatetime | None = None
    valid_until: AwareDatetime | None = None

    @model_validator(mode="after")
    def check_window(self):
        if self.valid_from and self.valid_until and self.valid_from >= self.valid_until:
            raise ValueError("有效期结束时间须晚于起始时间")
        return self


class OfferSheet(StrictModel):
    """Price and limit units are fixed at the sheet boundary, never inferred."""
    profile: Profile
    as_of: AwareDatetime | None = None
    required: Positive | None = None
    requirement_ref: Source | None = None
    offers: list[Offer] = Field(min_length=2, max_length=16)

    @model_validator(mode="after")
    def check_inputs(self):
        if len({row.id.casefold() for row in self.offers}) != len(self.offers):
            raise ValueError("候选编号必须唯一")
        if self.as_of is None and any(row.valid_from or row.valid_until for row in self.offers):
            raise ValueError("带有效期的记录需要带时区的比选时刻")
        return self


def display(value: Decimal) -> str:
    fixed = format(value, "f")
    return fixed.rstrip("0").rstrip(".") if "." in fixed else fixed


def check_offer(sheet: OfferSheet, row: Offer) -> dict:
    price_unit, limit_unit = UNITS[sheet.profile]
    reasons = []
    current = not (
        row.valid_from is not None and sheet.as_of < row.valid_from
        or row.valid_until is not None and sheet.as_of >= row.valid_until
    )
    price = row.price if current and row.quote_ref is not None else None
    if not current:
        eligibility = "unknown"
        reasons.append("整行证据在比选时刻无效")
    elif row.check_ref is None:
        eligibility = "unknown"
        reasons.append("缺少约束核验来源")
    elif row.assessment == "fail":
        eligibility = "ineligible"
        reasons.append("核验记录明确不满足约束")
    elif row.limit is not None or sheet.required is not None:
        # Once a quantitative requirement is declared, a verbal 'pass' cannot replace its evidence.
        if sheet.required is None or row.limit is None or sheet.requirement_ref is None:
            eligibility = "unknown"
            reasons.append("数值约束需要需求、需求来源及该候选上限")
        elif row.limit < sheet.required:
            eligibility = "ineligible"
            reasons.append(f"上限 {display(row.limit)} {limit_unit} 低于需求 {display(sheet.required)} {limit_unit}")
        else:
            eligibility = "eligible"
            reasons.append(f"上限 {display(row.limit)} {limit_unit} 满足需求 {display(sheet.required)} {limit_unit}")
    elif row.assessment == "pass":
        eligibility = "eligible"
        reasons.append("核验记录明确满足约束")
    else:
        eligibility = "unknown"
        reasons.append("约束核验结果待补")
    if price is None:
        reasons.append("缺少有效报价或报价来源")
    return {
        "id": row.id, "eligibility": eligibility, "price": display(price) if price is not None else None,
        "unit": price_unit, "limit": display(row.limit) if row.limit is not None else None,
        "limit_unit": limit_unit, "assessment": row.assessment,
        "quote_ref": row.quote_ref, "check_ref": row.check_ref, "reasons": reasons,
    }


def compare(sheet: OfferSheet) -> dict:
    rows = [check_offer(sheet, row) for row in sheet.offers]
    priced = [row for row in rows if row["eligibility"] == "eligible" and row["price"] is not None]
    minimum = min((Decimal(row["price"]) for row in priced), default=None)
    leaders = sorted(row["id"] for row in priced if Decimal(row["price"]) == minimum)
    blockers = sorted(
        row["id"] for row in rows if row["eligibility"] != "ineligible"
        and (row["price"] is None or row["eligibility"] == "unknown"
             and (minimum is None or Decimal(row["price"]) <= minimum))
    )
    if blockers:
        status = "needs_evidence"
    elif not leaders:
        status = "no_feasible"
    elif len(leaders) > 1:
        status = "tie"
    else:
        status = "selected"
    result = {
        "schema": "xiaoyi.offer-comparison.v1", "status": status, "profile": sheet.profile,
        "scope": "user_declared_scenario", "production_authority": False,
        "as_of": sheet.as_of.isoformat() if sheet.as_of else None,
        "input": sheet.model_dump(mode="json"), "sheet_sha256": digest(sheet.model_dump(mode="json")), "required": display(sheet.required) if sheet.required is not None else None,
        "requirement_ref": sheet.requirement_ref, "price_unit": UNITS[sheet.profile][0],
        "winners": leaders if status in {"selected","tie"} else [],
        "minimum": display(minimum) if status in {"selected","tie"} else None,
        "known_leaders": leaders, "known_minimum": display(minimum) if minimum is not None else None,
        "blocking_ids": blockers, "rows": rows,
    }
    return {**result, "result_sha256": digest(result)}


def summarize(result: dict) -> str:
    status = result["status"]
    if status in {"selected", "tie"}:
        label = "并列最低可行报价" if status == "tie" else "最低可行报价"
        lead = f"{label}为 {result['minimum']} {result['price_unit']}，候选为 {'、'.join(result['winners'])}。"
    elif status == "no_feasible":
        lead = "所有候选都被本轮约束排除。"
    else:
        lead = f"尚不能确定最低可行报价，需补齐 {'、'.join(result['blocking_ids'])} 的证据。"
        if result["known_leaders"]:
            lead += f" 已核实可行的最低价为 {result['known_minimum']} {result['price_unit']}（{'、'.join(result['known_leaders'])}），仍为暂定。"
    details = []
    for row in result["rows"]:
        price = f"{row['price']} {result['price_unit']}" if row["price"] is not None else "价格待核验"
        refs = list(dict.fromkeys(filter(None,[row["quote_ref"],row["check_ref"],result["requirement_ref"]])))
        details.append(f"• {row['id']}，{price}。{'；'.join(row['reasons'])}。" + (f" 依据：{'、'.join(refs)}。" if refs else ""))
    return lead + "\n" + "\n".join(details) + "\n结论限于本轮声明的方案、报价和约束，现场执行需另行授权。"
