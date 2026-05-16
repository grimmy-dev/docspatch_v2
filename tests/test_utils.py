"""Utils behavior tests (Priority 1)."""

from docspatch.utils.config import load_config
from docspatch.utils.project import get_dir_tree, get_pyproject_field

# ── config ─────────────────────────────────────────────────────────────────


def test_config_per_repo_wins_over_global(tmp_path):
    global_cfg = tmp_path / "global" / "config.toml"
    global_cfg.parent.mkdir()
    global_cfg.write_text('provider = "openai"\ntone = "casual"\n')

    repo_cfg = tmp_path / "repo" / "config.toml"
    repo_cfg.parent.mkdir()
    repo_cfg.write_text('tone = "technical"\n')

    cfg = load_config(global_path=global_cfg, repo_path=repo_cfg)
    assert cfg.tone.value == "technical"
    assert cfg.provider.value == "openai"


def test_config_scope_labels_correct(tmp_path):
    global_cfg = tmp_path / "global" / "config.toml"
    global_cfg.parent.mkdir()
    global_cfg.write_text('provider = "anthropic"\n')

    repo_cfg = tmp_path / "repo" / "config.toml"
    repo_cfg.parent.mkdir()
    repo_cfg.write_text('tone = "technical"\n')

    cfg = load_config(global_path=global_cfg, repo_path=repo_cfg)
    assert cfg.provider.scope == "global"
    assert cfg.tone.scope == "repo"
    assert cfg.batch_token_limit.scope == "default"


def test_config_missing_files_use_defaults(tmp_path):
    cfg = load_config(global_path=tmp_path / "no.toml", repo_path=tmp_path / "no2.toml")
    assert cfg.batch_token_limit.value == 6000
    assert cfg.batch_token_limit.scope == "default"
    assert cfg.tone.value == "professional"


# ── project ────────────────────────────────────────────────────────────────


def test_project_missing_fields_return_none(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "myapp"\n')

    assert get_pyproject_field(pyproject, "version") is None
    assert get_pyproject_field(pyproject, "description") is None


def test_project_existing_field_returned(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "myapp"\nversion = "1.0"\n')

    assert get_pyproject_field(pyproject, "name") == "myapp"
    assert get_pyproject_field(pyproject, "version") == "1.0"


def test_project_missing_file_returns_none(tmp_path):
    assert get_pyproject_field(tmp_path / "pyproject.toml", "name") is None


def test_project_dir_tree_correct_depth(tmp_path):
    (tmp_path / "a" / "b" / "c").mkdir(parents=True)
    (tmp_path / "a" / "b" / "c" / "deep.py").write_text("")
    (tmp_path / "a" / "shallow.py").write_text("")

    tree = get_dir_tree(tmp_path, max_depth=2)
    assert "shallow.py" in tree
    assert "deep.py" not in tree  # depth 3, excluded
