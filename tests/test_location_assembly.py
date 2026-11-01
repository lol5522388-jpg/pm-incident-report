"""地點完整性：樓+位置、座+樓+位置、短答10樓。"""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.gap_policy import LABEL_FLOOR, LABEL_LOCATION, prepare_fields
from app.location_assembly import (
    assemble_location,
    canonical_from_transcript,
    enrich_location_value,
    infer_location_from_text,
    is_bare_spot_location,
)
from app.extract import specific_location
from app.pipeline import Pipeline
from app.store import Store
from app.voice_flow import hear

STAMP = datetime(2026, 10, 22, 18, 0, tzinfo=timezone(timedelta(hours=8)))

LOCATION_FIXTURES = [
    ("C座10樓後樓梯有污水", "C座10樓後樓梯"),
    ("10樓後樓梯滴水", "10樓後樓梯"),
    ("第10層走廊好滑", "10樓走廊"),
    ("A座8樓垃圾房門外有臭味", "A座8樓垃圾房門外"),
    ("10 樓 後樓梯", "10樓後樓梯"),
]


@pytest.mark.parametrize("oral,expected", LOCATION_FIXTURES)
def test_canonical_from_transcript(oral, expected):
    assert canonical_from_transcript(oral) == expected


@pytest.mark.parametrize("oral,expected", LOCATION_FIXTURES)
def test_infer_never_bare_spot_when_floor_in_oral(oral, expected):
    got = infer_location_from_text(oral, specific_location)
    assert got == expected
    assert not is_bare_spot_location(got or "")


def test_enrich_bare_spot_with_floor_in_transcript():
    oral = "剛才10樓後樓梯有污水"
    assert enrich_location_value("後樓梯", oral) == "10樓後樓梯"


def test_prepare_fields_keeps_block():
    state = {
        "transcript": "C座10樓後樓梯滴水，已通知管理處。",
        "fields": {"location": {"value": "後樓梯", "status": "confirmed", "origin": "auto"}},
    }
    prepare_fields(state)
    loc = state["fields"]["location"]["value"]
    assert loc.startswith("C座")
    assert "10樓" in loc
    assert "後樓梯" in loc


def test_assemble_table():
    assert assemble_location(block="A", floor=3, spot="後樓梯") == "A座3樓後樓梯"
    assert assemble_location(floor=10, spot="走廊") == "10樓走廊"


def make_pipe(tmp_path) -> Pipeline:
    return Pipeline(Store(tmp_path / "cases.db"), today=date(2026, 10, 22), now=STAMP, engine="heuristic")


def test_short_10_floor_when_asking_location(tmp_path):
    pipe = make_pipe(tmp_path)
    oral = "而家十點幾，10樓後樓梯有污水溢出，好臭，我圍欄同通知管理處。"
    first = hear(pipe, "loc-10", oral)
    gaps = first["gaps"]
    if LABEL_LOCATION in gaps or LABEL_FLOOR in gaps:
        second = hear(pipe, "loc-10", "10樓")
        loc = pipe.store.get(second["case_id"])["fields"]["location"]["value"]
        assert "10樓" in loc
        assert "後樓梯" in loc
        assert LABEL_LOCATION not in second["gaps"]
        assert LABEL_FLOOR not in second["gaps"]
