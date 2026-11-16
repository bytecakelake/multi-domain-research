# Block Catalog and Composition Rules

workflow = a **DAG of blocks** selected from traits. Definitions are in `assets/blocks.json`; the composition code is `scripts/rlab_core/forge.py`.

## Blocks

| block | phase | role | fanout | inclusion condition (when) |
|---|---|---|---|---|
| intake, qtree | design | Parent | single | always |
| workflow-critic | design | Critic | single | stakes=high, or the library has no similar workflow (novel) |
| access-broker | acquire | Parent | single | access∈{mixed,gated} |
| scout | acquire | Scout | per_lane | always (max_waves 3, 2 if small) |
| collect | acquire | Collector | candidate_batch | always |
| source-audit | acquire | Auditor | single | noise≥med or stakes=high |
| privacy-gate | acquire | Parent | single | ethics≥personal_data |
| extract-dual | extract | Extractor | source_batch (A/B blind) | verifiability=interpretive or stakes=high or mode∈{evaluate,explain} |
| extract-single | extract | Extractor | source_batch | the complement of the above |
| data-analyze | analyze | DataAnalyst | per_data_question | quant (question kind∈measure,compare,trend,rank) |
| analyze-claims | analyze | Analyst | per_question | always (writes claims looking only at evidence IDs) |
| compare-matrix | analyze | Analyst | single | mode∈{compare,evaluate} |
| timeline-build | analyze | Analyst | single | temporal |
| rival-hypotheses | analyze | Analyst | per_question | mode∈{explain,verify} or stakes=high |
| base-rates | analyze | Analyst | single | mode=forecast |
| adversary | challenge | Adversary | claim_batch | stakes≥med or noise≥med or mode∈{verify,explain,evaluate} |
| bias-audit | challenge | Auditor | single | verifiability=interpretive or noise≥med |
| synthesize | synthesize | Parent | single | always (citation and contradictions gates) |
| qa-review | synthesize | Reviewer | single | stakes=high |
| retro | learn | Parent | single | always |

The core blocks (intake, qtree, analyze-claims, synthesize, retro) cannot be `--drop`ped. If there is no `extract-*` at all, forge fails.

## Composition order

1. `norm_traits`: defaults for missing values, validation of enumerated values, quant↔tabular consistency.
2. Library matching (`distance`): mode 0.30, modality (Jaccard) 0.15, verifiability, stakes, and quant 0.10 each, the rest 0.05. If `≤0.25`, similar (→ fork recommended); otherwise novel.
3. Block selection: evaluate each block's `when` predicate + apply `--add/--drop`. The reasons for exclusion are recorded in the spec's `excluded`.
4. Dependency resolution: wildcards in `needs` such as `extract-*` are replaced with the selected blocks, and prerequisites that were not selected are silently omitted. If there is a cycle, it fails.
5. Parameter derivation (`derive_params`): lanes, batch_size (6|10), overlap_frac (0.15|0.25), kappa_min (0.6|0.7), min_independent (2|3), max_origin_share (0.5|0.4), saturation window (5|8), freshness_days, allowed_ctypes.
6. Budget trimming (`budget_tasks`): removed in the order qa-review → bias-audit → rival-hypotheses → workflow-critic → source-audit → timeline-build → compare-matrix (blocks that were `--add`ed are kept). **Trimming is risk-taking, so report the dropped blocks to the user.**
7. The saturation gate is removed when volume=small or mode=verify.
8. `--set key=value` (JSON value): a global parameter (`kappa_min=0.8`) or a block parameter (`scout.max_waves=1`, `extract-dual.batch_size=4`).

The estimate (`estimate.dispatch_tasks`) is for planning and is not a measurement (the assumptions about the number of sources and questions are recorded in the spec).

## Meaning of fanout

