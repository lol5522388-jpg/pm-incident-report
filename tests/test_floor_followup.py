"""樓層短答合併回歸。"""

from datetime import date, datetime, timedelta, timezone

from app.gap_policy import LABEL_FLOOR
from app.pipeline import Pipeline
from app.store import Store
from app.voice_flow import hear

STAMP = datetime(2026, 10, 22, 18, 0, tzinfo=timezone(timedelta(hours=8)))

NOISE_B = (
    "B座走廊有人大吵，而家十一點幾，好似十五定十六樓，女住戶同對面單位嘈交。"
    "我表明身份勸喻，通知控制室。冇人受傷。"
)

PATROL_ORAL = (
    "圍威喂，我係大堂巡邏，而家十一點幾，B座由地下行上去，聽到好大聲嘈交同門砰砰。"
    "好似十幾樓，十五定十六我唔敢講死。走廊有水好滑，女住戶同對面男嘈，男有酒味。"
    "我表明身份叫細聲，通知控制室清潔同翻CCTV。冇人受傷，冇入單位。完"
)


def make_pipe(tmp_path) -> Pipeline:
    return Pipeline(Store(tmp_path / "cases.db"), today=date(2026, 10, 22), now=STAMP, engine="heuristic")


def test_b_block_noise_floor_short_answer_clears_gap(tmp_path):
    pipe = make_pipe(tmp_path)
    first = hear(pipe, "floor-b", NOISE_B)
    assert LABEL_FLOOR in first["gaps"]
    second = hear(pipe, "floor-b", "15樓")
    assert LABEL_FLOOR not in second["gaps"]
    assert "樓層（口述未能確定）" not in second["say"]
    assert "已記" in second["say"] and "15" in second["say"]
    loc = pipe.store.get(second["case_id"])["fields"]["location"]["value"]
    assert "15" in loc and "B" in loc.upper()
    floor = pipe.store.get(second["case_id"])["fields"].get("floor") or {}
    assert floor.get("value") == 15
    assert floor.get("note") == "用戶確認"


def test_pure_digit_15_after_floor_gap(tmp_path):
    pipe = make_pipe(tmp_path)
    hear(pipe, "floor-digit", NOISE_B)
    third = hear(pipe, "floor-digit", "15")
    assert LABEL_FLOOR not in third["gaps"]


def test_patrol_oral_first_turn_no_false_check(tmp_path):
    pipe = make_pipe(tmp_path)
    first = hear(pipe, "patrol-oral", PATROL_ORAL)
    assert LABEL_FLOOR in first["gaps"]
    assert "核對有唔啱" not in first["say"]
    assert "15樓" in first["say"] or "15" in first["say"] or "確認樓層" in first["say"]


def test_patrol_oral_15_floor_uses_corridor_not_lobby(tmp_path):
    pipe = make_pipe(tmp_path)
    hear(pipe, "patrol-corridor", PATROL_ORAL)
    second = hear(pipe, "patrol-corridor", "15樓")
    loc = pipe.store.get(second["case_id"])["fields"]["location"]["value"]
    assert "15" in loc
    assert "走廊" in loc
    assert "大堂" not in loc
