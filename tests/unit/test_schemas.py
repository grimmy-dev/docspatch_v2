"""Behaviour of the structured-output and domain summary schemas."""

from docspatch.schemas import FileSummary, FileSummaryOutput


def test_file_summary_output_parses_new_fields() -> None:
    out = FileSummaryOutput.model_validate(
        {
            "summary": "does x",
            "interfaces": ["f()", "C"],
            "relationships": ["imports a"],
            "change_note": "added f",
            "function_summaries": {"f": "does f"},
        }
    )
    assert out.interfaces == ["f()", "C"]
    assert out.relationships == ["imports a"]
    assert out.change_note == "added f"


def test_file_summary_output_defaults_new_fields() -> None:
    out = FileSummaryOutput(summary="x")
    assert out.interfaces == []
    assert out.relationships == []
    assert out.change_note is None


def test_file_summary_defaults_new_fields() -> None:
    s = FileSummary(path="src/x.py", summary="does x")
    assert s.interfaces == []
    assert s.relationships == []
    assert s.change_note is None
    assert s.compressed == ""
