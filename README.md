# docspatch

AI-powered documentation for Python projects. `docspatch` writes Google-style docstrings and directory-scoped `README.md` files, then edits them into your source without disturbing the surrounding code.

It works against the *meaning* of your code, not its text. Each file is reduced to a structural hash that ignores blank lines, comments, and existing docstrings, so a reformatted file is never re-sent to the model — only code whose logic actually changed is processed. Docstrings are inserted through `libcst`, preserving your formatting, imports, and indentation exactly.

## Features

- **Docstrings** — generate Google-style docstrings for undocumented functions, methods, classes, and modules, inserted in place.
- **READMEs** — draft or refresh a `README.md` scoped to any directory, reviewed side-by-side before anything is written.
- **Semantic change tracking** — a content-hash manifest skips files that are unchanged since the last run.
- **Interactive review** — accept, reject, edit, or rerun each generated item.
- **Resumable** — interrupted runs checkpoint to SQLite and continue with `--resume`.
- **Three providers** — Anthropic, OpenAI, and Google Gemini, each with `fast`, `balanced`, and `best` model tiers.
- **Cost-aware** — every run reports token usage and actual dollar cost.

## Requirements

- Python ≥ 3.14
- An API key for one provider: Anthropic, OpenAI, or Google Gemini

## Installation

`docspatch` installs a single `dp` command.

From source with [uv](https://docs.astral.sh/uv/):

```bash
uv sync          # create the environment and install dependencies
uv run dp --help
```

Once published, install it as a standalone tool:

```bash
uv tool install docspatch   # or: pipx install docspatch
```

## Quick Start

```bash
dp init                 # choose a provider, tier, and tone; store an API key
dp docs src/            # document everything undocumented under src/
dp readme               # draft or refresh the root README
```

## Commands

### `dp init`

Walks you through provider, model tier, and tone, then writes configuration to the repo (`.docspatch/config.toml`) or your global path (`~/.docspatch/`). API keys are stored masked.

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

## How It Works

`docspatch` runs two LangGraph pipelines over a shared change manifest.

**Docs pipeline.** Finds undocumented targets, packs them into token-bounded batches, and generates docstrings concurrently. Output is compiled to a concrete syntax tree with `libcst` and inserted into the exact scope, so nothing else in the file moves. Anti-LLM-ese and transient-failure retries run automatically, and the model can be switched mid-run when a provider is exhausted.

**README pipeline.** Scopes a directory, resolves its structure and entry points into a context backbone, maps the code with a fast model, then weaves a draft with the generator model. The result is reviewed as a red/green diff before it is committed.

**Change manifest.** Both pipelines key their state by pipeline name in one `ChangeManifest`. Files are compared by a structural hash (`semantic_hash` over a `Squeezer`-normalised tree), with a size/mtime stamp as a fast-skip so unchanged files are not even re-hashed.

**Checkpoints and ledger.** Runs serialize to an async SQLite store, so `--resume` picks up outstanding work with its saved state and remarks. Token usage is recorded to a per-run ledger and reported as real cost at the end.

**Run feedback.** Every `docs` and `readme` run shows one live elapsed timer that keeps ticking across steps while output scrolls above it. The docs run reports batch progress (`Generating docstrings 3/10`) and regeneration on that same line, stepping aside only while an interactive prompt owns the terminal.

## Configuration

Settings resolve in layers: built-in defaults, then your global config (`~/.docspatch/config.toml`), then the repo config (`.docspatch/config.toml`). Later layers win. View or edit them with `dp config`.

## Development

```bash
uv sync                # install runtime + dev dependencies
uv run pytest          # unit, integration, and pipeline tests
uv run ruff check      # lint
uv run mypy src        # static type check
```

## License

MIT — see [LICENSE](LICENSE).
