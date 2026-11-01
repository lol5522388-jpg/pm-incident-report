"""確認狀態機：齊必填直接出報告；「係」確認時間後出全文；禁【核對稿】。"""

from datetime import date, datetime, timedelta, timezone

from app.pipeline import Pipeline
from app.store import Store
from app.voice_flow import hear
from tests.fixtures_golden_patrol import PATROL_INPUT, PATROL_SUPPLEMENT
from tests.voice_helpers import hear_report

STAMP = datetime(2026, 10, 22, 18, 0, tzinfo=timezone(timedelta(hours=8)))

DRAFT_BANNED = ("【核對稿】", "啱就答「係」", "以上啱就答")


def make_pipe(tmp_path) -> Pipeline:
    return Pipeline(Store(tmp_path / "cases.db"), today=date(2026, 10, 22), now=STAMP, engine="heuristic")


def test_yes_after_vague_time_emits_full_report_not_draft(tmp_path):
    pipe = make_pipe(tmp_path)
    hear(pipe, "sm", PATROL_INPUT)
    hear(pipe, "sm", "日期 2026-10-22")
    hear(pipe, "sm", "15樓")
    confirmed = hear(pipe, "sm", "哦係呀")
    for bad in DRAFT_BANNED:
        assert bad not in (confirmed.get("say") or "")
    assert "【物管事件報告" in confirmed["say"]
    assert "（2）摘要版" in confirmed["say"]
    assert confirmed["document"] is not None


def test_complete_supplement_auto_ships_report(tmp_path):
    pipe = make_pipe(tmp_path)
    hear(pipe, "gp", PATROL_INPUT)
    done = hear_report(pipe, "gp", PATROL_SUPPLEMENT)
    assert done["complete"] is True
    for bad in DRAFT_BANNED:
        assert bad not in (done.get("say") or "")
    assert "【物管事件報告" in done["say"]
