"""通用缺口政策自測。"""

from datetime import date, datetime, timedelta, timezone

from app.pipeline import Pipeline
from app.store import Store
from app.voice_flow import hear
from tests.voice_helpers import hear_report

STAMP = datetime(2026, 10, 22, 18, 0, tzinfo=timezone(timedelta(hours=8)))

SEWAGE = (
    "10點許多，垃圾房對出污水溢流，好臭。我圍欄並通知管理處跟進。"
)

SEWAGE_A8 = (
    "10點20分，A座8樓垃圾房有污水溢出，地面好臭。已通知管理處跟進，無涉及單位。"
)

DATE = "日期今日 2026-10-22"

# 截圖綠泡：A座大堂、約15:40、8樓垃圾房污水、告示牌、清潔維修、單位號碼無涉及
SCREENSHOT_SEWAGE = (
    "約15:40，A座大堂行上8樓，8樓垃圾房門外走廊有污水溢出，地面好臭。"
    "我已放置告示牌，並通知管理處安排清潔維修。單位號碼無涉及。"
)
DATE_ISO = "日期 2026-10-22"


def make_pipe(tmp_path) -> Pipeline:
    return Pipeline(Store(tmp_path / "cases.db"), today=date(2026, 10, 22), now=STAMP, engine="heuristic")


def test_public_sewage_plus_date_no_unit_gap(tmp_path):
    pipe = make_pipe(tmp_path)
    done = hear_report(pipe, "sewage", SEWAGE, DATE)
    assert done["complete"] is True
    assert done["document"] is not None
    assert "仍欠：單位號" not in done["say"]
    assert "單位號" not in (done.get("gaps") or [])
    formal = pipe.store.get(done["case_id"])["report"]["formal"]
    assert "【物管事件報告" in formal


def test_a8_garbage_sewage_plus_today_must_not_ask_unit(tmp_path):
    pipe = make_pipe(tmp_path)
    done = hear_report(pipe, "sewage-a8", SEWAGE_A8, DATE)
    assert done["complete"] is True
    assert done["document"] is not None
    assert "仍欠：單位號" not in done["say"]
    assert "單位號" not in (done.get("gaps") or [])
    unit = pipe.store.get(done["case_id"])["fields"].get("unit") or {}
    assert unit.get("value") == "不適用"
    assert unit.get("status") == "confirmed"


def test_screenshot_green_bubble_sewage_plus_date_no_unit_gap(tmp_path):
    pipe = make_pipe(tmp_path)
    done = hear_report(pipe, "screenshot-sewage", SCREENSHOT_SEWAGE, DATE_ISO)
    assert done["complete"] is True
    assert done["document"] is not None
    assert "仍欠：單位號" not in done["say"]
    assert "仍欠" not in done["say"] or "單位" not in done["say"]
    formal = pipe.store.get(done["case_id"])["report"]["formal"]
    assert "【物管事件報告" in formal
    unit = pipe.store.get(done["case_id"])["fields"].get("unit") or {}
    assert unit.get("unit_status") == "na"
    loc = pipe.store.get(done["case_id"])["fields"]["location"]["value"]
    assert "垃圾房" in loc
