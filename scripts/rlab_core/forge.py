"""Workflow forge: domain/direction traits -> selected blocks -> parameterised workflow spec."""
from __future__ import annotations

import json
import math

from .core import ASSETS, die, now

MODALITIES = ["web", "academic", "social", "tabular", "code", "media", "legal", "human_subject", "local"]
MODES = ["explore", "describe", "compare", "explain", "evaluate", "verify", "forecast", "design"]
SCALES = {
    "stakes": ["low", "med", "high"],
    "noise": ["low", "med", "high"],
    "ethics": ["none", "personal_data", "sensitive", "safety_critical"],
    "volume": ["small", "medium", "large"],
    "volatility": ["static", "slow", "fast"],
    "verifiability": ["checkable", "mixed", "interpretive"],
    "access": ["open", "mixed", "gated"],
}
DEFAULTS = {
    "domain": "", "direction": "", "modality": ["web"], "verifiability": "mixed", "volume": "medium",
    "volatility": "slow", "noise": "low", "ethics": "none", "access": "open", "quant": None,
    "temporal": False, "mode": "describe", "stakes": "med", "budget_tasks": None,
}
# Direction (inference mode) -> claim types the run may assert. strong strength is limited to fact/measurement.
CTYPES = {
    "explore": ["fact", "measurement", "interpretation"],
    "describe": ["fact", "measurement", "interpretation"],
    "compare": ["fact", "measurement", "interpretation", "inference"],
    "explain": ["fact", "measurement", "interpretation", "inference"],
    "evaluate": ["fact", "measurement", "interpretation", "inference"],
    "verify": ["fact", "measurement", "inference"],
    "forecast": ["fact", "measurement", "inference", "forecast"],
    "design": ["fact", "measurement", "interpretation", "inference"],
}
LANE_DEFS = {
    "web": [("web-primary", "Official/primary web sources: official sites, original documents, announcements, primary records"),
            ("web-independent", "Independent reporting, analysis, reviews: third-party sources, not the parties involved")],
    "academic": [("academic", "Papers and academic DBs. Find review papers first, then follow citations")],
    "social": [("community", "Forums, communities, comments. Mark as tier 4 and use only as evidence of public opinion/perception")],
    "tabular": [("datasets", "Public datasets, statistics portals, API dumps (collected as kind=dataset)")],
    "code": [("repos", "Repositories, release notes, issues, benchmark code")],
    "media": [("media-transcripts", "Original captions/transcripts of video and audio")],
    "legal": [("statutes-cases", "Original statutes, case law, administrative documents")],
    "human_subject": [("firsthand", "Firsthand statements from the parties: interviews, self-descriptions")],
    "local": [("local-corpus", "Local material the user already has (files, notes, internal documents). Candidates come only from the given paths, with no web exploration")],
}
COUNTER_LANE = ("counter-view", "Deliberately seek opposing views, criticism, and failure cases (to block confirmation bias)")
TRIM_ORDER = ["qa-review", "bias-audit", "rival-hypotheses", "workflow-critic", "source-audit", "timeline-build", "compare-matrix"]
DIST_W = {"mode": 0.30, "modality": 0.15, "verifiability": 0.10, "stakes": 0.10, "quant": 0.10,
          "volatility": 0.05, "noise": 0.05, "volume": 0.05, "ethics": 0.05, "access": 0.05}


def load_catalog() -> dict:
    return json.loads((ASSETS / "blocks.json").read_text(encoding="utf-8"))


def norm_traits(raw: dict | None) -> dict:
    t = dict(DEFAULTS)
    for k, v in (raw or {}).items():
        if k.startswith("_") or k not in DEFAULTS:
            continue
        t[k] = v
    if isinstance(t["modality"], str):
        t["modality"] = [t["modality"]]
    t["modality"] = list(dict.fromkeys(t["modality"]))
    for m in t["modality"]:
        if m not in MODALITIES:
            die(f"unknown modality '{m}' (allowed: {MODALITIES})")
    for k, sc in SCALES.items():
        if t[k] not in sc:
            die(f"trait {k}='{t[k]}' invalid (allowed: {sc})")
    if t["mode"] not in MODES:
        die(f"trait mode='{t['mode']}' invalid (allowed: {MODES})")
    if t["quant"] is None:
        t["quant"] = "tabular" in t["modality"]
    if t["quant"] and "tabular" not in t["modality"]:
        t["modality"].append("tabular")
    t["temporal"] = bool(t["temporal"])
    t["quant"] = bool(t["quant"])
    return t


