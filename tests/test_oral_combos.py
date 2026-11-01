"""fixtures/oral_combos.jsonl 全量規則 + 分類 E2E 抽樣。"""

from __future__ import annotations

import pytest

from app.oral_autotest import FIXTURES, M_NEGATION_FIXTURES, load_cases, make_pipe, run_oral_case

CASES = load_cases()
TYPES = sorted({c["type"] for c in CASES})
E2E_PER_TYPE = 20


@pytest.fixture(scope="module")
def oral_pipe(tmp_path_factory):
    base = tmp_path_factory.mktemp("oral_combos")
    return make_pipe(base)


def test_m_negation_m01_m10(oral_pipe):
    cases = load_cases(M_NEGATION_FIXTURES)
    assert len(cases) == 10
    failures = []
    for index, case in enumerate(cases):
        result = run_oral_case(oral_pipe, case, phone=f"mneg{index:02d}", confirm_turns=True, want_report=True)
        if result["errors"]:
            failures.append(f"{case['id']}: " + "; ".join(result["errors"]))
    if failures:
        pytest.fail("\n".join(failures))


def test_oral_combos_jsonl_exists():
    assert FIXTURES.is_file()
    assert len(CASES) >= 1000


def test_oral_combos_meta_dimensions():
    meta_path = FIXTURES.parent / "oral_combos_meta.json"
    if meta_path.is_file():
        import json

        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert len(meta.get("dimensions") or []) >= 8


def test_oral_combos_all_rules(oral_pipe):
    failures: list[str] = []
    for index, case in enumerate(CASES):
        phone = f"oc{index:04d}"
        result = run_oral_case(oral_pipe, case, phone=phone, confirm_turns=True, want_report=False)
        if result["errors"]:
            failures.append(f"{case['id']}: " + "; ".join(result["errors"][:5]))
    if failures:
        sample = "\n".join(failures[:25])
        pytest.fail(f"{len(failures)}/{len(CASES)} failed. First failures:\n{sample}")


@pytest.mark.parametrize("case_type", TYPES)
def test_oral_combos_e2e_sample_by_type(oral_pipe, case_type, tmp_path):
    subset = [c for c in CASES if c["type"] == case_type][:E2E_PER_TYPE]
    assert len(subset) >= E2E_PER_TYPE, f"{case_type} needs {E2E_PER_TYPE} cases"
    pipe = make_pipe(tmp_path / case_type)
    failures: list[str] = []
    for index, case in enumerate(subset):
        phone = f"e2e{index:03d}"
        result = run_oral_case(pipe, case, phone=phone, confirm_turns=True, want_report=True)
        if result["errors"]:
            failures.append(f"{case['id']}: " + "; ".join(result["errors"]))
    if failures:
        pytest.fail("\n".join(failures[:10]))
