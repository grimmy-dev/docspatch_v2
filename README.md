# docspatch

AI-powered documentation generation for Python projects. `docspatch` finds
undocumented functions, classes, and modules, generates Google-style docstrings
with an LLM, and inserts them into your source without touching surrounding code.

The CLI is `dp`.

## Requirements

- Python >= 3.14
- An API key for one of: Anthropic, OpenAI, or Google (Gemini)

## Install

This project uses [uv](https://docs.astral.sh/uv/) for all package management.

```bash
uv sync
```

## Quick start

```bash
uv run dp init          # configure provider + API key for this repo
uv run dp docs          # document the whole repo
```

## Commands

| Command | What it does |
|---------|--------------|
| `dp init` | Configure docspatch in the current repo (provider, API key, models). |
| `dp docs [PATHS]` | Generate docstrings for undocumented code in the given files or directories (whole repo when omitted). |
| `dp cleanup` | Interactively remove docspatch artefacts. |
| `dp config` | Show the merged config. |
| `dp config set KEY VALUE` | Set a single config key (scope inferred from the key). |

### `dp docs` flags

| Flag | Effect |
|------|--------|
| `--check` | Preview what needs docs; write nothing. |
| `--update` | Regenerate docstrings that already exist, widening scope. |
| `--remarks TEXT` | Run-wide instruction injected into every prompt (e.g. `"Use British spelling."`). |
| `--resume` | Continue the most recent interrupted run from its checkpoint. |
| `--no-ignore` | Ignore `.docsignore` rules for this run. |
| `--debug` | Trace every step and print full tracebacks. |

```bash
uv run dp docs src/                # everything under src/
uv run dp docs src/app.py          # a single file
uv run dp docs --check src/        # preview only
uv run dp docs --resume            # continue an interrupted run
```

## Configuration

Config is layered: built-in defaults < global (`~`) < repo (`.docspatch/`). The
scope of a key is inferred — secrets and machine-wide settings go global, project
settings go repo-local. API keys are masked in all output and error text.

| Key | Meaning |
|-----|---------|
| `provider` | `anthropic`, `openai`, or `gemini`. |
| `api_key` | Provider API key (stored with owner-only permissions). |
| `generator_model` | Model used to write docstrings. |
| `scout_model` | Cheaper model used to scout/summarise code. |
| `tone` | Docstring tone (e.g. `professional`). |
| `batch_token_limit` | Max tokens per batched LLM call. |

```bash
uv run dp config set provider anthropic
uv run dp config set api_key sk-...
```

Model tiers map to `fast`, `balanced`, and `best`.

## Development

```bash
uv run pytest          # tests
uv run ruff check      # lint
uv run mypy src        # type-check
```

## License

MIT — see [LICENSE](LICENSE).
