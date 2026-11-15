"""Quality gates computed from the ledger. Each returns {gate,status,value,threshold,detail}.

status: pass | fail | na | waived
"""
from __future__ import annotations

import re
from collections import Counter

from .core import Run

STRENGTH_RANK = {"weak": 0, "moderate": 1, "strong": 2}


def _res(gate, status, value=None, threshold=None, detail=""):
    return {"gate": gate, "status": status, "value": value, "threshold": threshold, "detail": detail}


def root_question(run: Run, qid: str) -> str:
    seen = set()
    while qid and qid not in seen:
        seen.add(qid)
        r = run.one("SELECT parent FROM questions WHERE id=?", (qid,))
        if not r or not r["parent"]:
            return qid
        qid = r["parent"]
    return qid


def cohen_kappa(pairs: list[tuple[str, str]]) -> float:
    n = len(pairs)
    po = sum(a == b for a, b in pairs) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum((ca[c] / n) * (cb[c] / n) for c in set(ca) | set(cb))
    return 1.0 if pe >= 1 else (po - pe) / (1 - pe)


def _block_tasks(run: Run, block):
    if block:
        return [r["id"] for r in run.q("SELECT id FROM tasks WHERE block=?", (block,))]
    return [r["id"] for r in run.q("SELECT id FROM tasks")]


def g_receipts(run, block=None):
    bad = run.q("SELECT id FROM tasks WHERE status='proof_failed'" + (" AND block=?" if block else ""), (block,) if block else ())
    if bad:
        return _res("receipts", "fail", len(bad), 0, "proof_failed: " + ", ".join(r["id"] for r in bad))
    return _res("receipts", "pass", 0, 0)


def g_reject_rate(run, block=None):
    thr = run.params(block).get("max_reject_rate", 0.05) if block else run.params().get("max_reject_rate", 0.05)
    r = run.one("SELECT COALESCE(SUM(rows_ok),0) ok, COALESCE(SUM(rows_rejected),0) rej FROM tasks WHERE status IN ('verified','returned','failed')"
                + (" AND block=?" if block else ""), (block,) if block else ())
    tot = r["ok"] + r["rej"]
    if tot == 0:
        return _res("reject_rate", "na", None, thr, "no rows yet")
    rate = r["rej"] / tot
    return _res("reject_rate", "pass" if rate <= thr else "fail", round(rate, 4), thr, f"rejected {r['rej']} of {tot}")


def g_kappa(run, block=None):
    thr = run.params(block).get("kappa_min", 0.6) if block else run.params().get("kappa_min", 0.6)
    tids = _block_tasks(run, block)
    if not tids:
        return _res("kappa", "na", None, thr, "no tasks")
    ph = ",".join("?" * len(tids))
    rows = run.q(f"SELECT source_id, question_id, coder, label FROM evidence WHERE coder IN ('A','B') AND task_id IN ({ph})", tids)
    units: dict = {}
    for r in rows:
        units.setdefault((r["source_id"], r["question_id"]), {}).setdefault(r["coder"], []).append(r["label"])
    pairs = []
    for u in units.values():
        if "A" in u and "B" in u:
            pick = lambda ls: sorted(Counter(ls).items(), key=lambda kv: (-kv[1], kv[0]))[0][0]  # noqa: E731
            pairs.append((pick(u["A"]), pick(u["B"])))
    if len(pairs) < 5:
        return _res("kappa", "na", None, thr, f"overlap units={len(pairs)} (<5): 겹치는 코딩 단위가 부족합니다")
    k = cohen_kappa(pairs)
    agree = sum(a == b for a, b in pairs) / len(pairs)
    return _res("kappa", "pass" if k >= thr else "fail", round(k, 3), thr, f"units={len(pairs)} agreement={agree:.2f}")


def g_coverage(run, block=None):
    p = run.params()
    minind = p.get("min_independent", 2)
    tops = [r["id"] for r in run.questions(top_only=True)]
    if not tops:
        return _res("coverage", "fail", 0, 1, "no questions")
    stat = {q: {"groups": set(), "best": 9} for q in tops}
    for r in run.q("SELECT e.question_id qid, s.origin_group og, s.tier tier FROM evidence e JOIN sources s ON s.id=e.source_id WHERE e.is_null=0 AND s.status='active'"):
        root = root_question(run, r["qid"])
        if root in stat:
            stat[root]["groups"].add(r["og"])
            stat[root]["best"] = min(stat[root]["best"], r["tier"] or 9)
    bad = [f"{q}(groups={len(s['groups'])},best_tier={s['best'] if s['best'] < 9 else '-'})" for q, s in stat.items()
           if len(s["groups"]) < minind or s["best"] > 2]
    ok = len(tops) - len(bad)
    return _res("coverage", "pass" if not bad else "fail", f"{ok}/{len(tops)}", f"groups>={minind} & tier<=2",
                "gaps: " + ", ".join(bad) if bad else "")


def g_saturation(run, block=None):
    sp = run.params().get("saturation", {"window": 5, "max_new": 1})
    w, mx = sp["window"], sp["max_new"]
    srcs = run.q("SELECT s.id, s.seq FROM sources s WHERE s.status='active' AND s.kind!='dataset' ORDER BY s.seq")
    seen, newcounts = set(), []
    for s in srcs:
        rows = run.q("SELECT question_id, label, COALESCE(entity,'') ent FROM evidence WHERE source_id=? AND is_null=0", (s["id"],))
        if not rows:
            continue
        new = 0
        for r in rows:
            key = (r["question_id"], r["label"], r["ent"])
            if key not in seen:
                seen.add(key)
                new += 1
        newcounts.append(new)
    if len(newcounts) <= w:
        return _res("saturation", "fail", None, f"last {w} sources <= {mx} new codes", f"evidence-bearing sources={len(newcounts)} (<= window)")
    tail = sum(newcounts[-w:])
    return _res("saturation", "pass" if tail <= mx else "fail", tail, f"<= {mx} in last {w}", f"codes={len(seen)} sources={len(newcounts)}")


