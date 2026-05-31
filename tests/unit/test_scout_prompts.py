"""Scout prompt wording: body inclusion and change-note context."""

from docspatch.pipelines.scout.prompts import build_batch_prompt
from docspatch.pipelines.scout.state import FileMiss
from docspatch.schemas import FileSummary


def test_prompt_includes_new_compressed_body() -> None:
    miss = FileMiss("b.py", "src", "def b(): return 2", "h")
    prompt = build_batch_prompt([miss])
    assert "def b(): return 2" in prompt


def test_prompt_includes_prior_context_for_changed_file() -> None:
    prior = FileSummary(path="a.py", summary="old summary", compressed="def a(): return 0")
    miss = FileMiss("a.py", "src", "def a(): return 1", "h", prior=prior)
    prompt = build_batch_prompt([miss])
    assert "old summary" in prompt
    assert "def a(): return 0" in prompt
    assert "change_note" in prompt


def test_prompt_has_no_prior_section_for_new_file() -> None:
    miss = FileMiss("b.py", "src", "def b(): return 2", "h")
    prompt = build_batch_prompt([miss])
    assert "change_note" not in prompt
