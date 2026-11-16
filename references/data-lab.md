# Data Lab: Ledger, Parquet, DuckDB

## Run tree (`<lab home>/runs/<run_id>/`; a project folder can be specified with `init --root`)

```
brief.md  workflow.json  ledger.sqlite        # ledger (write truth), changed only by transactions
raw/          S0001.txt (canonical text, immutable)  S0001.orig.html ...
staging/      incoming/<task>/ (saved by collector)  out/<task>.jsonl (child output)  dispatch_NNN.json  dispatch_dryrun.json (preview)
tasks/<T>/    contract.md  input/*
lake/         analysis.duckdb  parquet/<table>.parquet  datasets/<name>.parquet  .rev
reports/      deliverable.md  status.md  retro.json
```

Principle: **SQLite is for writing**, **DuckDB·Parquet are for analysis (read-only, regenerable at any time)**. The lake is automatically rebuilt when `sql` runs after the ledger `rev` has changed (can be done manually with `lake build`).

## Ledger tables

`questions` (id,parent,kind,labels,label_defs) · `candidates` (scout results, status new/assigned/collected/unreached) · `sources` (tier 1-4, stance, origin_group, lane, as_of, pii_status, seq, status active/dropped) · `chunks` (source text fragments, substring search) · `datasets` (tabular data profiles) · `evidence` (quote|sql, label, polarity, entity/attribute/value_num/unit/as_of, coder, is_null) · `claims` (ctype, strength, scope, falsifier, status…) · `claim_evidence` (supports|refutes) · `challenges` · `contradictions` (open|resolved|disclosed) · `findings` · `tasks` (status, receipt, attempts, rows_*) · `block_state` · `rejects` · `waivers` · `events` (audit log).

Convenience views: `v_evidence` (evidence + source tier/stance/origin_group/lane/url), `v_claims` (+ counts of supporting, refuting, and refutation attempts). Datasets are loaded **as tables under their own names** (e.g. `SELECT engine, avg(ms) FROM bench GROUP BY 1`).

## SQL

- `rlab sql --run R "SELECT ..."` / `--recipe coverage|source_mix|origin_share|saturation|agreement|claims|entity_matrix|timeline|contradictions|tasks|rejects` / `--format json|csv` / `--limit N` / `--hash`.
- Read-only guard: a single statement; only SELECT/WITH/DESCRIBE/SHOW/PIVOT/SUMMARIZE/FROM; `read_*`, `copy`, `attach`, `pragma`, etc. are blocked; DuckDB `enable_external_access=false`. For broader work (training, visualization), open `lake/parquet/*.parquet` directly with polars or duckdb in a separate script, and if you want to keep the results as new evidence, make them reproducible as SQL evidence (below).
- **SQL evidence**: when the DataAnalyst submits `sql` + `result_sha` (printed by `--hash`; row-order independent, based on rounding to 6 decimal places), `load` re-runs it against the dataset and rejects it if the hash differs. At registration, a dataset is converted to Parquet with DuckDB and profiled (rows, columns, nulls, sample), and the profile is also saved as source text (`raw/S*.txt`).

## Evaluating an engine change against existing run ledgers

- Do not leave the real `runs/*/ledger.sqlite` open; connect with a read-only URI, make a copy, and query only the copy: `sqlite3.connect(f'file:{src}?mode=ro', uri=True).backup(dst_conn)`. Delete the copy when the evaluation is done (it contains research material).
- When classifying rows produced by the pre-change behavior with the post-change rules, if the provenance notation (`contradictions.note`, etc.) has been overwritten by a past `resolve --note`, row-level attribution is impossible. In that case classify conservatively per claim (if all of that claim's challenges are `stands`/`inconclusive`, "not generated under the new rule"; if even one is weakened/refuted, "indeterminable, excluded"; rows without a challenge originate from the analyst and are unaffected). Write the definition together with the numbers, and do not mix them in comparison with numbers reported earlier under a different definition.
- A forward fix does not change past rows. Do not migrate ledgers without a separate design.

## Invariants

- **Traceback path**: quote evidence is `[K] → claim_evidence → evidence.quote → raw/S*.txt` (source text substring); SQL evidence is `[K] → claim_evidence → evidence.sql/result_sha → datasets/<name>.parquet` (re-run hash). The quote field of SQL evidence is a reproduction string and is not a substring of the raw text.
- The `quote` of evidence was verified against `raw/S*.txt` at load time and `raw` is never changed → it can be re-verified at any time by date and hash.
- Claim status is not a stored value but is recomputed from `claim_evidence`, `sources`, and `contradictions` (automatically after `source set/drop` and `resolve`).
- `source drop`: removes the source's evidence, chunks, and links and empties the source text file (to block PII; not reversible).
