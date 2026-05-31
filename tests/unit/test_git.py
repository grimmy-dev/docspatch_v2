"""GitReader: read-only git config access."""

import subprocess

from docspatch.utils.git import GitReader


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def test_reads_local_config_value(tmp_path):
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "Ada Lovelace")
    assert GitReader(tmp_path).config("user.name") == "Ada Lovelace"


def test_returns_none_for_unset_key(tmp_path):
    _git(tmp_path, "init")
    assert GitReader(tmp_path).config("docspatch.nope") is None
