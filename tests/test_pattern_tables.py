"""date_patterns / followup_merge / asr_normalize 表覆蓋。"""

from datetime import date

import pytest

from app.asr_normalize import normalize_asr, variant_rule_count
from app.date_patterns import pattern_catalog, parse_date_text, strip_date_prefix
from app.followup_merge import apply_followup_merge, pending_field_from_gaps
from app.gap_policy import LABEL_DATE, LABEL_FLOOR
from app.location_assembly import assembly_rule_count
from app.negation_policy import spec_count
from app.extract import explicit_minute_pm_rule_count
from app.pipeline import Pipeline
from app.store import Store
from app.voice_flow import hear

TODAY = date(2026, 10, 22)

DATE_CASES = [
    ("today", "今天", "2026-10-22"),
    ("today_alt", "今日", "2026-10-22"),
    ("yesterday", "尋日", "2026-10-21"),
    ("day_before", "前日", "2026-10-20"),
    ("yyyy", "2026年10月22日", "2026-10-22"),
    ("yy_prefix", "日期係26年10月22号", "2026-10-22"),
    ("yy_bare", "26年10月22号", "2026-10-22"),
    ("md_cn", "10月22日", "2026-10-22"),
    ("slash", "10/22", "2026-10-22"),
    ("dot", "10.22", "2026-10-22"),
    ("iso", "2026-10-22", "2026-10-22"),
]


@pytest.mark.parametrize("name,spoken,iso", DATE_CASES)
def test_date_patterns_table(name, spoken, iso):
    parsed = parse_date_text(spoken, TODAY)
    assert parsed is not None, name
    assert parsed.iso == iso, name


def test_pattern_catalog_covers_table():
    catalog = set(pattern_catalog())
    assert "today" in catalog
    assert "yy_ymd" in catalog
    assert len(catalog) >= 10


def test_followup_date_short_reply_recorded_iso(tmp_path):
    pipe = Pipeline(Store(tmp_path / "c.db"), today=TODAY)
    state = {
        "fields": {},
        "voice": {"pending_field": "date", "gaps": [LABEL_DATE]},
        "transcript": "B座走廊嘈交",
    }
    hints = apply_followup_merge(state, "26年10月22号", TODAY)
    assert hints == ["已記 2026-10-22"]
    assert state["fields"]["date"]["status"] == "confirmed"
    assert state["date_iso"] == "2026-10-22"


def test_pending_field_from_gaps_order():
    assert pending_field_from_gaps([LABEL_FLOOR, LABEL_DATE]) == "date"


def test_location_assembly_rule_table():
    assert assembly_rule_count() >= 7


def test_negation_policy_table():
    assert spec_count() >= 2


def test_cn_explicit_minute_pm_table():
    assert explicit_minute_pm_rule_count() == 6


def test_asr_normalize_table():
    assert "污水" in normalize_asr("污誰溢流")
    assert "A座" in normalize_asr("A做8楼")
    assert variant_rule_count() >= 8


def test_hear_date_short_reply_say(tmp_path):
    pipe = Pipeline(Store(tmp_path / "c.db"), today=TODAY)
    hear(pipe, "d", "B座15樓走廊嘈交，十一點幾，我表明身份勸喻。冇人受傷。")
    second = hear(pipe, "d", "26年10月22号")
    assert "已記 2026-10-22" in second["say"]
    assert "日期" not in second.get("gaps", [])
