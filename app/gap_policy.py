"""必填缺口政策。條件欄（單位號等）永不阻塞出報告。"""

from __future__ import annotations

import re

from app.extract import (
    _UNCERTAIN_FLOOR,
    _written_lines,
    apply_written_facts,
    clocks,
    specific_location,
)
from app.lexicon import auto_rewrite
from app.location_assembly import (
    enforce_location_integrity,
    infer_location_from_text,
    is_bare_spot_location,
    transcript_implies_floor,
)

LABEL_DATE = "日期"
LABEL_TIME = "時間或時段"
LABEL_LOCATION = "地點"
LABEL_FLOOR = "樓層（口述未能確定）"
LABEL_FACTS = "客觀事實"
LABEL_ACTION = "已做行動或「未有行動記錄」"

# 必填缺口（永不包含 unit／單位號）
MANDATORY_GAP_LABELS = (
    LABEL_DATE,
    LABEL_TIME,
    LABEL_LOCATION,
    LABEL_FLOOR,
    LABEL_FACTS,
    LABEL_ACTION,
)

UNIT_STATUS_NA = "na"
UNIT_STATUS_UNRECORDED = "unrecorded"

_UNIT_GAP = re.compile(r"單位|鋪號|房號|室號")

_PUBLIC_PLACE = re.compile(
    r"垃圾房|渠口|沙井|大堂|走廊|地下|地庫|車場|地坪|工地|平台|平臺|後樓梯|楼梯|樓梯|天台|"
    r"接待處|會所|泳池|公眾地方|公用|花園|卸貨區|卸货区"
)
_UNIT_NOT_APPLICABLE = re.compile(
    r"無涉及單位|不涉及單位|无涉及单位|不涉及单位|不適用|不适用|"
    r"單位(?:號碼|号码)?\s*無涉及|號碼\s*無涉及|無涉及\s*(?:單位|单位)(?:號碼|号码)?|"
    r"冇單位|没有单位|无单位|"
    r"公用地方|公眾地方|"
    r"單位[^\n。，；]{0,20}(?:睇唔到|看不到|未能|唔知|未知|不清楚)|"
    r"(?:睇唔到|看不到)[^\n。，；]{0,12}(?:單位|幾樓|楼层)"
)
_UNIT_UNRECORDED = re.compile(r"單位號未有記錄|单位号未有记录")
_BLOCK = re.compile(r"([A-Za-z])\s*座")
_FLOOR_GARBAGE = re.compile(r"(?P<floor>\d{1,2})\s*樓\s*垃圾房(?:門外)?(?:走廊)?")
_PRIVATE_UNIT = re.compile(
    r"對面\s*單位|入\s*單位|入屋|室內|\d+\s*室|[A-Za-z]\s*室|商舖|店舖|鋪位|铺位|住戶\s*單位"
)
_NONE_ACTION = re.compile(r"未有行動|沒有行動|無採取行動|未採取行動|報告時未有行動")
_FACT_HINT = re.compile(
    r"見到|看到|睇到|聽到|聽見|聞到|發現|溢|漏|污水|滴水|抽煙|吸煙|煙灰|"
    r"喧嘩|嘈|跌|損|污|臭|男子|女子|有人|車|倒|流"
)
_LOC_SNIPPET = re.compile(
    r"[A-Za-z]座\s*\d{1,2}\s*樓\s*垃圾房(?:門外)?(?:走廊)?|[A-Za-z]座\s*地下|[A-Za-z]座\s*\d{1,2}\s*樓|"
    r"[\u4e00-\u9fff]{2,8}邨|\d{1,2}\s*樓\s*垃圾房(?:門外)?(?:走廊)?|"
    r"[A-Za-z]座\s*\d{1,2}\s*樓\s*電梯|\d{1,2}\s*樓\s*電梯|"
    r"垃圾房(?:對出|外|旁)?(?:門外)?(?:走廊)?|大堂|車位|走廊|後樓梯|電梯大堂|地庫|工地|電梯"
)


