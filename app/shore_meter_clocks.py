"""Check explicitly attributed ship-call clock readings against signed meter records."""
import re
from datetime import datetime, timedelta, timezone


CLOCK = re.compile(r"(?<!\d)(\d{1,2})[:：](\d{2})(?:[:：](\d{2}))?(?!\d)")
ROLE = re.compile(r"离泊|离港|到泊|靠泊|到港")
CALL = re.compile(r"SC_\d{5}")


def verify_clock_claims(answer, receipts):
    calls = [r for r in receipts if r.get("schema") == "gullmate.shore-call-review.v1"]
    issues = []
    if not calls:
        return answer, issues

    def check_clause(clause):
        # A ship identifier can follow the timestamp within a single clause.
        names = set(CALL.findall(clause))
        rows = [r for r in calls if not names or r["call"] in names]
        def check(match):
            prefix = clause[:match.start()]
            roles = list(ROLE.finditer(prefix))
            if not roles:
                return match.group()
            role = roles[-1]
            context = prefix[role.end():]
            if not re.fullmatch(r"[\s为在到是登记时间刻于：:()（）]*(?:(?:北京时间|上海当地时间|东八区|UTC(?:\+0?8)?)[\s：:()（）]*)?(?:20\d\d-\d\d-\d\d[T ]?)?", context, re.I):
                return match.group()
            if len(rows) != 1 or len(names) > 1:
                issues.append("该时刻无法唯一对应到所引用的船次电表。")
                return match.group()
            key = "etd" if role.group() in ("离泊", "离港") else "eta"
            stamp = datetime.fromisoformat(rows[0][key])
            zone_text = prefix[max(0,role.start()-6):] + (re.match(r"[（(]?(?:北京时间|上海当地时间|东八区|UTC\+0?8)",clause[match.end():],re.I) or [""])[0]
            zone = timezone(timedelta(hours=8)) if re.search(r"上海当地时间|北京时间|东八区|UTC\+0?8", zone_text, re.I) else timezone.utc
            stamp = stamp.astimezone(zone)
            h, m, s = match.groups()
            if (int(h), int(m)) == (stamp.hour, stamp.minute) and (s is None or int(s) == stamp.second):
                return " "
            issues.append("所述船次到泊或离泊时刻与引用的电表登记时间不符。")
            return match.group()
        return CLOCK.sub(check, clause)
    parts = re.split(r"([，,；;。！？\n])", answer)
    return "".join(check_clause(part) for part in parts), issues