def _leaf(node: dict, ctx: dict) -> bool:
    key = node["t"]
    v = ctx.get(key)
    if "eq" in node:
        return v == node["eq"]
    if "ne" in node:
        return v != node["ne"]
    if "in" in node:
        return v in node["in"]
    if "has" in node:
        return node["has"] in (v or [])
    sc = SCALES.get(key)
    if sc is None or v not in sc:
        return False
    i = sc.index(v)
    if "gte" in node:
        return i >= sc.index(node["gte"])
    if "lte" in node:
        return i <= sc.index(node["lte"])
    return False


def eval_when(node, ctx: dict) -> bool:
    if node == "always" or node is True:
        return True
    if "all" in node:
        return all(eval_when(n, ctx) for n in node["all"])
    if "any" in node:
        return any(eval_when(n, ctx) for n in node["any"])
    if "not" in node:
        return not eval_when(node["not"], ctx)
    return _leaf(node, ctx)


def pred_text(node) -> str:
    if node == "always" or node is True:
        return "always included"
    if "all" in node:
        return " and ".join(pred_text(n) for n in node["all"])
    if "any" in node:
        return " or ".join(pred_text(n) for n in node["any"])
    if "not" in node:
        return "NOT(" + pred_text(node["not"]) + ")"
    op = next(k for k in ("eq", "ne", "in", "has", "gte", "lte") if k in node)
    sym = {"eq": "=", "ne": "≠", "in": "∈", "has": "∋", "gte": "≥", "lte": "≤"}[op]
    return f"{node['t']}{sym}{node[op]}"


def derive_lanes(t: dict) -> list[dict]:
    lanes = []
    for m in t["modality"]:
        for name, desc in LANE_DEFS[m]:
            lanes.append({"name": name, "desc": desc})
    if t["noise"] == "high" or t["mode"] in ("compare", "evaluate", "verify", "explain"):
        lanes.append({"name": COUNTER_LANE[0], "desc": COUNTER_LANE[1]})
    return lanes


def derive_params(t: dict) -> dict:
    high = t["stakes"] == "high"
    interp = t["verifiability"] == "interpretive"
    return {
        "max_parallel": 4,
        "lanes": derive_lanes(t),
        "batch_size": 6 if (interp or high) else 10,
        "overlap_frac": 0.25 if high else 0.15,
        "kappa_min": 0.7 if high else 0.6,
        "min_independent": 3 if high else 2,
        "max_origin_share": 0.4 if t["noise"] == "high" else 0.5,
        "max_reject_rate": 0.05,
        "saturation": {"window": 8 if t["volume"] == "large" else 5, "max_new": 1},
        "freshness_days": {"fast": 90, "slow": 365}.get(t["volatility"]),
        "allowed_ctypes": CTYPES[t["mode"]],
        "challenge_min_strength": "moderate",
        "sources_est": {"small": 20, "medium": 80, "large": 250}[t["volume"]],
        "questions_est": 5,
    }


def _match_need(need: str, chosen_ids: list[str]) -> list[str]:
    if need.endswith("*"):
        return [i for i in chosen_ids if i.startswith(need[:-1])]
    return [need] if need in chosen_ids else []


