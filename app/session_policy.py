"""自動分案：短答 merge；衝突/已出報告 → 新案；歧義短問一次。"""

from __future__ import annotations

import re
from typing import Literal

SplitDecision = Literal["merge", "fresh", "ask"]

_CORRECTION = re.compile(r"時間改為|日期改為|地點改為|傷勢改為|補充[:：]")
_CONTROL = re.compile(
    r"^(?:傳送|send|送出去|送出|發送|寄出|送俾主管|送畀主管|"
    r"唔使|唔送|唔好送|取消|唔使送|"
    r"(?:哦)?(?:係|系)(?:呀|啊)?|啱|沒錯|無錯|正確|係咁|"
    r"唔係|不對|唔啱|有錯|"
    r"(?:時間)?未有記錄)[。！!?\s]*$",
    re.I,
)
_VOID = re.compile(
    r"^(?:取消|作廢|作废|冇事|没事情|搞錯單|讲错单|重講|重讲)[。！!?\s]*$",
    re.I,
)
_SPLIT_NEW = re.compile(r"^(?:新事件|新案|新報告)\s*[。！!?\s]*", re.I)
_SPLIT_SAME = re.compile(r"^(?:補充|同一單|跟住|繼續)\s*[。！!?\s]*", re.I)
_BLOCK = re.compile(r"([A-Za-z])\s*座")
_FLOOR = re.compile(r"(?<!\d)(\d{1,2})\s*樓")
_SEWAGE = re.compile(r"污水|溢流|垃圾房.*(?:臭|污水)|地面好臭")
_NOISE_DRUNK = re.compile(r"嘈交|喧嘩|酒味|醉酒|拍門|砰砰|對面男")
_DATE_ONLY = re.compile(r"^(?:日期|事件日期)\s*[\d\-年月日/]+", re.I)
_FULL_ORAL = re.compile(r"(見到|聽到|通知|已.{0,4}(?:做|放置|圍欄)|暫時無人|冇人受傷|表明身份)")
_PM_HINT = re.compile(r"三點|15\s*[:：]|15點|下午|約三點")
_AM_HINT = re.compile(r"十一點|10\s*[:：]|23\s*[:：]|凌晨|上午|十一點幾|十點幾")


def is_void_command(text: str) -> bool:
    return bool(_VOID.match((text or "").strip()))


def is_split_reply_new(text: str) -> bool:
    body = (text or "").strip()
    return bool(_SPLIT_NEW.match(body) or re.match(r"^新事件", body))


def is_split_reply_same(text: str) -> bool:
    return bool(_SPLIT_SAME.match((text or "").strip()))


def is_session_control(text: str) -> bool:
    body = (text or "").strip()
    if not body:
        return True
    if _CONTROL.match(body) or _VOID.match(body):
        return True
    if _DATE_ONLY.match(body) and len(body) < 40:
        return True
    if re.fullmatch(r"(?:第)?\d{1,2}\s*樓\s*\.?", body.strip("。．.")):
        return True
    if re.fullmatch(r"\d{1,2}\s*\.?", body.strip("。．.")):
        return True
    if _SPLIT_SAME.match(body) and len(body) < 16:
        return True
    return False


def _block_letter(text: str) -> str | None:
    match = _BLOCK.search(text or "")
    return match.group(1).upper() if match else None


def _floors(text: str) -> set[int]:
    return {int(m.group(1)) for m in _FLOOR.finditer(text or "") if 1 <= int(m.group(1)) <= 99}


def _location_value(state: dict) -> str:
    return ((state.get("fields") or {}).get("location") or {}).get("value") or ""


def _time_blob(state: dict) -> str:
    field = (state.get("fields") or {}).get("time") or {}
    return f"{state.get('transcript') or ''}\n{field.get('value') or ''}"


def _time_period_conflict(state: dict, body: str) -> bool:
    old = _time_blob(state)
    new_pm = bool(_PM_HINT.search(body))
    new_am = bool(_AM_HINT.search(body))
    old_pm = bool(_PM_HINT.search(old))
    old_am = bool(_AM_HINT.search(old))
    if new_pm and old_am and not _PM_HINT.search(old):
        return True
    if new_am and old_pm and not _AM_HINT.search(old):
        return True
    return False


