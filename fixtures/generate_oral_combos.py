#!/usr/bin/env python3
"""組合 + 隨機維度生成 oral 回歸用例（表驅動變體，非單 case if）。

維度：日期寫法、樓+地點、短答 merge、跨案、作廢清空、主觀詞口述、ASR 近音。
"""
from __future__ import annotations

import argparse
import json
import random
import itertools
from pathlib import Path

OUT = Path(__file__).resolve().parent / "oral_combos.jsonl"
META_OUT = Path(__file__).resolve().parent / "oral_combos_meta.json"

DIMENSIONS = [
    "date_followup_variants",
    "floor_location_spot",
    "floor_short_merge",
    "block_floor_spot",
    "cross_case_isolation",
    "void_session_reset",
    "subjective_oral_rewrite",
    "asr_homophone",
    "time_no_12_00",
    "unit_na_public",
]

TYPES = [
    {
        "id": "noise_dispute",
        "oral": "控制室，我係{block}巡邏。約{time}，行到約{floor}樓{spot}聽到有人喧嘩同拍門聲。女住戶企門口嘈，對面男嘅有酒味應嘴，態度好差。我表明身份叫雙方細聲，之後兩邊入返單位。{spot}有水，未見天花滴。已對講通知控制室安排清潔同翻查閉路。暫時無人受傷，我冇入單位。單位號未睇到。完。",
        "expect_has": ["喧嘩", "對講", "清潔"],
        "expect_missing_never": ["看到的事實"],
        "unit_na": True,
        "followups": [{"user": "{floor_short}", "clears": ["floor", "location"]}],
        "expect_location_floor": False,
    },
    {
        "id": "sewage_refuse",
        "oral": "控制室，我係{block}大堂。約{time}，住戶話{floor}樓垃圾房門口污水好滑。我上樓見到垃圾房門外走廊濕晒，污水由門底滲出。已對講請清潔同維修，門口放咗小心地滑告示。無人報整親。單位號碼無涉及，我冇入垃圾房。完。",
        "expect_has": ["污水", "告示", "清潔"],
        "expect_missing_never": ["單位號", "看到的事實"],
        "unit_na": True,
        "followups": [{"user": "{date_user}", "clears": ["date"]}],
        "expect_location_floor": True,
    },
    {
        "id": "smoking_lobby",
        "oral": "控制室，夜更，約{time}，{block}地下大堂近信箱，一名約二十歲戴帽黑衫男子抽煙，地下有煙灰。我表明身份勸喻，對方踩熄後入電梯，樓層睇唔到。已報翻查閉路。無人唔適，未見火警。完。",
        "expect_has": ["抽煙", "勸喻", "閉路"],
        "expect_missing_never": ["看到的事實"],
        "unit_na": True,
        "followups": [{"user": "{date_user}", "clears": ["date"]}],
        "expect_location_floor": False,
    },
    {
        "id": "lift_trapped",
        "oral": "控制室，約{time}，{block}{floor}樓電梯有住戶報困梯，我到場按對講安撫，已通知控制室召升降機公司同留意閉路。暫時未見受傷。單位唔適用。完。",
        "expect_has": ["困梯", "升降機"],
        "expect_missing_never": ["單位號"],
        "unit_na": True,
        "followups": [],
        "expect_location_floor": True,
    },
    {
        "id": "car_park_scratch",
        "oral": "控制室，約{time}，地庫車場B區，一架白車左後鏡疑刮花，司機男約四十歲報稱停泊後先發現。我拍照、記低車牌{plate}，已對講通知控制室。未見現場撞到其他人。完。",
        "expect_has": ["車場", "車牌", "拍照"],
        "expect_missing_never": ["看到的事實"],
        "unit_na": True,
        "followups": [{"user": "{date_user}", "clears": ["date"]}],
        "expect_location_floor": False,
    },
    {
        "id": "water_seepage_unit",
        "oral": "控制室，約{time}，{block}{floor}樓{unit}室住戶報天花滲水。我到場見客廳天花有水漬同滴水，已通知控制室請維修。暫時用桶盛住。完。",
        "expect_has": ["滲水", "維修"],
        "expect_missing_never": ["看到的事實"],
        "unit_na": False,
        "followups": [],
        "expect_location_floor": True,
    },
    {
        "id": "back_stairs_spill",
        "oral": "控制室，約{time}，{block}{floor}樓{spot}有污水溢出，地面好臭。我已圍欄同對講通知管理處清潔。單位號碼無涉及。冇人受傷。完。",
        "expect_has": ["污水", "對講"],
        "expect_missing_never": ["單位號", "看到的事實"],
        "unit_na": True,
        "followups": [{"user": "{floor_short}", "clears": ["floor", "location"]}],
        "expect_location_floor": True,
    },
]

