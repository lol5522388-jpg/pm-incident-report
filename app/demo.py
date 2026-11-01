"""跑八條假口述，打印每條停在追問還是已經出稿。"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from app.fixtures import (
    ELEVATOR,
    FALL_COMPLETE,
    FALL_SUBJECTIVE,
    LEAK_COMPLETE,
    LEAK_INCOMPLETE,
    NOISE_COMPLETE,
    NOISE_INCOMPLETE,
    PARKING,
)
from app.pipeline import Pipeline
from app.store import Store


def main() -> None:
    stamp = datetime(2026, 10, 22, 18, 0, tzinfo=timezone(timedelta(hours=8)))
    samples = [
        ("漏水缺時間", LEAK_INCOMPLETE, "text"),
        ("漏水完整", LEAK_COMPLETE, "text"),
        ("跌倒含主觀詞", FALL_SUBJECTIVE, "text"),
        ("跌倒完整", FALL_COMPLETE, "text"),
        ("噪音缺時間", NOISE_INCOMPLETE, "text"),
        ("噪音完整", NOISE_COMPLETE, "text"),
        ("違泊不在本期", PARKING, "text"),
        ("電梯故障", ELEVATOR, "text"),
    ]
    with TemporaryDirectory() as folder:
        pipe = Pipeline(
            Store(Path(folder) / "demo.db"),
            today=date(2026, 10, 22),
            now=stamp,
            engine="heuristic",
        )
        for title, text, source in samples:
            view = pipe.ingest(text, source=source)
            if view["question"]:
                nxt = view["question"]["field"] + "：" + view["question"]["text"][:42]
            else:
                nxt = view["message"][:42]
            print(f"{title} → {view['status']} / {view['event_label']} / {nxt}")
        done = pipe.ingest(ELEVATOR)
        revised = pipe.correct(done["case_id"], "時間改為09:12。補充：按鈕燈為紅色。")
        print(f"電梯修正 → v{revised['version']} / {revised['message']}")


if __name__ == "__main__":
    main()
