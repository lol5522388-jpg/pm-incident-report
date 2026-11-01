"""Judge：C 座地下抽煙 + 補日期須出報告，唔再錯缺目擊／單位。"""

from datetime import date, datetime, timedelta, timezone

from app.pipeline import Pipeline
from app.store import Store
from app.voice_flow import hear
from tests.voice_helpers import hear_report

STAMP = datetime(2026, 10, 22, 18, 0, tzinfo=timezone(timedelta(hours=8)))

SMOKING = (
    "10點20分，C座地下有男子抽煙，見到煙灰。我表明身份勸喻，之後佢入電梯離開。"
    "我已通知控制室翻查閉路。單位我睇唔到幾樓。"
)

DATE_LINE = "日期今日 2026-10-22"


def make_pipe(tmp_path) -> Pipeline:
    return Pipeline(Store(tmp_path / "cases.db"), today=date(2026, 10, 22), now=STAMP, engine="heuristic")


def test_smoking_plus_date_issues_report_without_false_gaps(tmp_path):
    pipe = make_pipe(tmp_path)
    first = hear(pipe, "smoke-judge", SMOKING)
    assert first["complete"] is False
    assert "客觀事實" not in first["gaps"]
    assert "單位" not in " ".join(first["gaps"])
    second = hear_report(pipe, "smoke-judge", DATE_LINE)
    assert second["complete"] is True
    assert second["document"] is not None
    assert "客觀事實" not in second["gaps"]
    assert "單位" not in " ".join(second["gaps"])
    assert "供轉發核對" in second["say"] or second["document"]["kind"] == "report"
    formal = pipe.store.get(second["case_id"])["report"]["formal"]
    assert "【物管事件報告" in formal
    assert "抽煙" in formal or "煙灰" in formal
    unit = pipe.store.get(second["case_id"])["fields"].get("unit") or {}
    assert unit.get("value") == "不適用"
    assert unit.get("status") == "confirmed"