BLOCKS = ["A座", "B座", "C座", "D座"]
FLOORS = ["8", "10", "12", "15", "16", "22"]
TIMES = ["15:40", "22:30", "00:20", "11:15", "18:05"]
DATES = ["2026-10-22", "2026-10-23"]
UNITS = ["101", "808", "1203"]
PLATES = ["AB1234", "XY9876"]
SPOTS = ["走廊", "後樓梯", "垃圾房門外走廊"]

DATE_FOLLOWUP_VARIANTS = [
    "今天",
    "日期 {date}",
    "日期係{y}年{mo}月{d}号",
    "{y2}年{mo}月{d}号",
    "{mo}/{d}",
    "10.{d}",
    "尋日",
    "10月{d}日",
]

FLOOR_SHORT_VARIANTS = [
    "{floor}樓",
    "第{floor}层",
    "{floor}",
]

# ASR 近音／分詞（表驅動；生成時隨機抽）
ASR_TWEAK_TABLE: list[tuple[str, str]] = [
    ("A座", "A做"),
    ("B座", "B 座"),
    ("C座", "C做"),
    ("8樓", "八 楼"),
    ("10樓", "10 楼"),
    ("15樓", "十 五 楼"),
    ("污水", "污誰"),
    ("垃圾房", "垃极房"),
    ("三點四十", "三 點 四 十"),
    ("15:40", "三點四十"),
    ("22:30", "十點半"),
    ("後樓梯", "后楼梯"),
    ("走廊", "走 廊"),
    ("告示", "告 示 牌"),
    ("好臭", "好 臭"),
]


def fmt(s: str, **kw) -> str:
    return s.format(**kw)


def apply_asr_tweak(rng: random.Random, text: str, intensity: int) -> str:
    out = text
    picks = rng.sample(ASR_TWEAK_TABLE, k=min(intensity, len(ASR_TWEAK_TABLE)))
    for src, dst in picks:
        if src in out:
            out = out.replace(src, dst, 1)
    return out


def base_assert(t: dict) -> dict:
    return {
        "missing_must_not_contain": t["expect_missing_never"],
        "report_or_reply_must_contain": t["expect_has"],
        "unit_na": t["unit_na"],
        "after_followups_must_not_repeat_same_missing": True,
        "must_not_use_time_12_00_unless_input_has_it": True,
        "forbidden_substrings_in_final": [
            "仍欠：單位號",
            "仍欠：看到的事實",
            "仍欠：樓層（口述未能確認）",
            "仍欠：樓層（口述未能確定）",
        ],
        "location_must_include_floor": t.get("expect_location_floor", False),
        "no_bare_spot_if_floor_in_oral": True,
    }


def build_combo_rows(rng: random.Random, count: int) -> list[dict]:
    rows: list[dict] = []
    product = list(itertools.product(TYPES, BLOCKS, FLOORS, TIMES, DATES))
    rng.shuffle(product)
    n = 0
    for t, block, floor, time, date in product:
        if n >= count:
            break
        unit = UNITS[n % len(UNITS)]
        plate = PLATES[n % len(PLATES)]
        spot = SPOTS[n % len(SPOTS)]
        floor_short = fmt(rng.choice(FLOOR_SHORT_VARIANTS), floor=floor)
        y, mo, d = date.split("-")
        y2 = y[2:]
        date_user = fmt(
            rng.choice(DATE_FOLLOWUP_VARIANTS),
            date=date,
            y=y,
            y2=y2,
            mo=int(mo),
            d=int(d),
        )
        oral = fmt(
            t["oral"],
            block=block,
            floor=floor,
            time=time,
            date=date,
            unit=unit,
            plate=plate,
            spot=spot,
        )
        oral = apply_asr_tweak(rng, oral, intensity=1 + (n % 3))
        followups = [
            {
                "user": fmt(
                    f["user"],
                    floor=floor,
                    floor_short=floor_short,
                    date=date,
                    unit=unit,
                    date_user=date_user,
                ),
                "clears": f["clears"],
            }
            for f in t["followups"]
        ]
        if not followups or not any("date" in (f.get("clears") or []) for f in followups):
            if t["id"] not in {"noise_dispute", "back_stairs_spill"}:
                followups.append({"user": date_user, "clears": ["date"]})
        rows.append(
            {
                "id": f"{t['id']}_{n}",
                "type": t["id"],
                "dimensions": [
                    "asr_homophone",
                    "date_followup_variants" if any("date" in (f.get("clears") or []) for f in followups) else "floor_short_merge",
                    "floor_location_spot" if spot else "block_floor_spot",
                ],
                "oral": oral,
                "meta": {
                    "block": block,
                    "floor": floor,
                    "time": time,
                    "date": date,
                    "unit": unit,
                    "spot": spot,
                },
                "followups": followups,
                "assert": base_assert(t),
            }
        )
        n += 1
    return rows


