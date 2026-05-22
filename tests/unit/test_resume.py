"""--resume target selection: pick the most recent incomplete run."""

import pytest

from docspatch.checkpoints.runs import pick_last_run
from docspatch.utils.errors import ConfigError


def test_pick_last_run_returns_newest() -> None:
    assert pick_last_run(["r3", "r2", "r1"]) == "r3"


def test_pick_last_run_errors_when_nothing_to_resume() -> None:
    with pytest.raises(ConfigError, match="No incomplete runs"):
        pick_last_run([])
