# 自動回歸（本機 agent 跑；勿叫人手試 demo 直至全綠匯報）

## 目標
缺口引擎 + 短答合併 + 地點完整性 + 跨案／作廢，用隨機組合口述自測到**連續兩輪全綠**。

## 資料
- `fixtures/oral_combos.jsonl`：預設 1200 單（組合 + 跨案／作廢場景）
- `fixtures/oral_combos_meta.json`：seed、維度、類型統計
- 失敗快照：`fixtures/oral_failures/*.jsonl`；可選釘選 `fixtures/oral_regression_pinned.jsonl`

## 覆蓋維度
日期寫法、樓+地點、短答 merge、座+樓+位置、跨案、作廢清空、主觀詞口述、ASR 近音、禁 12:00、地點完整性。

## 重跑
```bash
python fixtures/generate_oral_combos.py --seed 20261022 --count 1200
python fixtures/oral_regression_loop.py --consecutive 2 --seed 20261022 --count 1200
python -m pytest -q --ignore=tests/test_oral_combos.py
python -m pytest tests/test_oral_combos.py -q
```

## 完成定義
- `oral_regression_loop.py --consecutive 2` 連續兩輪失敗 0
- `pytest` 單元 + `test_oral_combos` 全綠
