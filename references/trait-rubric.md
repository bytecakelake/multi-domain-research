# Traits Rubric: Describing Domain and Direction by Properties, Not Numbers

forge picks blocks by **what properties this investigation has**, not by "which domain is it". Even for an unfamiliar domain, if you can answer the questions below, a workflow comes out. The `domain` and `direction` strings are free-form labels (for library search and lesson tags) and are not used for block selection.

## Fields

| trait | values | question for judging |
|---|---|---|
| `mode` (direction) | explore, describe, compare, explain, evaluate, verify, forecast, design | Is the deliverable a *map of the terrain* / a *description of a phenomenon* / a *comparison of alternatives* / a *causal explanation* / a *good-or-bad judgment* / a *fact check* / a *forecast of the future* / a *design proposal*? Pick only one. |
| `modality` | web, academic, social, tabular, code, media, legal, human_subject, local (multiple) | In what kinds of material does the evidence live? Each one creates one collection lane. `tabular` turns on quant and the SQL analysis lane. `local` is an investigation that uses only files and internal material the user already has (no web exploration). |
| `verifiability` | checkable, mixed, interpretive | Does the correct answer exist externally (checkable), or does interpretation decide the verdict (interpretive)? If interpretive, blind dual coding and κ are turned on. |
| `stakes` | low, med, high | Is the cost of a wrong conclusion lost time (low) / lost money or reputation (med) / irreversible, safety, or legal (high)? If high, critic review, rival hypotheses, independent QA, κ 0.7, and 3 independent sources apply. |
| `volume` | small (~20 sources), medium (~80), large (~250) | Target source scale. Used for budget estimation, batch size, saturation window, and reopen limit. |
| `volatility` | static, slow, fast | How quickly does the correct answer go stale? If fast, the freshness period (90 days) goes into the refutation contract. |
| `noise` | low, med, high | How much promotion, manipulation, re-quote amplification, and SEO spam is mixed in? If med or higher, source audit, bias audit, and refutation are turned on. |
| `ethics` | none, personal_data, sensitive, safety_critical | Are personal information, sensitive information, or safety issues involved? If personal_data or higher, privacy-gate is turned on. |
| `access` | open, mixed, gated | Are login or membership sources needed? If mixed/gated, the parent-only access-broker is turned on (credentials are not given to children). |
| `quant` | true/false (if omitted, whether tabular) | Is there a question whose answer only comes out by computing numbers or table data? |
| `temporal` | true/false | Is time order or the point of change central to the answer? If on, timeline-build is added. |
| `budget_tasks` | integer or null | Upper limit on subagent tasks. If the estimate exceeds it, less important blocks are trimmed first and a warning is issued. |

## Reasoning ceiling set by direction (mode)

The allowed claim types (`allowed_ctypes`) set the limit and are automatically rejected at load time. The `strong` strength is possible only for fact/measurement.

| mode | allowed ctype | blocks turned on by the direction |
|---|---|---|
| explore, describe | fact, measurement, interpretation | (defaults only) · saturation reopen |
| compare | + inference | compare-matrix, counter-view lane |
| explain | + inference | rival-hypotheses, adversary, dual coding, counter-view |
| evaluate | + inference | compare-matrix, adversary, dual coding, counter-view |
| verify | fact, measurement, inference | rival-hypotheses, adversary, counter-view (no saturation gate) |
| forecast | + forecast | base-rates |
| design | fact, measurement, interpretation, inference | (defaults only) |

## When you meet a new domain (7 questions)

Ask the user or infer from the brief. If you don't know, do not guess: set it to the more costly side and write down the rationale.
1. What is the deliverable, and who uses it for which decision? (→ mode, stakes)
2. In what form of material does the evidence live? (→ modality, quant)
3. Does the correct answer exist externally, or is it interpretation? (→ verifiability)
4. What is the most trustworthy source of first priority, and how easily is it obtained? (→ access, tier ladder, coverage criteria)
5. What are the pitfalls in this field? Promotion, re-quotes, bias, survivorship bias (→ noise, counter-view)
6. How quickly does the correct answer change? (→ volatility, temporal)
7. What information must not be handled? (→ ethics, the brief's prohibited scope)

After judging, leave a one-line rationale next to the traits file (or in the brief) so that at retro time you can find a trait that was set wrongly.
