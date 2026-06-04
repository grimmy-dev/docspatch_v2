# docspatch

docspatch automates the generation and maintenance of Python docstrings and README files by synchronizing documentation with your evolving code logic.

It parses your source code using LibCST to inject Google-style docstrings into undocumented functions and classes while preserving your existing formatting. It also synthesizes project-level READMEs by scouting your codebase's architecture and public interfaces. Every change is presented as a visual diff for human-in-the-loop approval before any files are modified on disk.

## Requirements

- Python >= 3.14
- An API key for Anthropic, OpenAI, or Google (Gemini)

## Install

This project uses [uv](https://docs.astral.sh/uv/) for package management.

```bash
uv sync
```

## Quick Start

Initialize your project to configure a provider and perform the first codebase scan, then generate documentation:

```bash
uv run dp init          # Configure provider, API key, and scan codebase
uv run dp docs          # Add Google-style docstrings to undocumented code
uv run dp readme        # Generate or refresh README.md from codebase context
```

## How it works

docspatch follows a reactive pipeline architecture driven by Typer and LangGraph. It operates in two distinct phases: scouting and generation. 

1.  **Scouting**: The `scout` pipeline summarizes the state and architecture of your files into a unified project-level map stored in `.docspatch/CONTEXT.md`. This pass is cached; unchanged files are not re-analyzed.
2.  **Generation**: The `docs` and `readme` pipelines consume this context. They utilize asynchronous LLM nodes to plan and generate content, which is then validated against your code's AST. 

All execution state is persisted to a local SQLite checkpoint, allowing you to interrupt and resume long-running operations without losing progress or redundant API costs.

## Commands

| Command | Description |
| :--- | :--- |
| `dp init` | Bootstraps the repo, validates API credentials, and runs the initial scout scan. |
| `dp docs [PATHS]` | Generates docstrings for functions, classes, and modules in the target paths. |
| `dp readme [PATH]` | Creates or refreshes a README.md scoped to the given directory or the repo root. |
| `dp config` | Displays the merged configuration from global and local stores. |
| `dp cleanup` | Interactively audits and removes caches, checkpoints, and metadata. |

### Documenting Code

The `dp docs` command scans for missing docstrings and inserts them using Google-style formatting. It avoids reformatting surrounding code and requests approval for every change.

```bash
uv run dp docs src/                # Document everything in the src directory
uv run dp docs --check             # Report missing docstrings without writing
uv run dp docs --update --resume   # Refresh existing docs and continue an interrupted run
```

- `PATHS`: Target files or directories. Defaults to the entire repository.
- `--check`: Validates changes and exits without writing.
- `--update`: Overwrites existing docstrings instead of skipping them.
- `--remarks TEXT`: Adds custom instructions (e.g., "Use concise language") to the generator.
- `--resume`: Continues from the last checkpointed run in the SQLite ledger.
- `--no-ignore`: Forces the runner to ignore patterns defined in `.docsignore`.

### Generating READMEs

Use `dp readme` to maintain documentation based on the architectural summaries produced by the scout pass. It manages content scope using markers to refresh only specific sections by default.

```bash
uv run dp readme                   # Refresh the root README.md
uv run dp readme src/pkg/ --update # Rewrite a package-specific README from scratch
```

- `PATH`: Directory to scope the README to; repo root when omitted.
- `--update`: Performs a full rewrite from scratch instead of an in-place refresh.
- `--check`: Reports if the README is stale relative to the codebase without calling the LLM.

## Configuration

Settings are merged from built-in defaults, your global user config, and the local `.docspatch/` directory. Secrets like `api_key` are stored with restricted permissions.

| Key | Purpose |
| :--- | :--- |
| `provider` | The LLM provider (`anthropic`, `openai`, or `gemini`). |
| `api_key` | Credential for the selected provider. |
| `generator_model` | The model used for writing docstrings and markdown. |
| `scout_model` | A typically cheaper model used for summarizing file logic. |
| `tone` | The writing style for generated content (e.g., `professional`). |
| `batch_token_limit` | Maximum tokens processed per batched LLM request. |

```bash
uv run dp config set provider anthropic
uv run dp config set tone technical
```

## Development

```bash
uv run pytest          # Run integration and unit tests
uv run ruff check      # Lint code
uv run mypy src        # Verify type safety
```

## License

MIT — see [LICENSE](LICENSE).
