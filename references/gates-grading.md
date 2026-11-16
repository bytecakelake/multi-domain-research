# Evidence Grades, Claim Status, Gates

## Source tier

1 = original/primary (raw material, outputs produced directly by the party, official primary records) · 2 = authoritative secondary (peer-reviewed papers, official documents, reporting with editorial control) · 3 = derived/aggregated (wikis, summaries, re-quotes) · 4 = opinion/community. **Writings that re-quote the same origin must have the same `origin_group`** (independence is counted by the number of origin_groups, and source-audit catches errors). Wikis and community posts are evidence that "someone sees it that way"; to promote them to fact, primary material is needed.

## Claim status (automatically recomputed)

| status | condition (min_independent = 2, 3 if stakes=high) |
|---|---|
| supported | independent origin_groups of supporting evidence ≥ min_independent AND best tier ≤ 2 |
| partial | (best tier ≤ 2 and at least 1 evidence) OR (independent origins ≥ min_independent regardless of tier) |
| weak | has supporting evidence but does not meet the conditions above |
| contested | has an unresolved (open) contradiction (counter-evidence found by the adversary, or counter_evidence linked by the analyst) |
| unsupported | no valid supporting evidence |

Do not delete statuses that cannot be settled from the deliverable. Keep them as labels (confirmed / partial / unconfirmed / refuted). ctype ceiling: strong only for fact/measurement.

## Gates

| gate | failure condition | default threshold | usual remedy |
|---|---|---|---|
| receipts | a proof_failed task exists | 0 | retry |
| reject_rate | block cumulative reject rate exceeded | 5% | adjust contract/batch |
| kappa | Cohen's κ below threshold on double-coded overlap units (source×question). If fewer than 5 units, `na` (cannot be derived) | 0.6 (high 0.7) | strengthen label_defs, recode once, and if still below, exclude that question's verdict from the analysis |
| coverage | independent origin_groups of a top-level question < min_independent, or no tier ≤2 evidence (including sub-question evidence) | 2 (high 3) | soft: automatic scout reopen (up to max_waves) |
| saturation | new codes (questions, labels, entities) introduced by the most recent window sources exceed the threshold | ≤1 / 5 sources | soft: scout reopen |
| independence | evidence share of the largest origin_group exceeded (`na` if fewer than 6 evidence) | 50% (noise high 40%) | soft: reinforce counter-view and source-audit |
| claim_support | a strong claim that is not supported, or zero claims | 0 | reinforce evidence (new analyst wave) or `rlab downgrade --claim K.... --strength moderate --reason "..."` (parent only; only lowering strength is allowed; the reason is recorded in the claim scope and audit log). Do not cover it with `waive` |
| challenge | claims of strength ≥ moderate with no refutation record | 100% | add adversary task |
| contradictions | open contradiction on a claim of moderate or higher | 0 | `resolve --status resolved|disclosed` (reason required) |
| citation | no deliverable, a nonexistent `[K....]` citation, zero citations, or no Limitations section (accepted if the heading line contains any of `Limitations`, `한계`, or `제한` — numbered and Korean headings such as `## 3. 한계` or `## 4. 연구의 한계와 제언` are allowed; 한계 = "limitations", 제한 = "restrictions", 연구의 한계와 제언 = "limitations of the study and recommendations"). **Only a structural check is done** (per-sentence citation presence and semantic match are not guaranteed; `uncited_lines` is informational) | — | fix the deliverable, manually review sentence↔claim |
| pii | a source with pii_status=flagged exists | 0 | `source drop` / `set --pii clear` |

Hard gates block block completion; soft gates end in a reopen or a limitations entry. `waive` is possible for every gate but always appears in the `report` limitations. Thresholds are workflow `params` and are changed with `--set`. The defaults are empirical starting points, not values calibrated over many runs.

## Resolving contradictions

Only when the challenge verdict is `weakened`/`refuted` are a `refutes` link and an open contradiction created. `stands`/`inconclusive` do not create a contradiction; the referenced evidence ids are preserved in the `[rlab challenge-context v1] {"evidence_ids": [...]}` line at the end of the challenge note, and `inconclusive` appears in the limitations. Therefore do not use bulk classification by verdict (a claim_id→verdict dictionary) (if a claim has several challenges, it gets overwritten). Resolve open contradictions one by one with `rlab resolve --id X.... --status resolved|disclosed --note "..."`, and process several at once with `rlab resolve --file F.jsonl` (per line `{"id":"X0001","status":"resolved|disclosed","note":"reason"}`). The file is applied in one transaction after everything is validated, and if even one line is wrong (JSON error, unknown id, invalid status, duplicate id), nothing is changed and the line number is reported (cannot be combined with `--id/--status/--note`). The original provenance note is kept and the reason is recorded as a `contradiction_resolved` event.
