# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `dp check` command — reports whether the README or any docstrings are stale and
  exits non-zero if so, with no model calls or configuration required, so it can
  run as a pre-commit hook. `dp init` runs the same report at the end of setup.
- Welcome banner — `dp init` opens with an ASCII banner showing the version and
  issue link; the same banner heads the project README.
- `dp readme` command and README pipeline: a LangGraph agent scopes a directory,
  maps its source with a fast analysis model, then drafts or refreshes a
  `README.md` for side-by-side review before writing.
- Shared `ChangeManifest` backing both pipelines — semantic-hash change
  detection with a stat-stamp fast-skip, keyed per pipeline.
- `DocstringGenerator` protocol so the docs pipeline depends on a generator
  interface rather than the concrete `LLMDocstringGenerator`.
- `py.typed` marker — the package now ships its type information to consumers.
- Persistent run timer: a single elapsed counter ticks for the whole `docs` and
  `readme` run, stepping aside only for interactive prompts.
- Status message while the docs review reruns docstrings, so the regeneration
  step is no longer silent.
- PyPI publishing metadata — SPDX license, classifiers, keywords, and project
  URLs.

### Changed
- Shared `confirm_or_skip` helper backs the docs and readme pre-run prompts, so
  both gate model calls the same way.
- Docs run summary formats elapsed time with `format_duration`, matching the
  readme summary and the live timer.

### Removed
- `mypy` moved from runtime dependencies to the dev group — it was never
  imported at runtime and shipping it added ~50 MB to every install.
- Dead, test-only helpers: `GitReader.is_repo` / `last_commit_touching` /
  `commits_since` and the `BatchPlan` count properties.

### Fixed
- `ConfigError` construction routed through named factory methods
  (`conflicting_flags`, `no_runs_to_resume`) instead of inline strings.

## [0.1.0]

### Added
- `dp` CLI with `init`, `docs`, `cleanup`, and `config` commands.
- Docs pipeline: scout undocumented code, generate Google-style docstrings in
  batched LLM calls, and insert them without disturbing surrounding source.
- Anthropic, OpenAI, and Gemini providers with `fast` / `balanced` / `best`
  model tiers.
- Anti-LLM-ese retries, transient-failure retries, and on-exhaustion model
  switching.
- Checkpointed runs with `--resume`, plus a per-run manifest of counts, tokens,
  and cost.
- Fast-skip cache so already-documented, unchanged files are not re-sent.
- Interactive review panel for accepting, rejecting, or rerunning generated
  docstrings.
- Layered config (defaults < global < repo) with masked API keys and an error
  hierarchy carrying actionable hints.
