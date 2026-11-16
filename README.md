# multi-domain-research

A [Hermes](https://hermes-agent.nousresearch.com/docs) skill. Describe a research **domain** and **direction** as traits; the skill composes a fitting workflow from a block catalog, stores it in a library, and runs it on a local data lake (SQLite ledger + Parquet + DuckDB) using waves of subagents. Every subagent output is file-based and machine-verified on load (quotes, SQL, receipts) before it enters the ledger. Results feed back into the library (Forge, Lab, Crew, Retro).

Summary (translated from the original Korean note): Describe a research domain and direction as traits, and the skill composes and stores a fitting workflow from the block catalog, then runs it with waves of subagents on a local data lake. All subagent outputs are received as files and are loaded into the ledger only after quotes, SQL, and receipts have been machine-verified.

## Layout

| Path | Contents |
|---|---|
| `SKILL.md` | Procedure (phases P0–P7) and operating pitfalls |
| `scripts/rlab.py`, `scripts/rlab_core/` | Engine CLI (`forge`, `init`, `next`, `load`, `gate`, `sql`, `retro`, ...) |
| `scripts/selftest.py`, `scripts/selftest_unit.py` | End-to-end (compare, describe) and unit regression tests |
| `assets/blocks.json`, `assets/routing.json` | Block catalog and role-to-model routing |
| `references/` | General reference notes (gates, blocks and forge, data lab, crew contracts, ...) |
| `templates/` | Brief and task-contract templates |
| `tools/sync_from_skill.py` | One-way mirror from the live skill folder into this repository |

## Not included

Domain-specific reference packs (person-profile research, personality frameworks, codebook iteration lessons, external STT, local ASR farm) are excluded from the mirror because they contain project-specific material. `SKILL.md` may link to them; those links are dead in this repository. Collected research data (`research-lab/`) is never mirrored.

## Install

Copy the folder contents into the Hermes skills directory as `skills/research/multi-domain-research/`. The engine needs Python 3.12 with `duckdb` installed.

## Test

```bash
RLAB_HOME=/tmp/mdr-selftest PYTHONDONTWRITEBYTECODE=1 python scripts/selftest.py
```

## Sync

The live skill folder is the source of truth. After the skill changes, run `python tools/sync_from_skill.py <skill dir> .` and commit.

## License

Apache-2.0. See `LICENSE`.