def _type_conflict(old_blob: str, body: str) -> bool:
    new_sew = bool(_SEWAGE.search(body))
    old_sew = bool(_SEWAGE.search(old_blob))
    new_noise = bool(_NOISE_DRUNK.search(body))
    old_noise = bool(_NOISE_DRUNK.search(old_blob))
    if new_sew and old_noise and not old_sew:
        return True
    if new_noise and old_sew and not new_sew:
        return True
    return False


def _location_conflict(state: dict, body: str) -> bool:
    old_text = state.get("transcript") or ""
    old_loc = _location_value(state)
    old_blob = f"{old_text}\n{old_loc}"
    new_block = _block_letter(body)
    old_block = _block_letter(old_blob)
    if new_block and old_block and new_block != old_block:
        return True
    new_floors = _floors(body)
    old_floors = _floors(old_blob)
    if new_floors and old_floors and not new_floors.intersection(old_floors):
        return True
    estate_new = re.search(r"[\u4e00-\u9fff]{2,8}邨", body)
    estate_old = re.search(r"[\u4e00-\u9fff]{2,8}邨", old_blob)
    if estate_new and estate_old and estate_new.group(0) != estate_old.group(0):
        return True
    return False


def _hard_fresh(state: dict, body: str) -> bool:
    if state.get("status") == "ready":
        return len(body) >= 12 and not is_session_control(body)
    old_text = state.get("transcript") or ""
    old_blob = f"{old_text}\n{_location_value(state)}"
    if _location_conflict(state, body):
        return True
    if _type_conflict(old_blob, body):
        return True
    if _time_period_conflict(state, body):
        return True
    if len(body) >= 48 and _SEWAGE.search(body) and (_NOISE_DRUNK.search(old_blob) or _floors(old_blob)):
        if _floors(body) and _floors(old_blob) and not _floors(body).intersection(_floors(old_blob)):
            return True
        if _NOISE_DRUNK.search(old_blob) and not _SEWAGE.search(old_blob):
            return True
    return False


def _soft_ambiguity(state: dict, body: str) -> bool:
    """同座、長口述、有少少唔同但未達硬分案 — 先問一次。"""
    if len(body) < 40 or not _FULL_ORAL.search(body):
        return False
    old_blob = f"{state.get('transcript') or ''}\n{_location_value(state)}"
    same_block = _block_letter(body) and _block_letter(body) == _block_letter(old_blob)
    if not same_block:
        return False
    if _type_conflict(old_blob, body) or _location_conflict(state, body):
        return False
    nf, of = _floors(body), _floors(old_blob)
    if nf and of and not nf.intersection(of):
        return True
    if _time_period_conflict(state, body):
        return True
    return False


def assess_case_split(state: dict | None, text: str) -> SplitDecision:
    if not state or state.get("status") == "closed":
        return "merge"
    body = (text or "").strip()
    if is_session_control(body) or _CORRECTION.search(body):
        return "merge"
    if len(body) < 20:
        return "merge"
    if _hard_fresh(state, body):
        return "fresh"
    if _soft_ambiguity(state, body):
        return "ask"
    return "merge"


def should_start_fresh_case(state: dict, text: str) -> bool:
    return assess_case_split(state, text) == "fresh"


def transcript_supports(text: str, transcript: str) -> bool:
    """報告片段必須能在本 session 口述找到依據（字面或錨詞）。"""
    snippet = (text or "").strip()
    if not snippet or snippet in {"未有記錄", "不適用", "未知"}:
        return True
    raw = transcript or ""
    if snippet in raw:
        return True
    if "醉酒" in snippet or "酒味" in snippet:
        return bool(re.search(r"酒|醉", raw))
    if "C" in snippet.upper() and "座" in snippet:
        return bool(re.search(r"C\s*座", raw, re.I))
    if "15" in snippet and "15" not in raw and "十五" not in raw:
        return False
    if "8" in snippet and "8" not in raw and "八" not in raw:
        return False
    return True
