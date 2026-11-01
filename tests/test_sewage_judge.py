"""Judge：污水單 PDF 時間、地點、行文、確認流程。"""

from datetime import date, datetime, timedelta, timezone

from app.pipeline import Pipeline
from app.store import Store
from app.voice_flow import hear
from tests.voice_helpers import hear_report

STAMP = datetime(2026, 10, 22, 18, 0, tzinfo=timezone(timedelta(hours=8)))

GREEN_BUBBLE = (
    "約三點四十左右，A座大堂行上8樓，8樓垃圾房門外走廊有污水溢出，地面好臭。"
    "有住戶通知管理處。我已放置告示牌，並用對講通知管理處安排清潔維修。暫時無人受傷，未入垃圾房。單位號碼無涉及。"
)

GREEN_WITH_TODAY = "今天，" + GREEN_BUBBLE


def make_pipe(tmp_path) -> Pipeline:
    return Pipeline(Store(tmp_path / "cases.db"), today=date(2026, 10, 22), now=STAMP, engine="heuristic")


def test_sewage_oral_auto_time_location_date_pdf(tmp_path):
    pipe = make_pipe(tmp_path)
    first = hear(pipe, "sew-judge", GREEN_BUBBLE)
    time_f = pipe.store.get(first["case_id"])["fields"]["time"]
    assert time_f.get("status") == "confirmed"
    assert "15:40" in (time_f.get("value") or "")
    assert "15:00" not in (time_f.get("value") or "")
    assert "12:00" not in (time_f.get("value") or "")
    assert "時間或時段" not in first.get("gaps", [])
    assert "確認時間" not in (first.get("say") or "")
    loc = pipe.store.get(first["case_id"])["fields"]["location"]["value"]
    assert "A座" in loc.replace(" ", "") and "8樓" in loc.replace(" ", "")
    assert first["document"] is not None
    assert "單位號" not in (first.get("gaps") or [])
    formal = pipe.store.get(first["case_id"])["report"]["formal"]
    assert "12:00" not in formal
    assert "15:00" not in formal
    assert "15:40" in formal or "約 15:40" in formal
    assert "A 座 8 樓" in formal
    assert "垃圾房" in formal
    assert "2026-10-22" in formal
    assert "確實單位號" not in formal
    assert "大廈公契" not in formal
    assert "原始口述" not in formal
    assert "我" not in formal.split("目擊事實：")[-1].split("行動：")[0]
    assert len(formal.split("未有記錄：")[-1].split("聲明")[0]) < 80


def test_sewage_today_keyword_sets_event_date(tmp_path):
    pipe = make_pipe(tmp_path)
    done = hear(pipe, "sew-today", GREEN_WITH_TODAY)
    date_f = pipe.store.get(done["case_id"])["fields"]["date"]
    assert date_f.get("status") == "confirmed"
    assert "2026年10月22日" in (date_f.get("value") or "")


def test_sewage_legacy_date_line_still_works(tmp_path):
    pipe = make_pipe(tmp_path)
    first = hear(pipe, "sew-legacy", GREEN_BUBBLE.replace("約三點四十", "約15:40"))
    if first.get("gaps"):
        done = hear_report(pipe, "sew-legacy", "日期 2026-10-22")
    else:
        done = first
    assert done["document"] is not None
    formal = pipe.store.get(done["case_id"])["report"]["formal"]
    assert "A 座 8 樓" in formal
