# docspatch

docspatch automates Python docstring and README generation. It parses code structures with AST-aware analysis and injects documented changes directly into source files using `libcst`, preserving your existing formatting, imports, and indentation.

By tracking semantic changes instead of line-by-line diffs, docspatch limits LLM processing to code that has actually undergone logical modifications.

## Getting Started

### Requirements

- Python >= 3.14
- An API key for your chosen LLM provider (Anthropic, OpenAI, or Google Gemini)

### Installation

The project uses [uv](https://docs.astral.sh/uv/) for package management. Sync the environment to install dependencies:

```bash
uv sync
```

This installs core dependencies including `libcst>=1.8.6`, `typer>=0.15`, `rich>=13`, `langgraph>=1.2.0`, and provider libraries such as `langchain-anthropic` and `langchain-openai`.

### Initialization

Set up your local configuration and scan your project structure to create a baseline:

```bash
uv run dp init
```

This command guides you through selecting your preferred provider and model tier, writing configurations to the local `.docspatch/` directory or your global configuration path.

## Usage

### Generating Docstrings

The `dp docs` command scans Python modules, extracts existing structures, and generates Google-style docstrings for undocumented functions, classes, and modules. It uses a content-hash change manifest to ensure only modified functions are processed.

```bash
uv run dp docs src/                # Analyze and document files inside the src/ directory
uv run dp docs --check             # Identify undocumented functions and show updates without writing to disk
uv run dp docs --update --resume   # Force overwrite existing docstrings and resume an interrupted pipeline execution
```

| Flag | Description |
| :--- | :--- |
| `--check` | Validates missing documentation and shows pending changes without editing files. |
| `--update` | Overwrites existing docstrings instead of skipping documented items. |
| `--remarks TEXT` | Appends custom instructions (e.g., "Use highly technical terminology") to the LLM context. |
| `--resume` | Recovers the execution state of an interrupted run from the SQLite ledger. |
| `--no-ignore` | Forces docspatch to scan files otherwise bypassed by your `.docsignore` patterns. |

### Maintaining READMEs

The `dp readme` command creates or updates a `README.md` targeted at a directory level. It measures the semantic drift of the source files in that directory since the last documentation generation to determine if the README is stale.

```bash
uv run dp readme                   # Analyze the entire project and draft or refresh the root README.md
uv run dp readme src/pkg/ --check  # Check if a package-specific README is out of sync with its source files
```

| Flag | Description |
| :--- | :--- |
| `--update` | Re-drafts the README from scratch rather than updating sections in place. |
| `--check` | Reports whether the README is stale relative to the source code without calling the LLM. |
| `--remarks TEXT` | Adds explicit layout or contextual instructions to the markdown generator. |

## How it Works

docspatch divides tasks into two separate execution pipelines powered by LangGraph agents:

1. **Docs Pipeline (`run_docs`)**: This pipeline identifies target functions, determines missing documentation, and processes batches of changes. Instead of naive text replacement, docspatch compiles code to concrete syntax trees with `libcst` to inject `DocstringSpec` values directly into target scopes. Changes are tracked with a `ChangeManifest` that stores structural SHA-256 hashes of the code body (ignoring blank lines, comments, and docstrings).
2. **README Pipeline (`generate_readme`)**: This pipeline builds a `PreContext` containing structural facts, entry points, and dependencies. A scout model first runs through the target scope to map logic flows. A generator model then weaves this analysis into target markdown segments. The result is displayed in a side-by-side terminal comparison using Rich, allowing you to accept or reject changes before they are committed to disk.

### Checkpoints and Ledger

Interrupted runs do not lose their progress. The `docspatch` pipeline utilizes an asynchronous checkpoint store (`AsyncSqliteSaver` inside `docs_db_path(repo_root)`) to serialize run states. When you run a command with `--resume`, the pipeline retrieves the incomplete graph state, validates outstanding targets, and proceeds with the execution using saved metadata and remarks. Active API token usage is tracked inside a local SQLite ledger to report actual model costs at the end of every run.

## Configuration

Configurations are resolved by merging defaults with your global config and local `.docspatch/` keys. You can view or change settings using the `dp config` interface.

```bash
uv run dp config set provider anthropic
uv run dp config set tone technical
```

| Key | Purpose |
| :--- | :--- |
| `provider` | The active LLM provider (`anthropic`, `openai`, or `gemini`). |
| `generator_model` | The model assigned to draft docstrings and compose markdown (e.g., `claude-3-5-sonnet`). |
| `scout_model` | A fast-tier, cost-efficient model used to summarize source files. |
| `tone` | The stylistic tone used across documentation (e.g., `professional`, `technical`). |
| `batch_token_limit` | The maximum token limit allocated per batched LLM payload. |

## Development

Set up a local environment with `uv` and execute linting and tests directly:

```bash
uv run pytest          # Run unit, integration, and pipeline tests
uv run ruff check      # Scan for style guide violations
uv run mypy src        # Perform static type checking on the source tree
```

You can wipe local cache files, transaction logs, and the SQLite state ledger by running:

```bash
uv run dp cleanup
```

## License

MIT — see [LICENSE](LICENSE).