- `per_lane`: 1 task per lane · `candidate_batch`: groups new candidates into batches · `source_batch`: groups sources that have not yet been extracted and are normal (pii clear) into batches (for dual, overlapping sources go to both A and B, the rest are assigned crosswise A/B; the overlap is decided deterministically by the source id hash).
- `per_question`: 1 task per top-level question that has evidence (or claims), and a new task appears when the evidence count changes · `claim_batch`: groups unrefuted claims in order of strength · `per_data_question`: questions with a dataset whose kind∈measure|compare|trend|rank.
- Every fanout is a **data-driven lazy expansion**, so on reopen (a new wave) only new inputs are processed.
- **The input snapshot is made only once, at task creation time.** `reopen` does not touch tasks that have already been emitted (ready·dispatched·returned) and only newly expands the next wave. If the input of a planned task that has not yet started has gone stale (for example, the parent seeded sources with `source add`, or candidates were added), do not overwrite the files by hand; use `rlab refresh-inputs --block B [--dry-run]`: it cancels that block's open tasks and re-runs the block's own expansion (`expand_block`), so the inputs, contracts, and receipts are regenerated by exactly the same code as at creation time (new task ids; the old tasks' candidate assignments are released and re-batched, and an `inputs_refreshed` event and "old -> new" id output appear; `block_state` is unchanged). **All** open tasks must be `planned`, not manual, `attempts=0`, with `dispatched`/`begun` empty, no `dispatch_emitted` event, and no `staging/out/<T>.jsonl`; they must be in the same wave, and must not be a Parent block. If even one violates this (if any task was emitted, started, or retried, re-expanding would duplicate work already sent out), it is rejected with no change and points to `retry`, `unready`, and `reopen` (a new wave). If re-expanding produces no task at all (nothing to process), it is likewise rejected and nothing is changed. All changes are one transaction, the old task directories are deleted only after the commit, and on failure the DB and even the newly created directories are restored to their original state.

## Adding and modifying blocks (extending the catalog)

Add an entry to `assets/blocks.json`. Fields: `id, phase, role, fanout, kind(candidates|sources|evidence|claims|challenges|findings), needs[], when, gates[], soft_gates[], on_fail{gate:block}, params{}, purpose, goal, guide`. `when` syntax: `"always"` | `{"t":trait, eq|ne|in|has|gte|lte: v}` | `{"all":[..]}` | `{"any":[..]}` | `{"not":..}` (`gte/lte` use the trait's ordinal scale: stakes, noise, ethics, volume, volatility, verifiability, access). For a new role, add a candidate to `assets/routing.json`. If a new kind of collected row is needed, you must add an adder to `ingest.py` (schema hints are in `runtime.SCHEMA_HINTS`). Run `selftest.py` after the change. **Fixing the catalog does not affect workflows that are already stored** (the spec holds a copy of the block definitions).

## Operating a fork (when scope, access, or scale changes)

Before `--fork <id>`, first confirm with `ls workflows/<id>.json` that the file actually exists on disk. `wf match`/`wf list` read only the registry (sqlite) index, so a workflow that was previously retired (archived or deleted) still appears in the distance calculation. If you `--fork` in this state, the registry entry is alive but the file is missing, so it dies immediately with `FileNotFoundError`. If the file is missing, give up and compose a new one with `forge` (it is natural if there is no alternative even when that workflow is close in distance).

The workflow of a running run cannot be modified, so use `forge --traits t2.json --fork <parent> --name <new>` with a JSON of updated traits.
- A fork has `novel=false`, so **`workflow-critic` drops out** (its inclusion condition is novel or stakes=high). A design whose scale or approach has changed needs re-review, so revive it with `--add workflow-critic`. If you raise `access` to mixed/gated, `access-broker` (parent-only) is attached automatically.
- Match the question-count assumption (default 5) with `--set questions_est=<actual number of top-level questions>`, check the estimated task count with `forge --no-save`, and then save. If the user's stated target scale (task count) differs from the estimate, report the difference.
- A new run **does not automatically receive** the previous run's candidates, disposition table, or addendum. Copy what you need: copy the addendum and `critic_dispositions.md` as files; for scout candidates, export the `candidates` table of `ledger.sqlite` to JSONL, place it in `reports/`, and use it as reference for the new scout's seeds and the parent's `source add`. Do not modify the old run.

### When the user says they will continue the run in a new session (regardless of fork)
If the user requests "run in a new session, keep the existing session", in the current session only save the workflow, `init` (up to P3), and prepare inputs, and **do not execute (`next`).** Write a handoff document (`handoff-<run>.md`: state, user decisions, recommended order, cautions, change history) in the lab home, and present in chat a starting prompt to paste into the new session. Write permissions such as membership and cookies into the document as facts, but in the prompt put them as **the user's own permission statement**, so that the new session treats them as permission received directly from the user. If the permission conditions change, fix the brief, the task copies, the handoff document, and the prompt all together and leave a change history.

This pattern is not fork-only; it applies as is **also when you stop an already-init'ed run in the middle of P4 (e.g. while waiting on workflow-critic or access-broker) and hand it to the next session**. In that case the handoff document additionally contains: (a) concrete data from the previous run's conclusions that will be used as the verdict criteria for specific questions of this run (e.g. the list of comparison targets, the verdict table), quoted directly in the body so the next session does not have to find them again, and (b) one sentence distinguishing which questions of this run the user-approved operating policy applies to and with which questions it is a **separate axis** (e.g. a "risk acceptance decision" is irrelevant to judging compliance with the platform ToS, but affects the contextual explanation of the rights-attribution verdict). The next session copies this distinction as is into addendum.md so the subagents do not confuse the two questions.

### Parent direct-seed pattern (when dropping scout and re-evaluating fixed candidates)

If you only want to re-evaluate a candidate list already settled in a previous run (the discovery scope stays the same, only the verdict method is reinforced), block rediscovery with `--drop scout` and have the parent plant the candidates and sources directly with `rlab source add`. In this case you **must** keep the order below — if you break the order, source-audit and extract-single end up with empty inputs:
1. If you run `next --dispatch` once right after creating the run with `init`, tasks such as workflow-critic and source-audit are created first. At this point `tasks/<T>/input/sources.jsonl` is **empty because there are no sources yet.**
2. For a task created before all sources are planted, even if you return it to planned with `retry --task T`, the input snapshot is not regenerated automatically. The parent directly queries the `sources` table of `ledger.sqlite`, makes a JSONL, and manually overwrites `tasks/<T>/input/sources.jsonl`, and then re-dispatches (for the schema, refer to any `tasks/*/input/sources.jsonl` file of an existing run — it is one JSON object per line with the keys `id,kind,title,url,tier,stance,origin_group,lane,as_of,n_chars,text_path,sha256_12`, and the `N|` line numbers that `read_file` shows are for display only and are not in the actual file).
3. If you reverse the order and run `next --dispatch` **after planting all the sources**, this manual work is unnecessary. If tasks have already been created, recover with method 2.
4. `--drop scout` itself can **crash** `status` and `next`: the `on_fail` of `extract-single` (and other blocks) statically pins the target to reopen on soft gate failure to `scout`, as in `{"coverage": "scout", "saturation": "scout"}`; if scout is dropped, that block is not in the run's block list, so `bstate(run, "scout")` returns `None` and the engine dies with `TypeError: 'NoneType' object is not subscriptable` (both `status` and `next` are affected — this run stops completely). If the symptom appears, find the `on_fail` entries pointing to the dropped block in the run's `workflow.json` (`grep -n '"scout"' workflow.json`) and fix that block's `on_fail` to `{}`. This is not a structural change (adding or deleting blocks) but a bug fix that removes a dangling reference left by the drop, so it is an exception to the rule "do not modify the workflow.json of a running run". After the fix, a soft gate failure is simply recorded as a failure and left in limitations (you can proceed without reopen).

### Pattern for integrating vision (image) evidence into the text pipeline

If you add `media` to the modality, forge automatically opens a `media-transcripts` lane. Do not give the images themselves to subagents (it conflicts with the principle of not storing original media, and quote verification is based on text substrings so it does not fit images), and integrate in the following order:
1. The parent opens the image URLs directly (`vision_analyze`) and writes the observations, per account or post, as a **narrative text document** ("vision observation notes").
2. Register this document with `rlab source add` as a **plain text source** (unify the origin as `parent_vision_analysis`, etc. — since the observer is the single parent, do not split the origin per account to disguise them as independent sources).
3. extract-single and analyze-claims read, quote, and extract this document exactly like other text sources — you can use the existing quote-verification structure as is, without a vision model or passing images.
4. Register together a separate "sample manifest" document (an origin such as `parent://sample_manifest`) stating which image URLs of which posts were viewed and how many, so the extraction and analysis stages reflect the sample scope (N images per account) in judging evidence strength. An entity with 0 media must be distinguished as "unverifiable", not "no evidence" (do not assert non-existent content).
5. If a vision observation note **bundles multiple entities (accounts, etc.) in one document** (e.g. 15 accounts recorded section by section in one file), extract-single tends to **cram the verdicts for all entities into the `note` field of 1 evidence row, separated by semicolons**, because the evidence schema has only one quote/entity per row (the quote and entity are filled in only for the first entity and the other 14 exist only inside the note text). As a result, the `per_question` analyze-claims cannot unpack the packed note again and produces only 1–2 claims. **If it is a wave to be newly dispatched**, the problem is solved immediately by stating in the `context` of delegate_task: "if per-entity verdicts are packed in the note field, parse them and make a separate claim/evidence row per entity" (the wording actually used in this workflow). The problem is a **task already committed as `VERIFIED`** — for the recovery procedure in that case (the parent's direct INSERT, advancing the nid counter, strength enum constraint), refer to the corresponding section of SKILL.md Pitfalls.

## Stored spec (`workflows/<name>-vN.json|md`)

`traits, params, blocks[] (needs resolved, why included), excluded[], estimate, overrides{add,drop,set}, warnings, novel, parent, forged`. A fork inherits the parent's overrides and creates a new version (lineage tracking).