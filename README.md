```
██████╗  ██████╗  ██████╗███████╗██████╗  █████╗ ████████╗ ██████╗██╗  ██╗
██╔══██╗██╔═══██╗██╔════╝██╔════╝██╔══██╗██╔══██╗╚══██╔══╝██╔════╝██║  ██║
██║  ██║██║   ██║██║     ███████╗██████╔╝███████║   ██║   ██║     ███████║
██║  ██║██║   ██║██║     ╚════██║██╔═══╝ ██╔══██║   ██║   ██║     ██╔══██║
██████╔╝╚██████╔╝╚██████╗███████║██║     ██║  ██║   ██║   ╚██████╗██║  ██║
╚═════╝  ╚═════╝  ╚═════╝╚══════╝╚═╝     ╚═╝  ╚═╝   ╚═╝    ╚═════╝╚═╝  ╚═╝
```

# docspatch

![Python](https://img.shields.io/badge/python-3.14%2B-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)
![Code style: Ruff](https://img.shields.io/badge/code%20style-ruff-261230)
![Typed](https://img.shields.io/badge/typing-mypy-blue)

**AI-powered documentation for Python projects.** `docspatch` writes Google-style docstrings and directory-scoped `README.md` files, then edits them into your source without disturbing the surrounding code.

By grimmy_dev · [Report an issue](https://github.com/grimmy-dev/docspatch_v2/issues) · [Repository](https://github.com/grimmy-dev/docspatch_v2)

---

## Why docspatch

Most doc generators re-process a file the moment a byte changes — a reformat, a renamed local, a stray comment — and pay the model for work that changed nothing. `docspatch` works against the **meaning** of your code, not its text:

- Each file is reduced to a **structural hash** that ignores blank lines, comments, and existing docstrings. A reformatted file is never re-sent to the model — only code whose logic actually changed is processed.
- Docstrings are inserted through [`libcst`](https://libcst.readthedocs.io/), so your formatting, imports, and indentation are preserved **exactly**. Nothing else in the file moves.
- Every generated item is **reviewed before it is written** — accept, reject, edit, or regenerate.

## Features

- **Docstrings** — Google-style docstrings for undocumented functions, methods, classes, and modules, inserted in place.
- **READMEs** — draft or refresh a `README.md` scoped to any directory, reviewed as a side-by-side diff before anything is written.
- **Semantic change tracking** — a content-hash manifest skips files unchanged since the last run.
- **Pre-commit ready** — `dp check` reports stale docstrings and READMEs and exits non-zero, with no model calls and no configuration required.
- **Interactive review** — accept, reject, edit, or rerun each generated item.
- **Resumable** — interrupted runs checkpoint to SQLite and continue with `--resume`.
- **Three providers** — Anthropic, OpenAI, and Google Gemini, each with `fast`, `balanced`, and `best` model tiers.
- **Cost-aware** — every run reports token usage and the actual dollar cost.

## Requirements

- Python ≥ 3.14
- An API key for one provider: [Anthropic](https://console.anthropic.com/), [OpenAI](https://platform.openai.com/), or [Google Gemini](https://aistudio.google.com/)

## Installation

`docspatch` installs a single `dp` command.

Once published, install it as a standalone tool:

```bash
uv tool install docspatch    # or: pipx install docspatch
```

From source with [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/grimmy-dev/docspatch_v2.git
cd docspatch_v2
uv sync                      # create the environment and install dependencies
uv run dp --help
```

## Quick Start

```bash
dp init                 # choose a provider, tier, and tone; store an API key
dp docs src/            # document everything undocumented under src/
dp readme               # draft or refresh the root README
dp check                # report stale docs/README; exit non-zero if any (no model calls)
```

A typical first run:

```bash
dp init                 # one-time setup, writes .docspatch/config.toml
dp docs src/ --check    # preview what needs docstrings and the estimated cost
dp docs src/            # generate and review them
```

## Commands

### `dp init`

Walks you through provider, model tier, and tone, then writes configuration to the repo (`.docspatch/config.toml`) or your global path (`~/.docspatch/`). API keys are stored masked. It finishes by reporting whether your docs and README are already up to date.

### `dp docs [PATHS]`

Scans the given files or directories (the whole repo when omitted), generates docstrings for anything undocumented, and edits them into place after review.

| Flag | Description |
| :--- | :--- |
| `--check` | List undocumented functions and the estimated cost; write nothing. |
| `--update` | Regenerate every docstring in scope, including already-documented ones. |
| `--remarks TEXT` | Extra instruction added to every docstring prompt. |
| `--resume` | Continue the most recent interrupted run. |
| `--no-ignore` | Scan files normally excluded by `.gitignore` / `.docsignore`. |

```bash
dp docs src/                      # document a subtree
dp docs src/ --check              # preview only, exit non-zero if work remains
dp docs src/ --update --resume    # full rewrite, resuming if interrupted
```

### `dp readme [PATH]`

Creates or updates a `README.md` for a directory. It compares the directory's source against the last run to decide whether the README is stale, maps the code with a fast analysis model, drafts the document, and shows a diff for approval.

| Flag | Description |
| :--- | :--- |
| `--update` | Re-draft from scratch instead of refreshing sections in place. |
| `--check` | Report whether the README is stale without calling the model. |
| `--remarks TEXT` | Extra layout or content instruction for the draft. |

```bash
dp readme                                   # root README
dp readme src/docspatch/commands/ --check   # is this package's README stale?
```

### `dp check`

Reports whether the root `README.md` or any docstrings are stale, then exits non-zero if so. It makes **no model calls** and needs **no configuration**, so it is safe to run on every commit or in CI.

```bash
dp check    # exit 0 when everything is fresh, 1 when work remains
```

```text
$ dp check
README.md may be stale — 3 changed, 0 removed file(s). Run dp readme to refresh it.
5 function(s) across 2 file(s) need docstrings. Run dp docs to document them.
$ echo $?
1
```

### `dp config`

Show the merged configuration, or set a key:

```bash
dp config                              # print resolved settings
dp config set provider anthropic
dp config set tone technical
```

| Key | Purpose |
| :--- | :--- |
| `provider` | Active provider: `anthropic`, `openai`, or `gemini`. |
| `generator_model` | Model that drafts docstrings and README prose. |
| `analysis_model` | Fast, cheaper model that maps source files. |
| `tone` | Stylistic tone, e.g. `professional` or `technical`. |
| `batch_token_limit` | Maximum tokens per batched model request. |
| `concurrency_limit` | Maximum concurrent model requests. |
| `call_timeout` | Per-request timeout in seconds. |

### `dp cleanup`

Removes local cache files, run logs, and the SQLite checkpoint ledger.

## Pre-commit Hook

Keep documentation from drifting by running `dp check` on every commit. It is fast, offline, and never calls a model. With the [pre-commit](https://pre-commit.com/) framework, add a local hook:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: docspatch-check
        name: docspatch staleness check
        entry: dp check
        language: system
        pass_filenames: false
        always_run: true
```

Then enable it:

```bash
uv tool install pre-commit    # or: pipx install pre-commit
pre-commit install
```

A complete example, including [Ruff](https://docs.astral.sh/ruff/), lives in [`.pre-commit-config.yaml`](.pre-commit-config.yaml) at the repo root.

## How It Works

`docspatch` runs two [LangGraph](https://langchain-ai.github.io/langgraph/) pipelines over a shared change manifest.

- **Docs pipeline.** Finds undocumented targets, packs them into token-bounded batches, and generates docstrings concurrently. Output is compiled to a concrete syntax tree with `libcst` and inserted into the exact scope, so nothing else in the file moves. Anti-LLM-ese and transient-failure retries run automatically, and the model can be switched mid-run when a provider is exhausted.
- **README pipeline.** Scopes a directory, resolves its structure and entry points into a context backbone, maps the code with a fast model, then weaves a draft with the generator model. The result is reviewed as a red/green diff before it is committed.
- **Change manifest.** Both pipelines key their state by pipeline name in one `ChangeManifest`. Files are compared by a structural hash over a normalised syntax tree, with a size/mtime stamp as a fast-skip so unchanged files are not even re-hashed.
- **Checkpoints and ledger.** Runs serialize to an async SQLite store, so `--resume` picks up outstanding work with its saved state and remarks. Token usage is recorded to a per-run ledger and reported as real cost at the end.
- **Run feedback.** Every `docs` and `readme` run shows one live elapsed timer that keeps ticking across steps while output scrolls above it, stepping aside only while an interactive prompt owns the terminal.

## Configuration

Settings resolve in layers: built-in defaults, then your global config (`~/.docspatch/config.toml`), then the repo config (`.docspatch/config.toml`). Later layers win. View or edit them with `dp config`.

To exclude files from documentation, add a `.docsignore` (same syntax as `.gitignore`) to your repo; `.gitignore` is honoured automatically.

## Development

```bash
uv sync                # install runtime + dev dependencies
uv run pytest          # unit, integration, and pipeline tests
uv run ruff check      # lint
uv run mypy src        # static type check
```

## Contributing

Issues and pull requests are welcome — see [the issue tracker](https://github.com/grimmy-dev/docspatch_v2/issues). Please run `uv run pytest`, `uv run ruff check`, and `uv run mypy src` before opening a PR.

## License

MIT — see [LICENSE](LICENSE).

---

*Keep your docs as fresh as your code.*
