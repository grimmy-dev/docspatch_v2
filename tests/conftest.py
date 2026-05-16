"""Shared pytest fixtures."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def no_real_docspatch_writes(tmp_path, monkeypatch):
    """Redirect Path.home() so tests can never accidentally write to ~/.docspatch."""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
