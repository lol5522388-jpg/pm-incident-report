"""M01–M10：否定反轉、錯案型、時間、時間軸。"""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.extract import _clock, classify
from app.negation_policy import fall_asserted, forbidden_fact_substrings
from app.pipeline import Pipeline
from app.store import Store
from app.timeline import parse_timeline_loose
from app.voice_flow import hear
from tests.voice_helpers import hear_report

STAMP = datetime(2026, 10, 23, 18, 0, tzinfo=timezone(timedelta(hours=8)))
TODAY = date(2026, 10, 23)


def make_pipe(tmp_path) -> Pipeline:
    return Pipeline(Store(tmp_path / "m.db"), today=TODAY, now=STAMP, engine="heuristic")


M_ORALS = {
    "M01": (
        "約三點四十，A座8樓垃圾房門外走廊污水好滑，地好滑。冇人跌倒，冇人受傷。"
        "我已放告示同對講通知清潔。單位號碼無涉及。"
    ),
    "M02": "今日八點二十，B座10樓後樓梯有滴水，已通知管理處。冇人受傷。",
    "M03": (
        "今日15:00據報A座8樓有污水，14:00到場見垃圾房門外濕滑。"
        "已圍欄及對講通知清潔。單位號碼無涉及。冇人跌倒。"
    ),
    "M04": "約15:40，C座12樓走廊地面好滑，有污水。未有受傷記錄，冇人跌倒。已對講通知清潔。單位號碼無涉及。冇人受傷。",
    "M05": "約三點四十，A座8樓垃圾房污水溢出，地面濕滑，暫時無人跌倒。已對講通知維修。單位號碼無涉及。冇人受傷。",
    "M06": "B座15樓後樓梯，十一點幾，未見有人跌倒，未見有人受傷。已通知控制室。冇人受傷。",
    "M07": "約三點四十，聽到有人講跌倒，但我到場確認冇人跌倒，只係地滑。A座8樓走廊污水。已放告示。單位號碼無涉及。已對講通知清潔。",
    "M08": "約三點四十，A座8樓污水。冇人受傷。已通知清潔。",
    "M09": (
        "15:00據報A座15樓走廊嘈交，14:00到場見B座8樓垃圾房門口有水漬。"
        "兩單分開跟進。8樓已通知清潔。冇人受傷。"
    ),
    "M10": "約三點四十，A做8楼垃圾房污水，地好滑，冇人跌倒。單位號碼無涉及。已對講通知清潔。冇人受傷。",
}


@pytest.mark.parametrize("case_id", [f"M{i:02d}" for i in range(1, 11)])
def test_m_case_no_false_fall_injury_label(tmp_path, case_id):
    oral = M_ORALS[case_id]
    assert not fall_asserted(oral), case_id
    assert classify(oral) != "fall_injury", case_id
    pipe = make_pipe(tmp_path)
    view = hear_report(pipe, case_id, oral, f"日期 {TODAY.isoformat()}")
    formal = pipe.store.get(view["case_id"])["report"]["formal"]
    summary = pipe.store.get(view["case_id"])["report"]["summary"]
    blob = formal + summary + (view.get("say") or "")
    for bad in forbidden_fact_substrings(oral):
        assert bad not in blob, f"{case_id} must not assert {bad!r}"
    assert "跌倒受傷" not in blob.replace("未有人跌倒", ""), case_id
    assert (pipe.store.get(view["case_id"]).get("event_type") or "") != "fall_injury"


def test_m01_negation_phrase_allowed(tmp_path):
    pipe = make_pipe(tmp_path)
    view = hear_report(pipe, "M01-only", M_ORALS["M01"], f"日期 {TODAY.isoformat()}")
    blob = view["say"] + pipe.store.get(view["case_id"])["report"]["formal"]
    assert any(x in blob for x in ("未有人跌倒", "未有受傷", "未見有人受傷", "未有受傷記錄"))


def test_m02_eight_twenty_is_0820_not_vague_hour():
    clock = _clock(M_ORALS["M02"])
    val = clock.get("value") or ""
    assert "08:20" in val.replace("約 ", "")
    assert "08:00" not in val
    assert clock.get("status") != "needs_confirm" or "20" in val


def test_m03_timeline_report_vs_arrival():
    tl = parse_timeline_loose(M_ORALS["M03"])
    assert tl is not None
    times = [s["time"] for s in tl["steps"]]
    assert "14:00" in times and "15:00" in times
    assert tl["start"] == "14:00" and tl["end"] == "15:00"


def test_m08_no_1200(tmp_path):
    pipe = make_pipe(tmp_path)
    view = hear_report(pipe, "M08", M_ORALS["M08"], f"日期 {TODAY.isoformat()}")
    st = pipe.store.get(view["case_id"])
    formal = st["report"]["formal"]
    time_val = (st.get("fields") or {}).get("time") or {}
    assert "12:00" not in formal
    assert "12:00" not in str(time_val.get("value") or "")
    tv = str(time_val.get("value") or "")
    assert "03:40" in formal or "15:40" in formal or "03:40" in tv or "15:40" in tv