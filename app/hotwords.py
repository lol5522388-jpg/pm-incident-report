"""熱詞表。ASR 整份載入；近音建議只用 fuzzy.txt，避免短詞亂配。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def _lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    rows = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(line)
    return rows


def load_hotwords() -> list[str]:
    return _lines(DATA / "hotwords.txt")


def load_fuzzy_targets() -> list[tuple[str, str]]:
    targets = []
    for line in _lines(DATA / "fuzzy.txt"):
        kind, _, word = line.partition(" ")
        word = word.strip()
        if kind in {"place", "term"} and word:
            targets.append((kind, word))
    return targets
