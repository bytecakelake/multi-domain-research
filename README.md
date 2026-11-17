# multi-domain-research

A [Hermes](https://hermes-agent.nousresearch.com/docs) skill plus a local Python engine, `rlab`, for evidence-tracked research.

You describe a research **domain** and **direction** as a small set of traits (mode, stakes, volume, access, ...). `rlab forge` composes a workflow from a block catalog (`assets/blocks.json`) and saves it in a workflow library. A run of that workflow is driven by the parent Hermes agent in waves of subagent tasks. Subagents submit results as files; the parent loads them with `rlab load`, which checks receipts, verbatim quotes and SQL evidence before accepting results into the run's SQLite ledger. Gates, a DuckDB/Parquet lake and a retro step round out the loop.

The procedure the agent follows is in [`SKILL.md`](SKILL.md) (phases P0-P7: setup, traits, forge, start run, drive loop, analysis, deliverable, retro).

## What is here

- **Skill** (`SKILL.md`): operating procedure and pitfalls for the Hermes agent.
- **Engine** (`scripts/rlab.py` + `scripts/rlab_core/`): CLI with subcommands `doctor, setup, forge, wf, init, questions, source, next, begin, check, load, done, retry, dispatched, unready, resume, waive, downgrade, reopen, refresh-inputs, resolve, gate, lake, sql, recipes, search, status, report, retro`. Run `python scripts/rlab.py --help` for the authoritative list.
- **Block catalog and routing** (`assets/`): workflow building blocks and role-to-model routing.
- **Reference notes and templates** (`references/`, `templates/`).

Verification covers structure and mechanics (receipts present, quotes found verbatim in stored source text, SQL results reproducible, gates evaluated). See [Limitations](#limitations) for what it does not cover.

## Prerequisites

- Python 3 (tested here on 3.13; `SKILL.md` reports passing self-tests on 3.12 and 3.14). The standard-library `sqlite3` must have FTS5 (`rlab doctor` reports it).
- **DuckDB** (`pip install duckdb`) is required for `lake`, `sql`, datasets and SQL evidence. Forge, the ledger and gates run on standard-library SQLite alone, but `rlab doctor` reports `RESULT NEEDS SETUP` without DuckDB, and the bundled self-test exercises the data paths, so install it. `pyarrow` and `polars` are optional.
- A Hermes agent (with `delegate_task`) to actually run subagent waves. The CLI by itself does not call any model; it plans tasks, emits dispatch payloads and verifies what comes back.

This repo is not a pip package and has no installer. Nothing in it installs a Hermes plugin.

## Install as a Hermes skill

Copy the repository contents (`SKILL.md`, `assets/`, `references/`, `scripts/`, `templates/`) into your Hermes skills directory, e.g. `skills/research/multi-domain-research/`. Then point the agent at an interpreter that has DuckDB. See the paths mentioned in `SKILL.md` for the layout it assumes (it is written around a Docker sandbox, so adjust paths for your setup).

## Quickstart (CLI only, isolated)

Everything below was run on Linux (Python 3.13.16, DuckDB 2.0.0) in a throwaway virtualenv with `RLAB_HOME` pointing at a scratch directory, so no real lab data is touched. `RLAB_HOME` selects where workflows and runs are stored; if unset, the engine uses `/workspace/research-lab` when `/workspace` exists, otherwise `~/.hermes/research-lab`.

```bash
REPO=$(pwd)                             # run from the repository root
WORK=$(mktemp -d "$REPO/.mdr-demo.XXXXXX")
python3 -m venv "$WORK/venv"
"$WORK/venv/bin/python" -m pip install duckdb
export RLAB_HOME="$WORK/lab" PYTHONDONTWRITEBYTECODE=1
rlab() { "$WORK/venv/bin/python" "$REPO/scripts/rlab.py" "$@"; }

rlab doctor
```

Output:

```
python      3.13.16  (.../venv/bin/python)
sqlite      3.46.1  fts5=yes
duckdb      2.0.0
pyarrow     not installed (optional)
polars      not installed (optional)
lab home    .../lab  writable=yes
workflows   0 saved
RESULT OK
```

**Forge** a workflow from traits (copy the example and edit the free-form `domain` and `direction`):

```bash
cp "$REPO/assets/traits.example.json" "$WORK/traits.json"  # edit domain/direction as needed
rlab forge --traits "$WORK/traits.json" --name oss-compare
```

This prints a block table and saves `workflows/oss-compare-v1.json` (+ `.md`) under `RLAB_HOME`. The first run printed, for example, `blocks=12` and `est dispatch tasks~40 (planning estimate)`; block sequence was `intake, qtree, workflow-critic, scout, collect, extract-single, data-analyze, analyze-claims, compare-matrix, adversary, synthesize, retro`, with lanes `web-primary, web-independent, repos, datasets, counter-view`. The exact block set depends on the traits and on what is already in the library (a later forge of similar traits produced an 11-block workflow, `novel=False`), so do not treat these numbers as fixed.

```bash
rlab wf list
rlab init --workflow oss-compare-v1 --run-id demo1
rlab status --run demo1
rlab next --run demo1
```

`init` prints `run created: .../runs/demo1` and tells you to fill in `brief.md` and load questions. `status` then shows block `intake` as `active` and the rest `pending`, with the global gates (`coverage`, `saturation`, `claim_support`, ...) failing because there are no questions or claims yet. `next` prints a design-phase summary such as `PHASE: design   blocks 0/12 complete` and a `[PARENT ACTIONS]` item for `intake` (fill `templates/brief.md`, then `rlab done --block intake`).

**Not demonstrated here:** beyond `init`/`status`/`next`, a real run needs a brief, a question file (see `templates/questions.example.jsonl`), and subagents dispatched by Hermes via `next --dispatch`; those parts were not exercised with live models in this quickstart. The test below plays the parent and fake subagents with synthetic data against the real CLI.

## Test

The self-test runs end to end on synthetic data in a temporary lab, then unit regressions. It needs DuckDB and takes about 45 seconds on the machine used here (`SKILL.md` budgets several minutes for slower setups).

Using the `REPO` and `WORK` variables and virtual environment from the quickstart:

```bash
TMPDIR="$WORK" PYTHONDONTWRITEBYTECODE=1 "$WORK/venv/bin/python" "$REPO/scripts/selftest.py"
```

The temporary directory must be on a filesystem that permits loading native libraries (some `/tmp` mounts do not). When finished, remove the scratch directory with `rm -rf -- "$WORK"`.

Actual output:

```
--- e2e compare: rc=0, 29 pass, 0 fail
--- e2e describe: rc=0, 31 pass, 0 fail
--- unit regressions: UNIT PASS
SELFTEST PASS
```

You can run one mode with `selftest.py compare` or `selftest.py describe`. No pytest is needed.

## Limitations

- **Platform validation:** `SKILL.md` declares `linux, macos, windows`, but only Linux was exercised for this README. macOS and native Windows are unverified. Note that `rlab setup` writes a `/bin/sh` wrapper script (only when `/workspace/.envs/bin` exists or `--wrapper` is given), and the default lab-home logic assumes POSIX-style paths.
- **Non-ASCII paths:** use ASCII run ids and `RLAB_HOME`; otherwise the engine warns that dispatch text may be mangled.
- **Citation checks are structural.** The `citation` gate verifies that cited ids exist, at least one citation is present and a Limitations section exists. It does not verify that each sentence is semantically supported by its cited claim; a human must review that.
- **Data validation checks provenance, not truth.** Quotes must be contiguous substrings of the stored source text and SQL evidence must reproduce, but this does not show a source is accurate, independent or complete. Source-quality and independence gates are heuristics.
- **Model-dependent stages** (collection, extraction, analysis, refutation) depend on whichever models Hermes delegates to; the self-test uses synthetic fakes, not live models.

## Source-tree structure

| Path | Contents |
|---|---|
| `SKILL.md` | Skill procedure (P0-P7) and pitfalls |
| `scripts/rlab.py` | CLI entry point |
| `scripts/rlab_core/` | Engine: `cli`, `core`, `forge`, `gates`, `ingest`, `lake`, `library`, `runtime` |
| `scripts/selftest.py`, `scripts/selftest_unit.py` | End-to-end and unit tests |
| `assets/` | `blocks.json`, `routing.json`, `traits.example.json` |
| `references/` | Notes on blocks and forge, gates, data lab, crew contracts, trait rubric, playbooks, retro, engine maintenance |
| `templates/` | `brief.md`, `questions.example.jsonl` |
| `tools/sync_from_skill.py` | One-way mirror from a live skill folder into this repo (maintainer tool) |

## Not included in this source tree

- Five domain-specific reference packs are deliberately excluded: person-profile research, personality frameworks, codebook iteration lessons, external speech-to-text, and local ASR farm. `SKILL.md` may mention or link to them; those links do not resolve in this repository.
- Collected research data (a lab home such as `research-lab/`: workflows, runs, ledgers, raw sources, Parquet/DuckDB files) is never part of the source and is not mirrored.

## Maintenance

The repository is mirrored from a live skill folder: `python tools/sync_from_skill.py <skill dir> .` overwrites `SKILL.md`, `assets/`, `references/`, `scripts/` and `templates/`.

## License

Apache-2.0. See [`LICENSE`](LICENSE).