def build_scenario_rows(rng: random.Random, count: int) -> list[dict]:
    rows: list[dict] = []
    i = 0
    while len(rows) < count:
        block = rng.choice(BLOCKS)
        floor = rng.choice(FLOORS)
        time = rng.choice(TIMES)
        date = rng.choice(DATES)
        spot = rng.choice(["後樓梯", "走廊"])
        if i % 2 == 0:
            # 跨案
            rows.append(
                {
                    "id": f"cross_case_{i}",
                "type": "cross_case",
                "dimensions": ["cross_case_isolation", "floor_location_spot", "date_followup_variants"],
                "segments": [
                    {
                        "oral": apply_asr_tweak(
                            rng,
                            f"{block}{floor}樓{spot}，十一點幾，女住戶同對面男嘈交，男有酒味搞事。"
                            "我表明身份勸喻，通知控制室。冇人受傷。",
                            1,
                        ),
                        "followups": [
                            {"user": f"{floor}樓", "clears": ["floor"]},
                            {"user": f"日期 {date}", "clears": ["date"]},
                        ],
                    },
                    {
                        "oral": apply_asr_tweak(
                            rng,
                            "約三點四十左右，A座大堂行上8樓，8樓垃圾房門外走廊有污水溢出，地面好臭。"
                            "有住戶通知管理處。我已放置告示牌，並用對講通知管理處安排清潔維修。"
                            "暫時無人受傷，未入垃圾房。單位號碼無涉及。",
                            1,
                        ),
                        "followups": [{"user": f"日期 {date}", "clears": ["date"]}],
                    },
                ],
                "meta": {"block": block, "floor": floor, "date": date, "segment": "cross"},
                "assert": {
                    **base_assert(TYPES[1]),
                    "location_must_include_floor": False,
                    "final_must_not_contain": (
                        ["酒味", "12:00", "十一點", "十點幾"]
                        + ([f"{floor}樓"] if floor != "8" else [])
                        + ([block] if block != "A座" else [])
                    ),
                    "final_must_contain": ["8樓", "污水", "15:40", "告示"],
                    "new_case_after_segment": 1,
                },
            }
            )
        else:
            rows.append(
                {
                    "id": f"void_reset_{i}",
                    "type": "void_reset",
                    "dimensions": ["void_session_reset", "floor_short_merge"],
                    "segments": [
                        {
                            "oral": f"{block}好似{floor}定{int(floor)+1}樓{rng.choice(SPOTS)}有人嘈交，十一點幾。",
                            "followups": [{"user": rng.choice(["作廢", "取消"]), "clears": ["void"]}],
                        },
                        {
                            "oral": apply_asr_tweak(
                                rng,
                                f"控制室，約{time}，{block}{floor}樓垃圾房門外走廊有污水，"
                                "已對講通知清潔。單位號碼無涉及。冇人受傷。完。",
                                1,
                            ),
                            "followups": [{"user": f"日期 {date}", "clears": ["date"]}],
                        },
                    ],
                    "meta": {"block": block, "floor": floor, "date": date},
                    "assert": {
                        **base_assert(TYPES[1]),
                        "void_no_leak": [f"{floor}定"],
                        "location_must_include_floor": True,
                    },
                }
            )
        i += 1
    return rows[:count]


def generate(*, seed: int, count: int) -> list[dict]:
    rng = random.Random(seed)
    scenario_n = max(60, count // 8)
    combo_n = count - scenario_n
    rows = build_combo_rows(rng, combo_n)
    rows.extend(build_scenario_rows(rng, scenario_n))
    rng.shuffle(rows)
    for idx, row in enumerate(rows):
        row["id"] = row.get("id") or f"case_{idx}"
        row.setdefault("seed", seed)
    return rows


def write_fixtures(rows: list[dict], out: Path = OUT) -> None:
    with out.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    meta = {
        "count": len(rows),
        "dimensions": DIMENSIONS,
        "types": sorted({r["type"] for r in rows}),
        "seed": rows[0].get("seed") if rows else None,
    }
    META_OUT.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(rows)} cases -> {out}")
    print(f"meta -> {META_OUT}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate oral_combos.jsonl with random dimensions")
    parser.add_argument("--seed", type=int, default=20261022)
    parser.add_argument("--count", type=int, default=1200)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    rows = generate(seed=args.seed, count=args.count)
    write_fixtures(rows, args.out)


if __name__ == "__main__":
    main()