def g_independence(run, block=None):
    mx = run.params().get("max_origin_share", 0.5)
    rows = run.q("SELECT s.origin_group og, COUNT(*) n FROM evidence e JOIN sources s ON s.id=e.source_id WHERE e.is_null=0 GROUP BY 1 ORDER BY 2 DESC")
    tot = sum(r["n"] for r in rows)
    if tot < 6:
        return _res("independence", "na", None, mx, f"evidence={tot} (<6)")
    share = rows[0]["n"] / tot
    return _res("independence", "pass" if share <= mx else "fail", round(share, 3), mx, f"largest origin_group={rows[0]['og']} groups={len(rows)}")


def g_claim_support(run, block=None):
    n = run.one("SELECT COUNT(*) c FROM claims")["c"]
    if n == 0:
        return _res("claim_support", "fail", 0, ">=1 claim", "no claims yet")
    bad = run.q("SELECT id, status FROM claims WHERE strength='strong' AND status!='supported'")
    if bad:
        return _res("claim_support", "fail", len(bad), 0, "strong but not supported: " + ", ".join(f"{r['id']}({r['status']})" for r in bad[:15]))
    c = Counter(r["status"] for r in run.q("SELECT status FROM claims"))
    return _res("claim_support", "pass", n, "strong claims must be supported", ", ".join(f"{k}={v}" for k, v in sorted(c.items())))


def g_challenge(run, block=None):
    min_rank = STRENGTH_RANK[run.params().get("challenge_min_strength", "moderate")]
    claims = [r for r in run.q("SELECT id, strength FROM claims") if STRENGTH_RANK.get(r["strength"], 0) >= min_rank]
    done = {r["claim_id"] for r in run.q("SELECT DISTINCT claim_id FROM challenges")}
    miss = [c["id"] for c in claims if c["id"] not in done]
    return _res("challenge", "pass" if not miss else "fail", f"{len(claims) - len(miss)}/{len(claims)}", "all >= moderate challenged",
                ("unchallenged: " + ", ".join(miss[:20])) if miss else "")


def g_contradictions(run, block=None):
    rows = run.q("SELECT x.id, x.claim_id FROM contradictions x JOIN claims c ON c.id=x.claim_id WHERE x.status='open' AND c.strength IN ('moderate','strong')")
    return _res("contradictions", "pass" if not rows else "fail", len(rows), 0,
                ("open: " + ", ".join(f"{r['id']}->{r['claim_id']}" for r in rows[:15]) + " (rlab resolve --status resolved|disclosed)") if rows else "")


KREF = re.compile(r"\[(K\d{4}(?:\s*[,;]\s*K\d{4})*)\]")


def g_citation(run, block=None):
    path = run.p("reports", "deliverable.md")
    if not path.exists():
        return _res("citation", "fail", None, None, "reports/deliverable.md 없음")
    text = path.read_text(encoding="utf-8")
    cited = set()
    for m in KREF.finditer(text):
        cited.update(re.findall(r"K\d{4}", m.group(1)))
    known = {r["id"] for r in run.q("SELECT id FROM claims")}
    unknown = sorted(cited - known)
    has_lim = re.search(r"(?im)^#+\s*(limitations|한계|제한)", text) is not None
    uncited = [ln for ln in text.splitlines() if len(ln.strip()) > 40 and not ln.lstrip().startswith("#") and not KREF.search(ln)]
    problems = []
    if unknown:
        problems.append("unknown claim ids: " + ", ".join(unknown[:10]))
    if not has_lim:
        problems.append("limitations/한계 절 없음")
    if not cited:
        problems.append("인용된 claim 없음")
    return _res("citation", "fail" if problems else "pass", f"cited={len(cited)}", "all cited ids exist + limitations",
                "; ".join(problems) + ("; " if problems else "") + f"uncited_lines={len(uncited)} (정보용)")


def g_pii(run, block=None):
    rows = run.q("SELECT id FROM sources WHERE pii_status='flagged' AND status='active'")
    return _res("pii", "pass" if not rows else "fail", len(rows), 0,
                ("flagged: " + ", ".join(r["id"] for r in rows[:15])) if rows else "")


GATES = {
    "receipts": g_receipts, "reject_rate": g_reject_rate, "kappa": g_kappa, "coverage": g_coverage,
    "saturation": g_saturation, "independence": g_independence, "claim_support": g_claim_support,
    "challenge": g_challenge, "contradictions": g_contradictions, "citation": g_citation, "pii": g_pii,
}


def evaluate(run: Run, gate: str, block: str | None = None) -> dict:
    fn = GATES.get(gate)
    if fn is None:
        return _res(gate, "fail", None, None, f"unknown gate '{gate}'")
    r = fn(run, block)
    if r["status"] == "fail":
        w = run.one("SELECT reason FROM waivers WHERE gate=? AND (block IS NULL OR block='' OR block=?)", (gate, block or ""))
        if w:
            r["status"] = "waived"
            r["detail"] += f" [waived: {w['reason']}]"
    return r


def evaluate_block(run: Run, b: dict) -> list[dict]:
    out = []
    for g in b.get("gates", []):
        r = evaluate(run, g, b["id"])
        r["hard"] = True
        r["block"] = b["id"]
        out.append(r)
    for g in b.get("soft_gates", []):
        r = evaluate(run, g, b["id"])
        r["hard"] = False
        r["block"] = b["id"]
        out.append(r)
    return out
