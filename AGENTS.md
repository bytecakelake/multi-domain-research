# Agent guidance

## Project

This repository contains the `multi-domain-research` Hermes skill and `rlab`, a Python CLI for composing and running evidence-tracked research workflows. Start with [README.md](README.md) for setup and [SKILL.md](SKILL.md) for the research procedure. The CLI plans work and verifies outputs; it does not itself invoke a model.

## Repository map

- `scripts/rlab.py`: CLI entry point; `scripts/rlab_core/cli.py`: command parsing and handlers.
- `scripts/rlab_core/core.py`: run paths, shared helpers and ledger schema; `forge.py` and `library.py`: workflow composition and library.
- `runtime.py`: task expansion, dispatch and run progression; `ingest.py`: output checking and ingestion; `gates.py`: research gates; `lake.py`: DuckDB, Parquet and SQL.
- `assets/`: block catalog, routing and example traits. `templates/`: brief and example questions. `references/`: detailed operating and maintenance guidance.
- `scripts/selftest.py` and `scripts/selftest_unit.py`: synthetic end-to-end and regression tests.

## Engineering invariants

- A task emitted by `next --dispatch` is `ready`, not confirmed as delegated. `dispatched` or the child's `begin` confirms delegation; `unready` cancels an unconfirmed emission without counting a retry. Use `retry` for a delegated attempt that failed. Audit concurrency limits, billing-stop logic and timestamps when changing these states.
- Subagents submit output through task files. Preserve receipt verification, input snapshots, transactional ingestion and rejection handling. A successful structural check does not prove that a source is true or that a sentence is semantically supported by its citation.
- An existing run-level `addendum.md` is included by reference in emitted contexts; its prohibitions and limits take precedence on conflict. `refresh-inputs` re-expands eligible never-started tasks and must refuse unsafe or duplicate work and roll back on failure. Consult `references/crew-contracts.md` and `references/blocks-and-forge.md` before changing either behavior.
- SQLite is the operational ledger; DuckDB and Parquet provide analytical paths. Preserve schema and existing run compatibility unless an explicitly reviewed migration is part of the task. Keep source quotations verifiable in their original language.
- Preserve identifiers, JSON formats, Unicode support and existing line endings. `.gitattributes` disables text normalization; many tracked files use CRLF, while some use LF. Do not reformat unrelated lines.

## Testing

Use synthetic data and an isolated lab home; never point tests at a real research lab. Run from the repository root using a Python environment with DuckDB and SQLite FTS5. `README.md` documents an isolated virtual environment and quickstart. For example, once an appropriate interpreter is active:

```bash
WORK=$(mktemp -d "$(pwd)/.mdr-test.XXXXXX")
TMPDIR="$WORK" RLAB_HOME="$WORK/lab" PYTHONDONTWRITEBYTECODE=1 python scripts/selftest.py
```

Remove the scratch directory after inspection. It must be on a filesystem that permits loading native libraries. The suite runs compare and describe end-to-end scenarios plus unit regressions; it uses synthetic data, not live models. For behavioral fixes, add a regression test that fails before the fix and passes after it; verify rollback and other critical safeguards with negative cases. Report platform and live-model coverage honestly.

## Data and publishing

Do not commit research runs, source material, credentials or private local notes. Five domain-specific reference packs are intentionally excluded from the public tree; do not copy them into it. Respect the user's instructions and applicable law and platform rules when working with research data.

The repository can be mirrored from an installed skill using `tools/sync_from_skill.py`; the direction is from skill to repository and the script overwrites mirrored files. Do not run it blindly over uncommitted edits. For engine changes, follow `references/engine-maintenance.md`: verify the repository change, then coordinate any installed-skill update separately. Contributors without Hermes can work on the repository and run its CLI and tests independently.
