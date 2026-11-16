# Playbooks: Examples of Real forge Results

Below are real compositions produced by `rlab forge` (with an empty library, `novel=true`; the estimated task count is a planning value assuming the source scale and 5 questions). Even in the same domain, the workflow differs if the direction differs. All values are starting points and do not replace the P1 judgment.

| case | key traits | block composition (execution order) | estimate |
|---|---|---|---|
| **Biographical verification of a person · describe** | modality=media+social+web, interpretive, stakes=low, noise=med, ethics=personal_data, access=mixed, temporal | intake, qtree, workflow-critic, access-broker, scout, collect, source-audit, **privacy-gate**, **extract-dual**, analyze-claims, timeline-build, adversary, bias-audit, synthesize, retro | ~47 |
| **OSS technology · compare** | web+code+tabular, checkable, stakes=med, volatility=fast, quant | intake, qtree, workflow-critic, scout, collect, **extract-single**, **data-analyze**, analyze-claims, **compare-matrix**, adversary, synthesize, retro | ~40 |
| **Policy · explain (high stakes)** | legal+academic+web, mixed, stakes=high, noise=high, volume=large, temporal | intake, qtree, workflow-critic, scout, collect, source-audit, extract-dual, analyze-claims, timeline-build, **rival-hypotheses**, adversary, bias-audit, synthesize, **qa-review**, retro | ~121 |
| **Market · forecast** | web+tabular, checkable, stakes=med, volume=small, volatility=fast | intake, qtree, workflow-critic, scout, collect, extract-single, data-analyze, analyze-claims, **base-rates**, adversary, synthesize, retro | ~22 |

Interpretation:
- For biographical verification of a person, *consistency of perception and description* matters more than fact checking, so dual coding (κ) and bias audit are central, and blocking non-public personal details (privacy-gate) is mandatory. Login/membership sources are handled only by the parent.
- For OSS comparison, the correct answer lies externally, so a single coder plus machine verification is enough; benchmarks are brought in as datasets and kept as SQL-reproducible evidence. The comparison matrix is the core of the deliverable.
- High-stakes policy interpretation turns on rival hypotheses and independent QA, and the cost rises sharply. If you set a cap with `budget_tasks`, some blocks are trimmed, but this is reported, so the user decides whether to accept the risk.
- For market forecasting, base-rates is the starting point, and forecast claims (ctype=forecast) are allowed only at moderate or below.

To reproduce it for real, copy `assets/traits.example.json`, change the values, and preview with `forge --no-save`.
