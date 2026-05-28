# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `DocstringGenerator` protocol so the docs pipeline depends on a generator
  interface rather than the concrete `LLMDocstringGenerator`.
- `py.typed` marker — the package now ships its type information to consumers.

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
