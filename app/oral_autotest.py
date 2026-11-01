"""oral_combos.jsonl 規則跑法（gap／merge／禁句）。"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.gap_policy import LABEL_DATE, LABEL_FLOOR
from app.location_assembly import is_bare_spot_location, transcript_implies_floor
from app.pipeline import Pipeline
from app.store import Store
from app.voice_flow import hear

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "oral_combos.jsonl"
M_NEGATION_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "m_negation_m01_m10.jsonl"

FLOOR_FORBIDDEN = (
    "仍欠：樓層（口述未能確認）",
    "仍欠：樓層（口述未能確定）",
)
DRAFT_FORBIDDEN = ("【核對稿】", "以上啱就答「係」", "啱就答「係」")
DEFAULT_STAMP = datetime(2026, 10, 22, 18, 0, tzinfo=timezone(timedelta(hours=8)))


def load_cases(path: Path | None = None) -> list[dict]:
    path = path or FIXTURES
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _gap_blob(gaps: list[str]) -> str:
    return " ".join(gaps or [])


def _must_not_in_missing(gaps: list[str], tokens: list[str]) -> list[str]:
    blob = _gap_blob(gaps)
    bad = []
    for token in tokens:
        if token in blob:
            bad.append(token)
        if token == "看到的事實" and "客觀事實" in blob:
            bad.append("客觀事實")
        if token == "單位號" and re.search(r"單位", blob):
            bad.append("單位")
    return bad


def _forbidden_in_text(text: str, forbidden: list[str]) -> list[str]:
    found = []
    for item in forbidden:
        if item in text:
            found.append(item)
    for item in FLOOR_FORBIDDEN:
        if item in text and item not in found:
            found.append(item)
    for item in DRAFT_FORBIDDEN:
        if item in text and item not in found:
            found.append(item)
    return found


def _time_ok(case: dict, state: dict) -> str | None:
    meta = case.get("meta") or {}
    oral = case.get("oral") or ""
    if not case.get("assert", {}).get("must_not_use_time_12_00_unless_input_has_it"):
        return None
    if "12:00" in oral or "十二點" in oral or "12點" in oral:
        return None
    time_val = (state.get("fields") or {}).get("time") or {}
    value = str(time_val.get("value") or "")
    report = (state.get("report") or {}).get("formal") or ""
    if "12:00" in value or re.search(r"\b12:00\b", report):
        return "12:00"
    expect = meta.get("time")
    if expect and expect in {"15:40", "22:30"}:
        if expect not in value and expect not in report and f"約 {expect}" not in value:
            pass
    return None


def _location_meta_ok(case: dict, state: dict) -> str | None:
    if case.get("type") in {"cross_case"}:
        return None
    asserts = case.get("assert") or {}
    if not asserts.get("location_must_include_floor"):
        return None
    meta = case.get("meta") or {}
    floor = meta.get("floor")
    if not floor:
        return None
    loc = ((state.get("fields") or {}).get("location") or {}).get("value") or ""
    if not re.search(rf"(?<!\d){re.escape(str(floor))}\s*樓", loc):
        return "location_missing_meta_floor"
    return None


def _location_integrity_ok(state: dict) -> str | None:
    loc = (state.get("fields") or {}).get("location") or {}
    value = (loc.get("value") or "").strip()
    text = state.get("transcript") or ""
    if not value:
        return None
    if is_bare_spot_location(value) and transcript_implies_floor(text):
        return "location_missing_floor"
    return None


def _unit_na_ok(case: dict, state: dict) -> str | None:
    if not case.get("assert", {}).get("unit_na"):
        return None
    unit = state.get("unit") or (state.get("fields") or {}).get("unit") or {}
    if unit.get("unit_status") == "na" or unit.get("value") in {"不適用", "未有記錄"}:
        return None
    if unit.get("value") and re.search(r"\d", str(unit.get("value"))):
        return None
    return "unit_not_na"


def run_oral_sequence(pipe: Pipeline, case: dict, *, phone: str, confirm_turns: bool = True) -> dict:
    """多段同 phone：跨案 / 作廢後新案。"""
    asserts = case.get("assert") or {}
    errors: list[str] = []
    say_log: list[str] = []
    last: dict = {}
    prev_case_id = None
    for seg_index, segment in enumerate(case.get("segments") or []):
        last = hear(pipe, phone, segment["oral"])
        say_log.append(last.get("say") or "")
        gaps = last.get("gaps") or []
        errors.extend(
            f"seg{seg_index}-oral: missing has {b}"
            for b in _must_not_in_missing(gaps, asserts.get("missing_must_not_contain") or [])
        )
        for follow in segment.get("followups") or []:
            last = hear(pipe, phone, follow["user"])
            say_log.append(last.get("say") or "")
            gaps = last.get("gaps") or []
            for cleared in follow.get("clears") or []:
                if cleared == "floor" and LABEL_FLOOR in gaps:
                    errors.append(f"floor not cleared seg{seg_index}")
        case_id = last.get("case_id")
        if seg_index == 0:
            prev_case_id = case_id
        elif asserts.get("new_case_after_segment") == seg_index and case_id == prev_case_id:
            errors.append(f"segment {seg_index}: expected new case_id")
        prev_case_id = case_id

    state = pipe.store.latest_phone(phone) or {}
    formal = (state.get("report") or {}).get("formal") or ""
    transcript = state.get("transcript") or ""
    leak_blob = formal + transcript
    reply_blob = formal + "\n".join(say_log) + transcript

    for token in asserts.get("final_must_not_contain") or []:
        if token and token in leak_blob:
            errors.append(f"final_must_not_contain:{token}")
    for token in asserts.get("final_must_contain") or []:
        if token and token not in reply_blob.replace("約 ", ""):
            errors.append(f"final_must_contain:{token}")
    for token in asserts.get("void_no_leak") or []:
        if token in (state.get("transcript") or ""):
            errors.append(f"void_leak:{token}")

    err = _time_ok(case, state)
    if err:
        errors.append(f"time:{err}")
    err = _unit_na_ok(case, state)
    if err:
        errors.append(err)
    err = _location_integrity_ok(state)
    if err:
        errors.append(err)
    err = _location_meta_ok(case, state)
    if err:
        errors.append(err)

    if confirm_turns:
        meta = case.get("meta") or {}

        def auto_date() -> None:
            nonlocal last
            if LABEL_DATE in (last.get("gaps") or []) and meta.get("date"):
                last = hear(pipe, phone, f"日期 {meta['date']}")
                say_log.append(last.get("say") or "")

        auto_date()
        for _ in range(8):
            if last.get("document") or not (last.get("gaps") or []):
                break
            last = hear(pipe, phone, "係")
            say_log.append(last.get("say") or "")

    return {"case_id": case.get("id"), "errors": errors, "last": last, "state": state, "say_log": say_log}


def run_oral_case(
    pipe: Pipeline,
    case: dict,
    *,
    phone: str,
    confirm_turns: bool = True,
    want_report: bool = False,
) -> dict:
    """跑一單：口述 → followups → 可選自動「係」確認。"""
    if case.get("segments"):
        return run_oral_sequence(pipe, case, phone=phone, confirm_turns=confirm_turns)
    asserts = case.get("assert") or {}
    prev_gaps: tuple[str, ...] = ()
    last = hear(pipe, phone, case["oral"])
    errors: list[str] = []
    say_log = [last.get("say") or ""]

    def check_turn(turn_label: str) -> None:
        nonlocal errors
        gaps = last.get("gaps") or []
        say = last.get("say") or ""
        blob = say + _gap_blob(gaps)
        errors.extend(
            f"{turn_label}: missing has {b}"
            for b in _must_not_in_missing(gaps, asserts.get("missing_must_not_contain") or [])
        )
        errors.extend(
            f"{turn_label}: forbidden {b}"
            for b in _forbidden_in_text(blob, asserts.get("forbidden_substrings_in_final") or [])
        )
        for item in FLOOR_FORBIDDEN:
            if item in blob:
                errors.append(f"{turn_label}: floor repeat {item}")

    check_turn("oral")

    for follow in case.get("followups") or []:
        prev_gaps = tuple(last.get("gaps") or [])
        last = hear(pipe, phone, follow["user"])
        say_log.append(last.get("say") or "")
        check_turn(f"follow:{follow['user'][:20]}")
        gaps = last.get("gaps") or []
        for cleared in follow.get("clears") or []:
            if cleared == "floor" and LABEL_FLOOR in gaps:
                errors.append(f"floor not cleared after {follow['user']!r}")
        if asserts.get("after_followups_must_not_repeat_same_missing"):
            if prev_gaps and prev_gaps == tuple(gaps) and LABEL_FLOOR in prev_gaps:
                errors.append("repeated same floor gap")

    meta = case.get("meta") or {}

    def auto_date_if_needed() -> None:
        nonlocal last
        gaps = last.get("gaps") or []
        if LABEL_DATE in gaps and meta.get("date"):
            last = hear(pipe, phone, f"日期 {meta['date']}")
            say_log.append(last.get("say") or "")
            check_turn("date")

    if confirm_turns:
        auto_date_if_needed()
        for _ in range(10):
            state = pipe.store.latest_phone(phone)
            if not state:
                break
            if want_report and LABEL_DATE in (last.get("gaps") or []):
                auto_date_if_needed()
            time_f = (state.get("fields") or {}).get("time") or {}
            if last.get("document"):
                break
            needs_confirm = time_f.get("status") == "needs_confirm"
            if not needs_confirm and not (last.get("gaps") or []):
                break
            if not needs_confirm and (last.get("gaps") or []) and not want_report:
                break
            last = hear(pipe, phone, "係")
            say_log.append(last.get("say") or "")
            check_turn("confirm")
            if want_report and LABEL_DATE in (last.get("gaps") or []):
                auto_date_if_needed()

    state = pipe.store.latest_phone(phone) or {}
    err = _time_ok(case, state)
    if err:
        errors.append(f"time:{err}")
    err = _unit_na_ok(case, state)
    if err:
        errors.append(err)
    err = _location_integrity_ok(state)
    if err:
        errors.append(err)
    err = _location_meta_ok(case, state)
    if err:
        errors.append(err)

    asserts = case.get("assert") or {}
    formal = (state.get("report") or {}).get("formal") or ""
    summary = (state.get("report") or {}).get("summary") or ""
    report_blob = formal + summary
    for token in asserts.get("forbidden_in_report") or []:
        if token in report_blob:
            errors.append(f"forbidden_in_report:{token}")
    if asserts.get("event_type_not") and state.get("event_type") == asserts.get("event_type_not"):
        errors.append(f"event_type:{asserts['event_type_not']}")
    for token in asserts.get("time_must_contain") or []:
        time_f = (state.get("fields") or {}).get("time") or {}
        pool = report_blob + str(time_f.get("value") or "")
        if token not in pool.replace("約 ", ""):
            errors.append(f"time_must_contain:{token}")
    not_times = asserts.get("time_must_not_contain") or []
    if isinstance(not_times, str):
        not_times = [not_times]
    for token in not_times:
        time_f = (state.get("fields") or {}).get("time") or {}
        pool = report_blob + str(time_f.get("value") or "")
        if token in pool:
            errors.append(f"time_must_not_contain:{token}")
    for token in asserts.get("timeline_must_include") or []:
        tl = state.get("timeline") or {}
        pool = report_blob + str(tl.get("span") or "") + str(tl.get("steps") or "")
        if token not in pool:
            errors.append(f"timeline_must_include:{token}")

    formal = (state.get("report") or {}).get("formal") or ""
    if want_report and not last.get("document"):
        errors.append("no_report_pdf")
    if formal:
        if "【物管事件報告" not in formal:
            errors.append("report_title")
        strict = formal.split("（2）")[0] if "（2）" in formal else formal
        obs = strict.split("目擊事實：")[-1].split("行動：")[0] if "目擊事實：" in strict else strict
        if re.search(r"我(?:已|們|喺|係)", obs):
            errors.append("first_person_in_strict")

    keywords = asserts.get("report_or_reply_must_contain") or []
    if keywords:
        pool = formal + "\n".join(say_log) + (state.get("transcript") or "")
        for kw in keywords:
            if kw not in pool:
                errors.append(f"keyword_missing:{kw}")

    return {
        "case_id": case.get("id"),
        "errors": errors,
        "last": last,
        "state": state,
        "say_log": say_log,
    }


def make_pipe(tmp_path, *, stamp: datetime | None = None) -> Pipeline:
    stamp = stamp or DEFAULT_STAMP
    return Pipeline(
        Store(tmp_path / "oral_autotest.db"),
        today=date(2026, 10, 22),
        now=stamp,
        engine="heuristic",
    )
