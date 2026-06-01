"""Target collection: hash-diff skipping, --update widening, module targets."""

from pathlib import Path

from docspatch.pipelines.docs.planner import collect_targets

MODULE_DOC = '"""Module summary."""\n'
DOCUMENTED_FN = 'def f():\n    """Has docs."""\n    return 1\n'
UNDOCUMENTED_FN = "def f():\n    return 1\n"
BLANK_FN = 'def f():\n    """   """\n    return 1\n'


def write(tmp_path: Path, name: str, source: str) -> Path:
    path = tmp_path / name
    path.write_text(source)
    return path


def test_update_targets_documented_function(tmp_path: Path) -> None:
    src = write(tmp_path, "a.py", DOCUMENTED_FN)
    quals = {t.qualname for t in collect_targets([src], tmp_path, update=True).targets}
    assert "f" in quals


def test_update_emits_module_target(tmp_path: Path) -> None:
    src = write(tmp_path, "a.py", UNDOCUMENTED_FN)
    quals = {t.qualname for t in collect_targets([src], tmp_path, update=True).targets}
    assert "<module>" in quals


def test_module_targeted_when_missing_without_update(tmp_path: Path) -> None:
    src = write(tmp_path, "a.py", UNDOCUMENTED_FN)
    quals = {t.qualname for t in collect_targets([src], tmp_path).targets}
    assert "<module>" in quals


def test_no_module_target_when_documented_without_update(tmp_path: Path) -> None:
    src = write(tmp_path, "a.py", MODULE_DOC + "\n\n" + DOCUMENTED_FN)
    quals = {t.qualname for t in collect_targets([src], tmp_path).targets}
    assert "<module>" not in quals


def test_blank_docstring_treated_as_missing(tmp_path: Path) -> None:
    src = write(tmp_path, "a.py", BLANK_FN)
    quals = {t.qualname for t in collect_targets([src], tmp_path).targets}
    assert "f" in quals


def test_fully_documented_file_yields_nothing(tmp_path: Path) -> None:
    src = write(tmp_path, "a.py", MODULE_DOC + "\n\n" + DOCUMENTED_FN)
    assert collect_targets([src], tmp_path).targets == []
