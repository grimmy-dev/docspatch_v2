"""Behaviour of the structured-output and config schemas."""

from docspatch.schemas import DocspatchConfig, ReadmeOutput, RunSettings


def test_readme_output_holds_markdown() -> None:
    out = ReadmeOutput(markdown="# Title\n\nbody")
    assert out.markdown.startswith("# Title")


def test_run_settings_fall_back_to_defaults() -> None:
    settings = RunSettings.from_config(DocspatchConfig())
    assert settings.batch_token_limit > 0
    assert settings.concurrency_limit > 0
    assert settings.call_timeout > 0
