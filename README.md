# multi-domain-research

A [Hermes](https://hermes-agent.nousresearch.com/docs) skill. Describe a research **domain** and **direction** as traits; the skill composes a fitting workflow from a block catalog, stores it in a library, and runs it on a local data lake (SQLite ledger + Parquet + DuckDB) using waves of subagents. Every subagent output is file-based and machine-verified on load (quotes, SQL, receipts) before it enters the ledger. Results feed back into the library (Forge, Lab, Crew, Retro).

한국어: 연구 도메인·방향을 특성(traits)으로 서술하면 블록 카탈로그에서 맞는 workflow를 합성·저장하고, 로컬 데이터 레이크 위에서 서브에이전트 웨이브로 실행하는 Hermes 스킬입니다. 서브에이전트 산출물은 모두 파일로 받아 인용·SQL·수신증을 기계 검증한 뒤에만 원장에 적재합니다.

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
