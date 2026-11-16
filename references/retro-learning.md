# Retro: How Results Feed Back into the Library, and Its Limits

## What is stored (`<lab home>/registry.sqlite`, `workflows/`)

- `workflows`: id (`name-vN`), parent (lineage), domain/direction labels, traits, spec path.
- `runs`: run_id, workflow_id, metrics (JSON), `score` (user rating 0-5, optional), `proxy` (process metric 0-1).
- `lessons`: `lesson` (a lesson written by a person) and `mutation` (a rule-based mutation suggestion); tags = mode, domain, direction, and user tags.

## How the next forge uses it

`forge`/`wf match` compute the traits distance to the stored workflows (on a tie, the one with higher fitness wins). If no candidate has distance ≤0.25, the result is marked `novel` and workflow-critic is turned on. Lessons of the matched workflow, and lessons carrying the same mode/domain/direction tags, are printed as information. **Workflows are not modified automatically.** The parent reads the suggestions and creates a new version with `forge --fork <id> --set/--add/--drop`.

## What fitness is (honestly)

- If `score` (user rating) exists, use `score/5`; otherwise use `proxy`; then average.
- `proxy` = 0.35×(gate pass ratio; waived counts as 0.5) + 0.25×(claim support score: supported 1, partial 0.6, contested 0.3) + 0.2×(1−5×reject rate) + 0.2×(1−rework rate). **It is a health indicator of the execution process, not of the truthfulness of the results.** When there are few runs, do not use it as the basis for ranking (at most a tiebreaker when choosing between two candidates with equal similarity but different scores).
- Do not claim effects such as accuracy or cost savings before they are measured. Cost currently records only the task count and rework rate (tokens and money are not recorded).

## Mutation suggestion rules (`runtime.suggestions`)

coverage failure → add scout lanes / raise max_waves · kappa failure → label_defs, lower batch_size, raise overlap_frac · saturation not reached → raise max_waves · independence failure → add source-audit · challenge incomplete → lower adversary batch · reject rate >10% → strengthen the contract, upgrade the model · rework rate >30% → upgrade routing for that role · contested present → add rival-hypotheses and bias-audit.

## Criteria for writing lessons

Write not a one-off fact but a **reusable rule + the why** in one line (e.g. "Use the community lane only as tier 4 and exclude it from the coverage count: re-quotes of promotional posts were counted as independent sources"). If you attach tags other than domain/direction with `--tag`, it also matches in other workflows. Reflect reusable procedure improvements in this skill (`SKILL.md`, `references/`), and keep run state in the ledger.
