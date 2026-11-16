# Crew: Roles, Routing, Contracts, Receipts

## Roles

| role | what it does | principle |
|---|---|---|
| Scout | source candidates only (no body-text extraction) | parallel per lane; exclude URLs that overlap with ones already collected |
| Collector | saves the original text as text + sources row | no alteration, mark PII, tabular data is `kind=dataset` |
| Extractor A/B | codebook-based evidence extraction | **A and B are different model families**, and do not know each other's results or hypotheses |
| DataAnalyst | computes quantitative questions with DuckDB SQL, rerunnable SQL evidence | create the result hash with `rlab sql --hash` before submitting |
| Analyst | writes claims looking at **evidence IDs only** | no reading of full source text (blocks confirmation bias) |
| Adversary | refutation: first defines and then looks for the material that should exist if the claim were wrong | **a different family from the Analyst**; "could not find it" is also a result |
| Auditor | audits the source pool and ledger for bias and independence | statistics-centered |
| Critic / Reviewer | critique of the workflow / review of deliverable sentence↔evidence correspondence | a different viewpoint from the parent (recommended: a different family) |
| Parent | decomposition, verdicts, writing the deliverable, synthesis | machine verification of citations, SQL, and receipts is done by `load` |

## Routing

`assets/routing.json` is a role→option candidate list and is **not evidence of what is active**. In every run, compare against the actual active list with `next --available "<current delegate_task option names>"` (if absent, `option` is left empty and the reason is printed; do not silently substitute a nonexistent name). Promotion is done only with `retry --option`, after the failure cause is confirmed to be a model limit. The model that was actually run is verified with the manifest-check procedure of the `subagent-orchestration` skill.

## Anatomy of a contract

`next` generates `tasks/<T>/contract.md` and `tasks/<T>/input/*` for each task. The contract is self-contained: goal, brief summary, question tree, inputs (absolute path + sha), method guidance, one output file, row schema and examples, required procedure (begin → write → check), and prohibited items. Send **only a pointer** through `delegate_task` (saves parent tokens; the child reads the contract on the same filesystem). If the child's environment cannot read files, put the full text into the payload with `next --full`.

