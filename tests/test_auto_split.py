"""自動分案：短答 merge、衝突新案、作廢清空。"""

from datetime import date, datetime, timedelta, timezone

from app.pipeline import Pipeline
from app.store import Store
from app.session_policy import assess_case_split, is_session_control
from app.voice_flow import hear
from tests.test_cross_case_contamination import (
    CASE1_C15,
    FORBIDDEN,
    REQUIRED,
    SEWAGE_A8,
    make_pipe,
)
from tests.voice_helpers import hear_report

STAMP = datetime(2026, 10, 22, 18, 0, tzinfo=timezone(timedelta(hours=8)))


def test_short_answers_stay_merge():
    state = {"status": "incomplete", "transcript": "B座", "fields": {}}
    assert is_session_control("15樓")
    assert is_session_control("15")
    assert is_session_control("日期 2026-10-22")
    assert assess_case_split(state, "15樓") == "merge"


def test_void_then_sewage_no_old_fields(tmp_path):
    pipe = make_pipe(tmp_path)
    hear(pipe, "void-user", CASE1_C15)
    void = hear(pipe, "void-user", "作廢")
    assert "作廢" in void["say"]
    done = hear_report(pipe, "void-user", SEWAGE_A8, "日期 2026-10-22")
    assert done["complete"] is True
    blob = done["say"] + pipe.store.get(done["case_id"])["report"]["formal"]
    for bad in FORBIDDEN:
        assert bad not in blob, bad
    for need in REQUIRED:
        assert need in blob.replace("約 ", ""), need
    assert "C座" not in pipe.store.get(done["case_id"])["transcript"]


def test_c15_drunk_then_a8_auto_fresh(tmp_path):
    pipe = make_pipe(tmp_path)
    first = hear_report(pipe, "auto", CASE1_C15, "日期 2026-10-22", "15樓")
    second = hear_report(pipe, "auto", SEWAGE_A8, "日期 2026-10-22")
    assert second["case_id"] != first["case_id"]
    st = pipe.store.get(second["case_id"])
    assert "酒" not in st["transcript"]
    formal = st["report"]["formal"]
    for bad in FORBIDDEN:
        assert bad not in formal
