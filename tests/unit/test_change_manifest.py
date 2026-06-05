"""Change-detection manifest: semantic hash stability, diff classification, commit lifecycle."""

from pathlib import Path

from docspatch.manifest import ChangeManifest, semantic_hash

CODE = """
import os


def greet(name: str) -> str:
    \"\"\"Say hello.\"\"\"
    # a comment
    msg = f"hi {name}"
    return msg
"""


def test_semantic_hash_ignores_comments_blanklines_docstrings() -> None:
    edited = (
        "\nimport os\ndef greet(name: str) -> str:\n"
        '    """A different docstring entirely."""\n'
        '    msg = f"hi {name}"\n    return msg\n'
    )
    assert semantic_hash(CODE) == semantic_hash(edited)


def test_semantic_hash_changes_on_real_code_edit() -> None:
    edited = CODE.replace('f"hi {name}"', 'f"hello {name}"')
    assert semantic_hash(CODE) != semantic_hash(edited)


def test_baseline_absent_is_none(tmp_path: Path) -> None:
    assert ChangeManifest(tmp_path).baseline("readme") is None


def test_first_run_treats_everything_as_added(tmp_path: Path) -> None:
    cs = ChangeManifest(tmp_path).diff("readme", {"a.py": "h1", "b.py": "h2"})
    assert cs.added == ["a.py", "b.py"]
    assert cs.updated == [] and cs.removed == []
    assert not cs.empty


def test_diff_classifies_added_updated_removed(tmp_path: Path) -> None:
    m = ChangeManifest(tmp_path)
    m.commit("readme", {"keep.py": "h", "change.py": "old", "gone.py": "h"})
    cs = m.diff("readme", {"keep.py": "h", "change.py": "new", "fresh.py": "h"})
    assert cs.added == ["fresh.py"]
    assert cs.updated == ["change.py"]
    assert cs.removed == ["gone.py"]
    assert cs.changed == ["fresh.py", "change.py"]


def test_empty_changeset_when_nothing_moved(tmp_path: Path) -> None:
    m = ChangeManifest(tmp_path)
    m.commit("readme", {"a.py": "h1"})
    assert m.diff("readme", {"a.py": "h1"}).empty


def test_commit_only_changes_named_pipeline(tmp_path: Path) -> None:
    m = ChangeManifest(tmp_path)
    m.commit("docs", {"x.py": "hx"})
    m.commit("readme", {"y.py": "hy"})
    # readme's write must not erase the docs baseline.
    assert m.baseline("docs") == {"x.py": "hx"}
    assert m.baseline("readme") == {"y.py": "hy"}


def test_commit_refreshes_uuid_each_write(tmp_path: Path) -> None:
    m = ChangeManifest(tmp_path)
    m.commit("readme", {"a.py": "h"})
    import gzip
    import json

    first = json.loads(gzip.decompress(m.path.read_bytes()))["readme"]["uuid"]
    m.commit("readme", {"a.py": "h"})
    second = json.loads(gzip.decompress(m.path.read_bytes()))["readme"]["uuid"]
    assert first != second


def test_stamps_round_trip_for_fast_skip(tmp_path: Path) -> None:
    m = ChangeManifest(tmp_path)
    m.commit("readme", {"a.py": "h"}, stamps={"a.py": (12, 345)})
    assert m.stamps("readme") == {"a.py": (12, 345)}
    # hashes still diff normally
    assert m.diff("readme", {"a.py": "h"}).empty


def test_stamps_absent_when_not_committed(tmp_path: Path) -> None:
    m = ChangeManifest(tmp_path)
    m.commit("readme", {"a.py": "h"})  # no stamps
    assert m.stamps("readme") == {}


def test_corrupt_manifest_treated_as_first_run(tmp_path: Path) -> None:
    m = ChangeManifest(tmp_path)
    m.path.parent.mkdir(parents=True, exist_ok=True)
    m.path.write_bytes(b"not gzip")
    assert m.baseline("readme") is None
    # The corrupt file is dropped, so a later commit rebuilds cleanly.
    m.commit("readme", {"a.py": "h"})
    assert m.baseline("readme") == {"a.py": "h"}