**Dispatch state and ASCII payload (E2)**: `next --dispatch` turns a task into `ready` (only placed in the payload; delegation unconfirmed) and leaves a `dispatch_emitted` event and `staging/dispatch_NNN.json` (`tasks.dispatched` is left empty). A `ready` task is not emitted again, `next` lists it as `[EMITTED, NOT CONFIRMED]`, and it counts as in progress in the `max_parallel` and `max_per_option` calculations. After actually calling `delegate_task`, confirm `ready → dispatched` with `rlab dispatched --payload dispatch_NNN.json` (or repeated `--task T`) (the child's `begin` also confirms it; already dispatched/returned pass silently, and if even one is in another state the whole thing is rejected). If you decide not to delegate, revert `ready → planned` with `rlab unready --payload ...` (or `--task`) (attempts and receipt unchanged, `dispatch_cancelled` event; `retry` is for an attempt that was delegated but failed: running `retry` in the `ready` state records it as delegated, so failures where the child could not `begin`, such as a 402 at delegation time, are also included in the billing-stop determination). The `goal`/`context` of the payload are **fixed ASCII sentences** containing only the task id, block, role, and the absolute path of `contract.md`, so do not rewrite them by hand and pass the JSON printed by `next` as is (the Korean purpose/goal exists only in `contract.md` and the payload `meta`, and `meta` is not sent through `delegate_task`). If you need the full text, use `next --full`. This guarantee holds only if the run id and the `RLAB_HOME` path are ASCII; otherwise `next` warns on stderr. `next` without `--dispatch` writes only to `dispatch_dryrun.json`.

**Run addendum (addendum, E6)**: The contract contains only the first 1400 characters of the brief, so write operating rules decided later (collection boundaries, origin definitions, per-question coding rules, etc.) in `addendum.md` in the run directory. When `next` builds the payload, it is automatically included if `addendum.md` exists: the absolute path of the addendum and one ASCII sentence saying "read together; if it conflicts with the contract, the addendum's prohibitions and restrictions take precedence" are appended to the default ASCII `context` pointer, and `next --full` appends the addendum body after the contract together with the same title and precedence sentence (`goal` is unchanged). The same one-line notice is also put into any new contract made while an addendum already exists. If there is no addendum, the payload is byte-for-byte the same as before. The parent does not need to hand-insert the addendum path into the dispatch payload or write a pointer in the brief (the addendum path is derived from the run directory, so it is ASCII as long as `RLAB_HOME` is ASCII).

## Receipts and machine verification

1. The child runs `begin --task T` → `receipt = sha256(run_key | task | input_sha)[:12]` (run_key exists only in the ledger and cannot be guessed).
2. The child's only output, `staging/out/T.jsonl`, has as its first line `{"_meta":{"task","receipt","n_rows"}}`.
3. The child does a dry run with `check` (prints rejection reasons with row numbers, without committing) → fixes until `CHECK OK`.
4. The parent runs `load`: checks receipt and n_rows → per-row checks of schema, quote match against source text, SQL re-run hash, codebook labels, ctype ceiling, and evidence existence. If the reject rate ≤ `max_reject_rate` (5%), commit; if exceeded, roll back everything (`status=failed`, reject reasons in the `rejects` table).
5. `--accept-rejects` discards rejected rows and commits only the rest (record the case in limitations). `--force-unproven` is the exception where the parent accepts output without a receipt as unproven, and `unproven` is left in the task notes.

## Failure classification

**Empty result**: when a child intentionally reports 0 rows, write `"n_rows":0,"empty":true,"blocker":"reason"` in meta (otherwise an empty file fails with `no valid rows`). The blocker is left in the task notes. In an **environment where re-delegation is impossible**, the parent may perform the contract directly in order (begin→write→check→load), but since this is not an independent model review, record it in limitations. `--available ""` (an empty list) is treated as "no active option" and the option is left empty. Findings mixed into blocks such as claims and evidence take the form `{"kind":"findings","type":"evidence_gap",...}`.

| symptom | cause class | action |
|---|---|---|
| PROOF FAILED | fabricated without execution, or the file was truncated | `retry`; if repeated, upgrade that role's model |
| reject rate exceeded: many `not found verbatim` | model reconstructed the quote | emphasize "copy verbatim" in the contract, shrink the batch, a higher model if needed |
| `label not in codebook` | codebook unclear | reinforce `labels`/`label_defs` in questions, then a new task |
| `ctype not allowed` | direction ceiling violated | do not change the direction; instruct to lower the claim type |
| tool, permission, or network error | environment | fix the environment or report a blocker (do not hide it with a model upgrade) |

The default for retry is one cause fix followed by re-evaluation. If the same structural failure repeats, stop and fix the contract or upgrade.

**Auto-classification, concurrency, stop (E3)**: `retry` classifies the reason (`--note`, or the previous notes if absent) by pattern only, records `failure_class/failure_kind/class_source` in the retry event, and prepends a tag such as `[env:billing]` to the notes only when the classification is certain (the original text is not changed). Classes: `env` (billing = HTTP 402 / credits exhausted, rate_limit = HTTP 429 / usage limit, auth = HTTP 401, network = timeout / 5xx) / `output` (rejected, proof — from the text alone it is unknown whether it is a contract defect or a model limit) / `unknown` (no tag). `env` is not counted as a model failure and is not grounds for promotion. If a person has confirmed the cause, `retry --cause env|contract|model` takes precedence over the pattern. `next` limits concurrent execution per option (ready+dispatched+returned) to `params.max_per_option` (default 3); tasks that hit the limit remain planned and are reported as `capped` (in the CLI, a slot-waiting list) (tasks without an option have no limit; `max_parallel` is kept separately). If there are 2 or more unverified tasks of the same (block, wave) and all of their last retries are `env/billing` of the same option, the meta key `halt` is set and `next` emits no dispatch and prints `[HALT]` (a single task, 429, or 401 does not stop it). After the user tops up or chooses another provider, release it with `rlab resume --reason "..."` (records a `resume` event; an error if there is no active stop).

## Security limits (honest scope)

- The receipt is a device that filters out **output fabricated without execution**. A malicious child sharing the same filesystem could forge it by reading run_key from `ledger.sqlite`. That is, it is for accident prevention, not an adversarial control. Quote and SQL verification operate independently regardless of forgery.
- A child-supplied `path` is allowed only under `staging/incoming/` (blocks pulling secret files into the ledger). Only the parent's `source add` accepts arbitrary paths.
- Investigations needing serious security controls require separate isolation that does not share the run directory with children (Docker, a copied workspace).
