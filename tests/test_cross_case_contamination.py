"""跨案污染：先 C15 醉酒嘈交 → 再 A8 污水，第二單不得帶上單殘留。"""

from datetime import date, datetime, timedelta, timezone

from app.pipeline import Pipeline
from app.store import Store
from app.voice_flow import hear
from tests.voice_helpers import hear_report

STAMP = datetime(2026, 10, 22, 18, 0, tzinfo=timezone(timedelta(hours=8)))

CASE1_C15 = (
    "C座15樓走廊，十一點幾，女住戶同對面男嘈交，男有酒味。"
    "我表明身份勸喻，通知控制室。冇人受傷。"
)

SEWAGE_A8 = (
    "約三點四十左右，A座大堂行上8樓，8樓垃圾房門外走廊有污水溢出，地面好臭。"
    "有住戶通知管理處。我已放置告示牌，並用對講通知管理處安排清潔維修。"
    "暫時無人受傷，未入垃圾房。單位號碼無涉及。"
)

FORBIDDEN = ("C 座", "C座", "15 樓", "15樓", "醉酒", "酒味", "12:00", "11:00")
REQUIRED = ("A 座 8", "15:40", "垃圾房", "告示牌", "對講")


def make_pipe(tmp_path) -> Pipeline:
    return Pipeline(Store(tmp_path / "cases.db"), today=date(2026, 10, 22), now=STAMP, engine="heuristic")


def test_two_cases_c15_drunk_then_a8_sewage_isolated(tmp_path):
    pipe = make_pipe(tmp_path)
    first_id = hear_report(pipe, "cross", CASE1_C15, "日期 2026-10-22", "15樓")["case_id"]
    second = hear_report(pipe, "cross", SEWAGE_A8, "日期 2026-10-22")
    assert second["case_id"] != first_id
    blob = (second.get("say") or "") + pipe.store.get(second["case_id"])["report"]["formal"]
    blob += pipe.store.get(second["case_id"])["report"]["summary"]
    for bad in FORBIDDEN:
        assert bad not in blob, f"cross-case leak: {bad}"
    for need in REQUIRED:
        assert need in blob.replace("約 ", ""), f"missing {need}"
    assert "單位號" not in (second.get("gaps") or [])


def test_same_block_a15_noise_then_a8_sewage_starts_fresh(tmp_path):
    """同 A 座先 15 樓嘈交再 8 樓污水 — 必須開新案，唔 merge。"""
    pipe = make_pipe(tmp_path)
    noise = (
        "A座15樓走廊，十一點幾，女住戶同對面男嘈交，男有酒味。"
        "我表明身份勸喻，通知控制室。冇人受傷。"
    )
    id1 = hear_report(pipe, "same-block", noise, "日期 2026-10-22", "15樓")["case_id"]
    r = hear(pipe, "same-block", SEWAGE_A8)
    assert r["case_id"] != id1
    done = hear_report(pipe, "same-block", "日期 2026-10-22")
    formal = pipe.store.get(done["case_id"])["report"]["formal"]
    assert "8 樓" in formal
    assert "15 樓" not in formal
    assert "15:40" in formal or "約 15:40" in formal
    assert "酒" not in formal and "醉酒" not in formal
    assert "12:00" not in formal
