"""對話 UX：第二轉短回覆、時間地點 NLP 合併。"""

from datetime import date, datetime, timedelta, timezone

from app.pipeline import Pipeline
from app.store import Store
from app.voice_flow import hear
from tests.voice_helpers import hear_report

STAMP = datetime(2026, 10, 22, 18, 0, tzinfo=timezone(timedelta(hours=8)))

OPEN = (
    "B座走廊有人大吵，而家十一點幾，好似十五定十六樓，女住戶同對面單位嘈交。"
    "我表明身份勸喻，通知控制室。冇人受傷。"
)

FILL = "今日10:15接通知，10:20到場，10:30完結離開。10樓101室。"


def make_pipe(tmp_path) -> Pipeline:
    return Pipeline(Store(tmp_path / "cases.db"), today=date(2026, 10, 22), now=STAMP, engine="heuristic")


def test_first_turn_is_short_numbered_gaps(tmp_path):
    pipe = make_pipe(tmp_path)
    first = hear(pipe, "ux-1", OPEN)
    assert first["complete"] is False
    assert first["say"].count("\n") <= 4
    assert "仍缺：" in first["say"]
    assert "1." in first["say"]
    assert "已收到：" not in first["say"]


def test_second_turn_absorbs_time_place_without_wall_text(tmp_path):
    pipe = make_pipe(tmp_path)
    hear(pipe, "ux-2", OPEN)
    second = hear_report(pipe, "ux-2", FILL)
    assert "已收到：" not in second["say"]
    assert "已記：" in second["say"] or "【物管事件報告" in second["say"]
    assert "10:15" in second["say"] or "10:15–10:30" in second["say"]
    assert "時間或時段" not in second.get("gaps", [])
    assert "樓層（口述未能確定）" not in second.get("gaps", [])
    if second["complete"]:
        assert second["document"] is not None
        assert "【物管事件報告" in pipe.store.get(second["case_id"])["report"]["formal"]
        assert "【核對稿】" not in second["say"]