def _loc_snippets(text: str) -> list[str]:
    raw = text or ""
    out: list[str] = []
    for match in _LOC_SNIPPET.finditer(raw):
        out.append(re.sub(r"\s+", "", match.group(0)))
    garbage = _FLOOR_GARBAGE.search(raw)
    if garbage:
        out.append(re.sub(r"\s+", "", garbage.group(0)))
    return out


def _infer_location(text: str) -> str | None:
    return infer_location_from_text(text, specific_location, extra_snippets=_loc_snippets)


def without_unit_gaps(missing: list[str], state: dict | None = None) -> list[str]:
    """條件欄（單位 na／未有記錄）永不進缺口清單。"""
    unit = None
    if state:
        unit = state.get("unit") or (state.get("fields") or {}).get("unit") or {}
    status = (unit or {}).get("unit_status")
    if status in {UNIT_STATUS_NA, UNIT_STATUS_UNRECORDED}:
        return [item for item in missing if not _UNIT_GAP.search(item)]
    return [item for item in missing if not _UNIT_GAP.search(item)]


def _maybe_default_session_date(state: dict, fields: dict, text: str) -> None:
    field = fields.get("date") or {}
    if field.get("status") == "confirmed" and field.get("value"):
        return
    if re.search(r"今日|今天|今個日", text or ""):
        return
    if state.get("channel") != "voice":
        return
    label = state.get("session_today_label")
    iso = state.get("session_today")
    if not label or not iso:
        return
    time_f = fields.get("time") or {}
    if time_f.get("status") != "confirmed" or not time_f.get("value"):
        return
    loc = (fields.get("location") or {}).get("value") or ""
    if not re.search(r"[A-Za-z]座\s*\d{1,2}\s*樓", re.sub(r"\s+", "", loc)):
        return
    if not _facts_ready(fields, text) or not _action_ready(fields, text):
        return
    fields["date"] = {"value": label, "status": "confirmed", "origin": "auto"}
    state["date_iso"] = iso


def prepare_fields(state: dict) -> None:
    """合併口述後補齊可自動判斷的欄位（唔代填虛構）。"""
    fields = state.setdefault("fields", {})
    text = state.get("transcript") or ""
    apply_written_facts(fields, text)
    if _NONE_ACTION.search(text):
        fields["action_taken"] = {"value": "報告時未有行動記錄", "status": "unknown", "origin": "auto"}
    inferred = _infer_location(text)
    loc = fields.get("location") or {}
    current = (loc.get("value") or "").strip()
    if current and re.search(r"\d{1,2}\s*樓", current):
        inferred = None
    if inferred and (not current or len(inferred) > len(current) or is_bare_spot_location(current)):
        fields["location"] = {"value": inferred, "status": "confirmed", "origin": "auto"}
    enforce_location_integrity(fields, text)
    _maybe_default_session_date(state, fields, text)


def _unit_public_or_na(state: dict) -> bool:
    text = state.get("transcript") or ""
    place = ((state.get("fields") or {}).get("location") or {}).get("value") or ""
    blob = f"{text}\n{place}"
    if _PUBLIC_PLACE.search(blob):
        return True
    if _UNIT_NOT_APPLICABLE.search(text):
        return True
    return False


def unit_applicable(state: dict) -> bool:
    if _unit_public_or_na(state):
        return False
    text = state.get("transcript") or ""
    place = ((state.get("fields") or {}).get("location") or {}).get("value") or ""
    blob = f"{text}\n{place}"
    return bool(_PRIVATE_UNIT.search(blob))


def resolve_unit_field(state: dict) -> dict:
    """條件欄：永不阻塞 required_gaps。"""
    text = state.get("transcript") or ""
    existing = state.get("unit") or (state.get("fields") or {}).get("unit")
    if existing and existing.get("status") == "confirmed" and re.search(r"\d", existing.get("value") or ""):
        return existing
    if _UNIT_UNRECORDED.search(text):
        return {
            "value": "未有記錄",
            "status": "unknown",
            "unit_status": UNIT_STATUS_UNRECORDED,
            "origin": "auto",
        }
    if _unit_public_or_na(state):
        return {
            "value": "不適用",
            "status": "confirmed",
            "unit_status": UNIT_STATUS_NA,
            "origin": "auto",
        }
    if unit_applicable(state):
        return {
            "value": "未有記錄",
            "status": "unknown",
            "unit_status": UNIT_STATUS_UNRECORDED,
            "origin": "auto",
        }
    return {
        "value": "不適用",
        "status": "confirmed",
        "unit_status": UNIT_STATUS_NA,
        "origin": "auto",
    }