def estimate(blocks: list[dict], params: dict) -> dict:
    n_src = params["sources_est"]
    nq = params["questions_est"]
    lanes = len(params["lanes"])
    per = {}
    for b in blocks:
        bp = {**params, **b.get("params", {})}
        f = b["fanout"]
        if b["role"] == "Parent":
            per[b["id"]] = 0
        elif f == "single":
            per[b["id"]] = 1
        elif f == "per_lane":
            per[b["id"]] = lanes
        elif f == "candidate_batch":
            per[b["id"]] = math.ceil(n_src * 1.4 / bp.get("batch", 8))
        elif f == "source_batch":
            base = math.ceil(n_src / bp["batch_size"])
            extra = math.ceil(n_src * bp["overlap_frac"] / bp["batch_size"]) if bp.get("dual") else 0
            per[b["id"]] = base + extra
        elif f == "per_data_question":
            per[b["id"]] = max(1, nq // 2)
        elif f == "per_question":
            per[b["id"]] = nq
        elif f == "claim_batch":
            per[b["id"]] = math.ceil(nq * 5 / bp.get("batch", 8))
        else:
            per[b["id"]] = 1
    total = sum(per.values())
    return {"dispatch_tasks": total, "per_block": per,
            "basis": f"sources~{n_src}, questions~{nq}, lanes={lanes}; planning estimate, not a measurement"}


def _topo(blocks: list[dict]) -> list[dict]:
    ids = [b["id"] for b in blocks]
    by = {b["id"]: b for b in blocks}
    done: list[str] = []
    pending = list(ids)
    while pending:
        progressed = False
        for i in list(pending):
            if all(n in done for n in by[i]["needs"]):
                done.append(i)
                pending.remove(i)
                progressed = True
        if not progressed:
            die(f"dependency cycle among blocks: {pending}")
    return [by[i] for i in done]


def _apply_sets(spec_params: dict, blocks: list[dict], sets: list[str]) -> None:
    for s in sets:
        if "=" not in s:
            die(f"--set expects key=value, got '{s}'")
        k, v = s.split("=", 1)
        try:
            val = json.loads(v)
        except Exception:  # noqa: BLE001
            val = v
        head, _, rest = k.partition(".")
        blk = next((b for b in blocks if b["id"] == head), None)
        target, key = (blk.setdefault("params", {}), rest) if blk and rest else (spec_params, k)
        parts = key.split(".")
        for p in parts[:-1]:
            target = target.setdefault(p, {})
        target[parts[-1]] = val


def forge(traits_raw: dict | None, parent: dict | None = None, add=(), drop=(), sets=(),
          name: str | None = None, novel: bool | None = None) -> dict:
    if traits_raw is None and parent is None:
        die("forge needs --traits (or --fork <workflow>)")
    t = norm_traits(traits_raw if traits_raw is not None else parent["traits"])
    ov = {"add": [], "drop": [], "set": []}
    if parent:
        for k in ov:
            ov[k] = list(parent.get("overrides", {}).get(k, []))
    ov["add"] = list(dict.fromkeys(ov["add"] + list(add)))
    ov["drop"] = list(dict.fromkeys(ov["drop"] + list(drop)))
    ov["set"] = ov["set"] + list(sets)
    ctx = dict(t)
    ctx["novel"] = True if novel is None else bool(novel)

    cat = load_catalog()["blocks"]
    cat_ids = {b["id"] for b in cat}
    for x in ov["add"] + ov["drop"]:
        if x not in cat_ids:
            die(f"unknown block '{x}' (catalog: {sorted(cat_ids)})")

    chosen, excluded, why = [], [], {}
    for b in cat:
        ok = eval_when(b["when"], ctx)
        reason = pred_text(b["when"])
        if b["id"] in ov["drop"]:
            if b.get("core"):
                die(f"block '{b['id']}' is core and cannot be dropped")
            ok, reason = False, "excluded by user (--drop)"
        if b["id"] in ov["add"]:
            ok, reason = True, "added by user (--add)"
        if ok:
            chosen.append(json.loads(json.dumps(b)))
            why[b["id"]] = reason
        else:
            excluded.append({"id": b["id"], "reason": f"condition not met: {reason}" if b["id"] not in ov["drop"] else reason})

    params = derive_params(t)
    trimmed: list[str] = []
    warnings: list[str] = []

    def finalize(cs: list[dict]) -> list[dict]:
        ids = [b["id"] for b in cs]
        out = []
        for b in cs:
            nb = dict(b)
            nb["needs"] = [m for need in b.get("needs", []) for m in _match_need(need, ids)]
            nb["why"] = why[b["id"]]
            nb.pop("when", None)
            nb.setdefault("kind", None)
            nb.setdefault("soft_gates", [])
            nb.setdefault("on_fail", {})
            nb.setdefault("params", {})
            out.append(nb)
        return _topo(out)

    blocks = finalize(chosen)
    if t["budget_tasks"]:
        est = estimate(blocks, params)["dispatch_tasks"]
        for tid in TRIM_ORDER:
            if est <= t["budget_tasks"]:
                break
            if any(b["id"] == tid for b in chosen) and tid not in ov["add"]:
                chosen = [b for b in chosen if b["id"] != tid]
                trimmed.append(tid)
                blocks = finalize(chosen)
                est = estimate(blocks, params)["dispatch_tasks"]
        if est > t["budget_tasks"]:
            warnings.append(f"estimate {est} exceeds budget {t['budget_tasks']}: lower volume or reduce questions")
    for tid in trimmed:
        excluded.append({"id": tid, "reason": "trimmed for exceeding budget"})
        why.pop(tid, None)

    ids = [b["id"] for b in blocks]
    if not any(i.startswith("extract-") for i in ids):
        die("workflow has no extract-* block")
    for b in blocks:
        if t["volume"] == "small" or t["mode"] == "verify":
            b["soft_gates"] = [g for g in b["soft_gates"] if g != "saturation"]
        if b["id"] == "scout":
            b.setdefault("params", {})["max_waves"] = 2 if t["volume"] == "small" else 3
    _apply_sets(params, blocks, ov["set"])
    est = estimate(blocks, params)

    spec = {
        "schema": 1,
        "name": name or (parent or {}).get("name") or f"{t['domain'] or 'general'}-{t['mode']}",
        "parent": (parent or {}).get("id"),
        "traits": t,
        "params": params,
        "phases": load_catalog()["phases"],
        "blocks": blocks,
        "excluded": excluded,
        "estimate": est,
        "overrides": ov,
        "warnings": warnings,
        "novel": ctx["novel"],
        "forged": now(),
    }
    return spec


def distance(a: dict, b: dict) -> float:
    a, b = norm_traits(a), norm_traits(b)
    d = DIST_W["mode"] * (a["mode"] != b["mode"])
    ma, mb = set(a["modality"]), set(b["modality"])
    d += DIST_W["modality"] * (1 - len(ma & mb) / max(1, len(ma | mb)))
    for k, sc in SCALES.items():
        d += DIST_W[k] * abs(sc.index(a[k]) - sc.index(b[k])) / (len(sc) - 1)
    d += DIST_W["quant"] * (a["quant"] != b["quant"])
    return d


def render_md(spec: dict) -> str:
    t = spec["traits"]
    L = [f"# Workflow `{spec.get('id', spec['name'])}`", ""]
    L.append(f"- domain: **{t.get('domain') or '-'}** / direction: **{t.get('direction') or '-'}** (mode=`{t['mode']}`)")
    L.append(f"- parent: {spec.get('parent') or '-'} · novel: {spec.get('novel')} · forged: {spec.get('forged')}")
    L.append(f"- traits: modality={t['modality']}, verifiability={t['verifiability']}, stakes={t['stakes']}, volume={t['volume']}, "
             f"volatility={t['volatility']}, noise={t['noise']}, ethics={t['ethics']}, access={t['access']}, quant={t['quant']}, temporal={t['temporal']}")
    est = spec["estimate"]
    L.append(f"- Planning-estimate dispatch: ~{est['dispatch_tasks']} tasks ({est['basis']})")
    L += ["", "## Blocks (execution order)", "", "| # | block | phase | role | fanout | needs | gates | why |", "|---|---|---|---|---|---|---|---|"]
    for i, b in enumerate(spec["blocks"], 1):
        g = ",".join(b["gates"]) + ((" (soft: " + ",".join(b["soft_gates"]) + ")") if b["soft_gates"] else "")
        L.append(f"| {i} | {b['id']} | {b['phase']} | {b['role']} | {b['fanout']} | {','.join(b['needs']) or '-'} | {g or '-'} | {b['why']} |")
    p = spec["params"]
    L += ["", "## Params", "", "```json", json.dumps({k: v for k, v in p.items() if k != "lanes"}, ensure_ascii=False, indent=2), "```", "", "### Lanes"]
    L += [f"- `{l['name']}`: {l['desc']}" for l in p["lanes"]]
    if spec["excluded"]:
        L += ["", "## Excluded", ""] + [f"- `{e['id']}`: {e['reason']}" for e in spec["excluded"]]
    if spec.get("warnings"):
        L += ["", "## Warnings", ""] + [f"- {w}" for w in spec["warnings"]]
    ov = spec.get("overrides", {})
    if any(ov.get(k) for k in ov):
        L += ["", "## Overrides", "", f"- add={ov['add']} drop={ov['drop']} set={ov['set']}"]
    return "\n".join(L) + "\n"
