"""Project overview store round-trip and generic project facts, no LLM."""

from pathlib import Path

from docspatch.pipelines.scout.overview import overview_path, read_overview, write_overview
from docspatch.schemas import ComponentNote, ProjectOverviewOutput
from docspatch.utils.project import project_facts


def test_overview_round_trips_through_gzip_store(tmp_path: Path) -> None:
    overview = ProjectOverviewOutput(
        summary="does things",
        architecture="layered",
        components=[ComponentNote(name="core", role="runs things")],
    )
    write_overview(tmp_path, overview)
    assert overview_path(tmp_path).suffix == ".gz"
    assert read_overview(tmp_path) == overview


def test_read_overview_missing_returns_none(tmp_path: Path) -> None:
    assert read_overview(tmp_path) is None


def test_read_overview_corrupt_returns_none(tmp_path: Path) -> None:
    path = overview_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not gzip")
    assert read_overview(tmp_path) is None


def test_project_facts_from_pyproject(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\ndescription = "d"\nversion = "2.0"\n'
        'requires-python = ">=3.12"\n\n[project.scripts]\ndemo = "demo:app"\n'
    )
    facts = project_facts(tmp_path)
    assert facts.name == "demo"
    assert facts.description == "d"
    assert facts.labelled == [("Version", "2.0"), ("Python", ">=3.12"), ("Entry points", "demo")]


def test_project_facts_no_pyproject_falls_back_to_dir_name(tmp_path: Path) -> None:
    facts = project_facts(tmp_path)
    assert facts.name == tmp_path.resolve().name
    assert facts.description is None
    assert facts.labelled == []