def note_conditional_fields(state: dict) -> None:
    """條件欄寫入狀態，唔進缺口清單。"""
    fields = state.setdefault("fields", {})
    unit = resolve_unit_field(state)
    state["unit"] = unit
    fields["unit"] = unit


def _date_ready(fields: dict, text: str) -> bool:
    field = fields.get("date") or {}
    return field.get("status") in {"confirmed", "unknown"} and bool(field.get("value"))


def _time_ready(fields: dict, state: dict) -> bool:
    if state.get("timeline"):
        return True
    field = fields.get("time") or {}
    if field.get("status") == "unknown" and field.get("value"):
        return True
    if field.get("status") == "needs_confirm":
        return False
    if field.get("status") != "confirmed" or not field.get("value"):
        return False
    if field.get("vague") and not str(field.get("value", "")).startswith("約"):
        return False
    text = state.get("transcript") or ""
    if re.search(r"點幾|十一點幾|十點幾", text) and len(clocks(text)) < 1 and not state.get("timeline"):
        vague_only = field.get("vague") and not re.search(r"約", field.get("value") or "")
        if vague_only:
            return False
    return True


def _floor_uncertain(fields: dict, text: str) -> bool:
    floor_field = fields.get("floor") or {}
    if floor_field.get("status") == "confirmed" and floor_field.get("value"):
        return False
    loc = fields.get("location") or {}
    value = loc.get("value") or ""
    if loc.get("status") == "confirmed" and re.search(r"\d{1,2}\s*樓|地下|地庫", value):
        return False
    return bool(_UNCERTAIN_FLOOR.search(text))


def _location_ready(fields: dict, text: str) -> bool:
    loc = fields.get("location") or {}
    if loc.get("status") == "confirmed" and loc.get("value"):
        value = loc.get("value") or ""
        if is_bare_spot_location(value) and transcript_implies_floor(text):
            return False
        return not _floor_uncertain(fields, text)
    return bool(specific_location(text) or _LOC_SNIPPET.search(text) or _FLOOR_GARBAGE.search(text))


def _facts_ready(fields: dict, text: str) -> bool:
    action = fields.get("action") or {}
    if action.get("value") and action.get("status") in {"confirmed", "unknown"}:
        return True
    seen, _, _ = _written_lines(auto_rewrite(text))
    if seen:
        return True
    if _FACT_HINT.search(text) and re.search(r"見|聞|聽|發現|好臭|溢|漏", text):
        return True
    return False


def _action_ready(fields: dict, text: str) -> bool:
    taken = fields.get("action_taken") or {}
    if taken.get("value") and taken.get("status") in {"confirmed", "unknown"}:
        return True
    _, done, _ = _written_lines(auto_rewrite(text))
    if done:
        return True
    if _NONE_ACTION.search(text):
        return True
    if re.search(r"通知|勸喻|圍欄|已做|我做|採取", text):
        return True
    return False


def required_gaps(state: dict) -> list[str]:
    """只返回必填缺口（條件欄永不列出）。"""
    prepare_fields(state)
    note_conditional_fields(state)
    fields = state.get("fields") or {}
    text = state.get("transcript") or ""
    missing: list[str] = []
    if not _date_ready(fields, text):
        missing.append(LABEL_DATE)
    if not _time_ready(fields, state):
        missing.append(LABEL_TIME)
    if not _location_ready(fields, text):
        if _floor_uncertain(fields, text):
            missing.append(LABEL_FLOOR)
        else:
            missing.append(LABEL_LOCATION)
    if not _facts_ready(fields, text):
        missing.append(LABEL_FACTS)
    if not _action_ready(fields, text):
        missing.append(LABEL_ACTION)
    return without_unit_gaps(missing, state)
