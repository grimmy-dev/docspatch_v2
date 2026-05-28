# docspatch conventions

The single source of truth for *how* code is written here. CLAUDE.md states the
principles; this file states the concrete patterns. Every PRD and every change
follows it. When two ways exist to do something, this file picks one — pick it.

If you find code that violates a convention, the code is wrong, not the
convention. Fix the code or change this file deliberately — never let drift
stand silently.

## Module layout

- One responsibility per module. A module is *deep* (simple interface, real
  implementation hidden) — not necessarily one file, but never a shallow
  wrapper that exists only to be imported.
- Do not create a file under ~80 lines that has a single importer, little
  logic, and no own test. Fold it into its sibling.
- Pure-data/CPU modules (`source.py`) know nothing about the event loop, the
  console, or config. Side effects live at the edges.

## Error handling

- All raised errors subclass `DocspatchError` (`utils/errors.py`).
- Construct via a named `@classmethod` (`ConfigError.unknown_tier(...)`), never
  a bare string at the raise site — the message lives in one place.
- Every error carries an actionable `hint`. Set `exit_code` on the class.
- Never `except Exception` silently. Catch narrow; if you must catch broad,
  add a `# noqa: BLE001` with a one-line reason (see `commit.py`, `janitor.py`).
- The CLI (`cli.py`) is the only place that maps errors to process exit.

## Async

- **Sync core, async edges.** Pure CPU functions stay `def`. Pipeline nodes are
  `async def`. The boundary offloads — not the core.
- CPU-bound work (libcst `compress`, `ast.parse`, large `gzip`) that can run
  while network calls are in flight is wrapped in `asyncio.to_thread` **at the
  call site**, never inside the pure function.
- Every LLM call passes through the run's semaphore / `RateLimitGate`. No
  unbounded `asyncio.gather` over network calls.
- Prefer `asyncio.TaskGroup` over bare `gather` for fan-out so a failure
  cancels siblings.
- Small one-off file reads may stay synchronous on the loop; large or many
  reads in a concurrent phase get offloaded.

## Adapter isolation

- UI goes through the `Prompter` protocol and the `docspatch.ui` facade.
  Never `import rich` or `import questionary` outside `ui/`.
- LLM access goes through `LLMClient` / the typed runnable. Pipelines never
  import a provider SDK directly.
- Engines (AST scan, git status) return **pure data** (lists, dataclasses) —
  never console boxes, colors, or tables. Representation is the UI's job.

## Typing

- Type hints everywhere. `Any` is a last resort; if used, a comment says why.
- Make illegal states unrepresentable: a value that must be one of N options
  uses the typed alias (`Provider`, `Tier`), not a bare `str`.
- Validate external input (config, LLM responses, CLI args) with a strict
  schema at the boundary. Fail fast, before a bad value reaches core logic.

## Docstrings

- Google-style, compact. Document *why* and the *contract* — what the function
  guarantees, what it assumes, how it fails — not what obvious code does.
- No LLM-ese ("facade", "fan out", "tracer-bullet"). Plain verbs.
- Pre-release: no back-compat / "legacy" framing.

## Filesystem & process

- Never write a live file directly. Use `atomic_write` (temp file + atomic
  rename) so an interrupt cannot corrupt the file.
- Subprocess calls pass an argument **list**, never `shell=True`. All git calls
  go through `GitReader`.
- Validate target paths against the repo root; reject traversal outside it.

## Secrets

- API keys are masked everywhere they could surface. All error/log text runs
  through `secrets.scrub`. Config files with secrets get owner-only
  permissions.

## Testing

- Test behavior, not implementation. A refactor that keeps behavior must keep
  tests green without edits.
- Run everything with `uv run` — `uv run pytest`, `uv run ruff`. Never `pip`,
  never bare `python`, never `.venv/bin/python`.

## Naming

- Descriptive and consistent. Avoid a `_` prefix unless the symbol is truly
  module-private. Same concept → same word across the codebase.
