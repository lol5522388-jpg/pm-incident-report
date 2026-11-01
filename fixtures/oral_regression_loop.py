#!/usr/bin/env python3
"""生成 → 跑 oral 規則 → 失敗寫 fixtures → 退出碼。

連續兩輪全綠：python fixtures/oral_regression_loop.py --consecutive 2
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fixtures.generate_oral_combos import generate, write_fixtures  # noqa: E402
from app.oral_autotest import FIXTURES, load_cases, make_pipe, run_oral_case  # noqa: E402

FAIL_DIR = Path(__file__).resolve().parent / "oral_failures"
PINNED = Path(__file__).resolve().parent / "oral_regression_pinned.jsonl"


def run_all(path: Path | None = None) -> tuple[int, list[dict]]:
    cases = load_cases(path)
    base = Path(tempfile.mkdtemp(prefix="oral_loop_"))
    pipe = make_pipe(base)
    failures: list[dict] = []
    for index, case in enumerate(cases):
        phone = f"loop{index:05d}"
        result = run_oral_case(pipe, case, phone=phone, confirm_turns=True, want_report=False)
        if result["errors"]:
            failures.append(
                {
                    "id": case.get("id"),
                    "type": case.get("type"),
                    "dimensions": case.get("dimensions"),
                    "errors": result["errors"],
                    "case": case,
                }
            )
    return len(cases), failures


def write_failures(failures: list[dict], *, seed: int, round_no: int) -> Path:
    FAIL_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d_%H%M%S")
    path = FAIL_DIR / f"failures_seed{seed}_r{round_no}_{stamp}.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for item in failures:
            slim = {k: item[k] for k in ("id", "type", "dimensions", "errors") if k in item}
            handle.write(json.dumps(slim, ensure_ascii=False) + "\n")
    if failures:
        with PINNED.open("a", encoding="utf-8") as pinned:
            for item in failures[:50]:
                pinned.write(json.dumps(item.get("case") or item, ensure_ascii=False) + "\n")
    return path


def print_report(*, total: int, failures: list[dict], seed: int, round_no: int, green: bool) -> None:
    print("\n【匯報｜oral 隨機回歸】")
    print(f"  輪次: {round_no}  seed: {seed}")
    print(f"  覆蓋維度: date寫法、樓+地點、短答merge、跨案、作廢、主觀詞、ASR近音、禁12:00、地點完整性")
    print(f"  總用例: {total}")
    print(f"  失敗: {len(failures)}")
    print("  重跑:")
    print(f"    python fixtures/generate_oral_combos.py --seed {seed} --count {total}")
    print("    python fixtures/oral_regression_loop.py --consecutive 2")
    print("    python -m pytest tests/test_oral_combos.py -q")
    if green:
        print("  狀態: 全綠 ✓")
    else:
        print("  狀態: 有失败 — 見 fixtures/oral_failures/")


def one_round(seed: int, count: int, round_no: int) -> bool:
    rows = generate(seed=seed, count=count)
    write_fixtures(rows, FIXTURES)
    total, failures = run_all(FIXTURES)
    if failures:
        path = write_failures(failures, seed=seed, round_no=round_no)
        print_report(total=total, failures=failures, seed=seed, round_no=round_no, green=False)
        print(f"  失敗明细: {path}")
        return False
    print_report(total=total, failures=[], seed=seed, round_no=round_no, green=True)
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20261022)
    parser.add_argument("--count", type=int, default=1200)
    parser.add_argument("--consecutive", type=int, default=1, help="連續全綠輪數目標")
    args = parser.parse_args()

    consecutive = 0
    round_no = 0
    while consecutive < args.consecutive:
        round_no += 1
        seed = args.seed + round_no - 1
        if one_round(seed, args.count, round_no):
            consecutive += 1
        else:
            return 1
    print(f"\n連續 {args.consecutive} 輪全綠。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
