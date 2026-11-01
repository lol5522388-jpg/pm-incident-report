"""Golden：大堂巡邏口述 → 追問 → 補料 → 物管報告版面。"""

from datetime import date, datetime, timedelta, timezone

from app.pipeline import Pipeline
from app.store import Store
from app.voice_flow import hear
from tests.voice_helpers import hear_report
from tests.fixtures_golden_patrol import (
    GOLDEN_PATROL_REPORT,
    GOLDEN_PATROL_SUMMARY,
    PATROL_INPUT,
    PATROL_SUPPLEMENT,
)

STAMP = datetime(2026, 10, 22, 18, 0, tzinfo=timezone(timedelta(hours=8)))

FORBIDDEN = (
    "原始口述",
    "整理方式",
    "大廈公契",
    "第314章",
    "第400章",
    "來源聲明：",
    "不提供法律意見",
)


def make_pipe(tmp_path) -> Pipeline:
    return Pipeline(Store(tmp_path / "cases.db"), today=date(2026, 10, 22), now=STAMP, engine="heuristic")


def test_patrol_input_asks_before_pdf(tmp_path):
    pipe = make_pipe(tmp_path)
    first = hear(pipe, "golden-patrol", PATROL_INPUT)
    assert first["complete"] is False
    assert first["document"] is None
    assert "日期" in first["gaps"]
    assert "時間或時段" in first["gaps"]
    assert "樓層（口述未能確定）" in first["gaps"]
    assert "單位號" not in first["gaps"]
    assert "仍缺：" in first["say"]
    assert first["say"].count("\n") <= 4


def test_patrol_golden_report_after_supplement(tmp_path):
    pipe = make_pipe(tmp_path)
    hear(pipe, "golden-patrol", PATROL_INPUT)
    done = hear_report(pipe, "golden-patrol", PATROL_SUPPLEMENT)
    assert done["complete"] is True
    assert done["document"] is not None
    report = pipe.store.get(done["case_id"])["report"]
    formal = report["formal"]
    summary = report["summary"]
    assert formal == GOLDEN_PATROL_REPORT
    assert summary == GOLDEN_PATROL_SUMMARY
    blob = formal + "\n" + summary
    for bad in FORBIDDEN:
        assert bad not in blob
