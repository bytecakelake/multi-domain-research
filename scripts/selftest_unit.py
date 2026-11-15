#!/usr/bin/env python3
"""Unit regression tests for defects found in independent review (synthetic data, temp lab).

Run: python selftest_unit.py  -> prints per-case PASS/FAIL and `UNIT PASS|FAIL`.
"""
import json, os, shutil, sys, tempfile
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
BASE = Path(tempfile.mkdtemp(prefix="rlab-unit-"))
os.environ["RLAB_HOME"] = str(BASE / "lab")

from rlab_core import core, forge, gates, ingest, lake, runtime  # noqa: E402
from rlab_core.core import new_run_db  # noqa: E402

RESULTS = []


def check(cond, msg):
    RESULTS.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + msg)


def setup(case, ids, params=None):
    root = BASE / case
    r = new_run_db(root, case)
    cat = {b["id"]: b for b in forge.load_catalog()["blocks"]}
    blocks = []
    for i in ids:
        b = dict(cat[i]); b["needs"] = []; b.setdefault("soft_gates", []); b.setdefault("params", {}); blocks.append(b)
    spec = {"name": "t", "traits": {"mode": "describe"}, "params": {"allowed_ctypes": ["fact", "measurement", "inference"], "min_independent": 2,
            "max_reject_rate": 0.05, "lanes": [{"name": "one", "desc": "x"}], "kappa_min": 0.6, **(params or {})}, "blocks": blocks}
    r.p("workflow.json").write_text(json.dumps(spec))
    r.db.executemany("INSERT INTO block_state(block) VALUES(?)", [(x,) for x in ids])
    r.p("brief.md").write_text("test")
    return r


def question(r, qid="Q1", parent=None, kind="describe", labels=("a", "b", "c")):
    r.db.execute("INSERT INTO questions(id,parent,text,kind,labels) VALUES(?,?,?,?,?)", (qid, parent, "q " + qid, kind, json.dumps(list(labels))))


def source(r, text, origin, url=None, kind="text", name=None, pii=False):
    p = r.p("staging", "incoming", f"{origin}.{'txt' if kind == 'text' else 'csv'}")
    p.write_text(text)
    return ingest.add_source(r, {"path": str(p), "tier": 1, "stance": "independent", "origin_group": origin, "title": origin, "url": url, "kind": kind, "name": name, "pii": pii},
                             None, {"trusted": True})


def task(r, bid, coder="A", wave=1):
    return runtime.make_task(r, r.block(bid), wave, {}, coder=coder)


def ev(r, tid, sid, q="Q1", label="a", quote="abcdefghijk", **kw):
    t = dict(r.one("SELECT * FROM tasks WHERE id=?", (tid,)))
    return ingest.add_evidence(r, {"source_id": sid, "question_id": q, "label": label, "quote": quote, **kw}, tid, {"task": t})


def ctx_of(r, tid):
    return {"task": dict(r.one("SELECT * FROM tasks WHERE id=?", (tid,)))}


# 1 reopen reaches an active dependent that still has an open task
r = setup("reopen", ["scout", "analyze-claims"]); r.spec["blocks"][1]["needs"] = ["scout"]
r.db.execute("UPDATE block_state SET status='complete' WHERE block='scout'")
t = task(r, "analyze-claims", None); r.db.execute("UPDATE block_state SET status='active', waves=1 WHERE block='analyze-claims'")
runtime.reopen(r, "scout")
check(runtime.bstate(r, "analyze-claims")["status"] == "pending", "reopen marks an in-flight dependent pending")

# 2 fanout key changes when evidence ids change although the count is equal
r = setup("samecount", ["extract-single", "analyze-claims"]); question(r)
t = task(r, "extract-single"); s1 = source(r, "abcdefghijk first text", "og1")[2]; ev(r, t, s1)
first = runtime.expand_block(r, r.block("analyze-claims"), 1)
ingest.drop_source(r, s1); s2 = source(r, "abcdefghijk second text", "og2")[2]; ev(r, t, s2)
check(len(first) == 1 and len(runtime.expand_block(r, r.block("analyze-claims"), 2)) == 1, "same evidence count, different ids -> new analyst task")

# 3 duplicate source reported with pii=true flags the existing source
r = setup("piidup", ["extract-single"]); sid = source(r, "abcdefghijk sensitive content here", "og", "https://x.test/p")[2]
source(r, "abcdefghijk sensitive content here", "og", "https://x.test/p", pii=True)
check(r.one("SELECT pii_status s FROM sources WHERE id=?", (sid,))["s"] == "flagged" and gates.g_pii(r)["status"] == "fail", "duplicate pii report propagates and fails the pii gate")

# 4 none label with a quote is refused; null rows are unique and exclusive
r = setup("none", ["extract-dual"]); question(r); a = task(r, "extract-dual", "A")
sid = source(r, "abcdefghijk source text", "og0")[2]
check(ev(r, a, sid, label="none")[0] == "err", "label none + quote is rejected")
check(ev(r, a, sid, label="none", quote=None)[0] == "ok" and ev(r, a, sid, label="none", quote=None)[0] == "dup", "duplicate none rows are deduplicated")
check(ev(r, a, sid, label="a")[0] == "err", "evidence after none for the same unit is rejected")

# 5 dual coding: one label per source x question (blocks tie-break kappa inflation)
r = setup("kappa", ["extract-dual"]); question(r); a = task(r, "extract-dual", "A")
sid = source(r, "abcdefghijk lmnopqrstuv text", "og1")[2]
check(ev(r, a, sid, label="a", quote="abcdefghijk")[0] == "ok" and ev(r, a, sid, label="b", quote="lmnopqrstuv")[0] == "err", "dual coder cannot give two labels for one unit")

# 6 SQL evidence must reference the cited dataset table
r = setup("dataset", ["data-analyze"]); question(r)
da = source(r, "x\n111\n", "a", kind="dataset", name="one")[2]; db_ = source(r, "x\n999\n", "b", kind="dataset", name="two")[2]; t = task(r, "data-analyze", None)
sql = "SELECT x FROM two"; cols, rows = lake.run_sql(r, sql, ledger=False)
row = {"method": "sql", "source_id": da, "question_id": "Q1", "label": "a", "sql": sql, "result_sha": lake.result_hash(cols, rows)}
check(ingest.add_evidence(r, row, t, ctx_of(r, t))[0] == "err", "sql citing another dataset's source is rejected")
check(ingest.add_evidence(r, {**row, "source_id": db_}, t, ctx_of(r, t))[0] == "ok", "sql citing its own dataset source is accepted")

# 7 questions: cycles and referenced-question removal
r = setup("q", ["extract-single"]); p = r.p("q.jsonl")
p.write_text("\n".join(json.dumps(x) for x in [{"id": "Q1", "text": "a", "parent": "Q2"}, {"id": "Q2", "text": "b", "parent": "Q1"}]))
try:
    runtime.load_questions(r, p); ok = False
except core.RlabError:
    ok = True
check(ok, "parent cycle is rejected")
r = setup("q2", ["extract-single"]); question(r); sid = source(r, "abcdefghijk text for the unit test", "og")[2]; ev(r, task(r, "extract-single"), sid)
p = r.p("q.jsonl"); p.write_text(json.dumps({"id": "Q2", "text": "new"}))
try:
    runtime.load_questions(r, p); ok = False
except core.RlabError:
    ok = True
check(ok, "reloading questions cannot orphan existing evidence")

# 8 failed load leaves no raw file and reuses ids cleanly
r = setup("rollback", ["collect"]); t = task(r, "collect", None); runtime.begin_task(r, t)
good = r.p("staging", "incoming", "s.txt"); good.write_text("abcdefghijk source full text with payload")
rows = [{"path": str(good), "title": "s", "tier": 1, "stance": "i", "origin_group": "o"}, {"path": "/nonexistent", "title": "bad", "tier": 1, "stance": "i", "origin_group": "b"}]
rcpt = r.one("SELECT receipt FROM tasks WHERE id=?", (t,))["receipt"]
out = r.p("staging", "out", t + ".jsonl"); out.write_text("\n".join(json.dumps(x) for x in [{"_meta": {"task": t, "receipt": rcpt, "n_rows": 2}}] + rows))
res = ingest.ingest_file(r, t, out)
check(res["status"] == "failed" and not r.p("raw", "S0001.txt").exists(), "rolled-back load removes its raw file")

# 9 resubmitting the same claim merges new evidence links
r = setup("claim", ["extract-single", "analyze-claims"]); question(r); t = task(r, "extract-single"); ids = []
for n in range(2):
    ids.append(ev(r, t, source(r, f"abcdefghijk text number {n} here", f"og{n}")[2])[1])
a = task(r, "analyze-claims", None); row = {"text": "same claim", "question_id": "Q1", "ctype": "fact", "strength": "moderate", "evidence_ids": ids[:1]}
ingest.add_claim(r, row, a, ctx_of(r, a)); ingest.recompute_claims(r)
before = r.one("SELECT status s FROM claims")["s"]
ingest.add_claim(r, {**row, "evidence_ids": ids}, a, ctx_of(r, a)); ingest.recompute_claims(r)
check(before == "partial" and r.one("SELECT status s FROM claims")["s"] == "supported", "re-submitted claim merges evidence and upgrades status")

# 10 dedupe distinguishes labels but not zero-width variants (single coder)
r = setup("dedupe", ["extract-single"]); question(r); t = task(r, "extract-single", None); sid = source(r, "abcdefghijk and more words", "og")[2]
x1, x2 = ev(r, t, sid, label="a")[0], ev(r, t, sid, label="b")[0]
x3 = ev(r, t, sid, label="a", quote="abcdefghij\u200bk")[0]
check((x1, x2, x3) == ("ok", "ok", "dup"), "dedupe respects labels and normalisation")

# 11 receipt rotates on retry; begin and n_rows are mandatory
r = setup("proof", ["scout"]); t = task(r, "scout", None); a = runtime.begin_task(r, t)["receipt"]
runtime.retry_task(r, t); b = r.one("SELECT receipt FROM tasks WHERE id=?", (t,))["receipt"]
check(a != b, "retry rotates the receipt")
p = r.p("staging", "out", t + ".jsonl"); p.write_text(json.dumps({"_meta": {"task": t, "receipt": b, "n_rows": 1}}) + "\n" + json.dumps({"url": "https://e.test", "title": "x"}) + "\n")
check(ingest.ingest_file(r, t, p, commit=False)["status"] == "proof_failed", "output without begin on this attempt is refused")
runtime.begin_task(r, t)
p.write_text(json.dumps({"_meta": {"task": t, "receipt": b}}) + "\n" + json.dumps({"url": "https://e.test", "title": "x"}) + "\n")
check(ingest.ingest_file(r, t, p, commit=False)["status"] == "proof_failed", "missing n_rows is refused")
p.write_text(json.dumps({"_meta": {"task": t, "receipt": b, "n_rows": 0, "empty": True, "blocker": "no seeds"}}) + "\n")
check(ingest.ingest_file(r, t, p, commit=False)["status"] == "check_ok", "deliberate empty result (empty:true) is accepted")

# 12 quantitative child questions get data-analyze tasks
r = setup("childdata", ["data-analyze"]); question(r, "Q1"); question(r, "Q1a", parent="Q1", kind="measure"); source(r, "x\n111\n", "a", kind="dataset", name="one")
check(len(runtime.expand_block(r, r.block("data-analyze"), 1)) == 1, "measure child question under describe parent gets a data task")

# 13 lake cache refreshes after begin_task
r = setup("cache", ["scout"]); t = task(r, "scout", None); lake.run_sql(r, "SELECT status FROM tasks")
runtime.begin_task(r, t)
check(lake.run_sql(r, "SELECT status FROM tasks")[1][0][0] == "dispatched", "lake reflects task changes after begin")

# 14 report counts claims on child questions
r = setup("childreport", ["extract-single", "analyze-claims"]); question(r, "Q1"); question(r, "Q1a", parent="Q1")
sid = source(r, "abcdefghijk source content", "og")[2]; e = ev(r, task(r, "extract-single"), sid, q="Q1a")[1]; a = task(r, "analyze-claims", None)
ingest.add_claim(r, {"text": "child claim", "question_id": "Q1a", "ctype": "fact", "strength": "weak", "evidence_ids": [e]}, a, ctx_of(r, a))
check("question Q1:" not in runtime.report_md(r), "report does not flag a parent whose child question has claims")

# 15 SQL guard: comments are fine, quoted function names are not
r = setup("sqlg", [])
check(lake.run_sql(r, "SELECT 1 -- update later", ledger=False)[1] == [(1,)], "harmless SQL comment is allowed")
for bad in ['SELECT * FROM "read_csv"(\'/etc/passwd\')', "SELECT * FROM duckdb_settings()", "SELECT 1; SELECT 2", "SELECT * FROM '/etc/passwd'"]:
    try:
        lake.run_sql(r, bad, ledger=False); ok = False
    except Exception:
        ok = True
    check(ok, f"SQL guard blocks {bad[:40]!r}")

# 16 untrusted path must stay inside staging/incoming
r = setup("path", ["collect"]); (r.p("staging", "incoming") / "l.txt").symlink_to("/etc/hostname")
st = ingest.add_source(r, {"path": str(r.p("staging", "incoming", "l.txt")), "tier": 1, "stance": "i", "origin_group": "o", "title": "t"}, None, {})
check(st[0] == "err", "symlink escaping staging/incoming is refused for subagent paths")

# 17 downgrade: strong claim on a single origin group is blocked, only lowering is allowed, gate passes afterwards
import subprocess
r = setup("downgrade", ["extract-single", "analyze-claims"]); question(r); t = task(r, "extract-single", None); ids = []
for n in range(2):
    sid = source(r, f"abcdefghijk same group text {n} here", "same-og")[2]; ids.append(ev(r, t, sid)[1])
a = task(r, "analyze-claims", None)
ingest.add_claim(r, {"text": "strong claim on one group", "question_id": "Q1", "ctype": "fact", "strength": "strong", "evidence_ids": ids}, a, ctx_of(r, a)); ingest.recompute_claims(r)
check(gates.g_claim_support(r)["status"] == "fail", "strong claim backed by one origin group fails claim_support")
r.db.commit() if hasattr(r.db, "commit") else None
CLI = [sys.executable, str(Path(__file__).resolve().parent / "rlab.py"), "downgrade", "--run", str(r.root), "--claim", "K0001"]
up = subprocess.run(CLI + ["--strength", "strong", "--reason", "x"], capture_output=True, text=True)
check(up.returncode != 0, "downgrade refuses to keep or raise strength")
dn = subprocess.run(CLI + ["--strength", "moderate", "--reason", "single origin group"], capture_output=True, text=True)
check(dn.returncode == 0, "downgrade lowers strength" + ("" if dn.returncode == 0 else ": " + dn.stderr[-200:]))
r2 = core.Run.open(r.root) if hasattr(core.Run, "open") else r
check(gates.g_claim_support(r2)["status"] == "pass" and "single origin group" in (r2.one("SELECT scope s FROM claims")["s"] or ""), "after downgrade the gate passes and the reason is kept in claim scope")

# 18 E4: citation gate accepts numbered / Korean limitation headings (no English-only workaround)
r = setup("citgate", ["extract-single", "analyze-claims"]); question(r); t = task(r, "extract-single", None)
sid = source(r, "abcdefghijk source content", "og")[2]; e = ev(r, t, sid)[1]; a = task(r, "analyze-claims", None)
ingest.add_claim(r, {"text": "c", "question_id": "Q1", "ctype": "fact", "strength": "weak", "evidence_ids": [e]}, a, ctx_of(r, a))
(r.p("reports")).mkdir(exist_ok=True)
def cit(tail):
    r.p("reports", "deliverable.md").write_text("# 결과\n\n- 근거 위에서 기술된 주장 문장 [K0001]\n\n" + tail, encoding="utf-8")
    return gates.g_citation(r)["status"]
for h in ["## 3. 한계", "## 한계", "### 3) 제한 사항", "## 4. 연구의 한계와 제언", "## 3. Limitations", "## Limitations"]:
    check(cit(h + "\n\n- 내용\n") == "pass", f"citation gate accepts heading {h!r}")
for h in ["## 3. 결론", "본문에서 한계를 말한다"]:
    check(cit(h + "\n") == "fail", f"citation gate rejects non-limitations text {h!r}")

# 19 E3: retry always records a reason; explicit note wins; automatic reason only from recorded facts
r = setup("retryreason", ["scout"]); t = task(r, "scout", None)
runtime.begin_task(r, t); r.db.execute("UPDATE tasks SET status='failed', notes=? WHERE id=?", ("HTTP 429 new-account-rpm", t))
runtime.retry_task(r, t)
n1 = r.one("SELECT notes n, attempts a FROM tasks WHERE id=?", (t,))
check(n1["n"] and "failed" in n1["n"] and "HTTP 429 new-account-rpm" in n1["n"] and n1["n"].startswith("auto:"), "blank retry records automatic reason from prior status/notes")
ev1 = json.loads(r.one("SELECT detail d FROM events WHERE kind='retry' ORDER BY id DESC")["d"])
check(ev1.get("auto") is True and ev1.get("note") == n1["n"], "retry event flags the reason as automatic")
r.db.execute("UPDATE tasks SET status='failed', notes=NULL WHERE id=?", (t,))
runtime.retry_task(r, t, note="   ")
n2 = r.one("SELECT notes n FROM tasks WHERE id=?", (t,))["n"]
check(n2.startswith("auto:") and "no prior note" in n2 and "429" not in n2, "whitespace note + empty prior notes: auto reason does not invent a cause")
r.db.execute("UPDATE tasks SET status='failed' WHERE id=?", (t,))
runtime.retry_task(r, t, option="X", note="contract fixed")
n3 = r.one("SELECT notes n FROM tasks WHERE id=?", (t,))["n"]
ev3 = json.loads(r.one("SELECT detail d FROM events WHERE kind='retry' ORDER BY id DESC")["d"])
check(n3 == "contract fixed" and not ev3.get("auto"), "explicit note is stored verbatim and not marked auto")

# 20 E1: stands/inconclusive challenges must not create contradictions; weakened/refuted still do
def e1_run(case, strength="moderate"):
    r = setup(case, ["extract-single", "analyze-claims", "adversary"]); question(r)
    t = task(r, "extract-single", None)
    s1, s2, s3 = (source(r, f"abcdefghijk source {i} content", f"og{i}")[2] for i in (1, 2, 3))
    e1, e2, e3 = ev(r, t, s1)[1], ev(r, t, s2)[1], ev(r, t, s3)[1]
    a = task(r, "analyze-claims", None)
    k = ingest.add_claim(r, {"text": "c", "question_id": "Q1", "ctype": "fact", "strength": strength, "evidence_ids": [e1, e2]}, a, ctx_of(r, a))[1]
    ingest.recompute_claims(r)
    return r, k, (e1, e2, e3), task(r, "adversary", None)

def chal(r, k, tid, verdict, refs=None, note=None, found=False, **extra):
    row = {"claim_id": k, "expected_falsifier": "f", "search_log": "q", "found": found, "verdict": verdict, **extra}
    if refs is not None:
        row["evidence_refs"] = refs
    if note is not None:
        row["note"] = note
    return ingest.add_challenge(r, row, tid, ctx_of(r, tid))

def cnt(r, sql="SELECT COUNT(*) n FROM contradictions"):
    return r.one(sql)["n"]

for verdict in ("stands", "inconclusive", "weakened", "refuted"):
    for withref in (False, True):
        r, k, (e1, e2, e3), at = e1_run(f"e1v-{verdict}-{withref}")
        st, msg = chal(r, k, at, verdict, [e3] if withref else None)
        genuine = verdict in ("weakened", "refuted")
        if not withref and genuine:
            check(st == "err", f"E1 {verdict} without refs rejected")
            continue
        check(st == "ok", f"E1 {verdict} refs={withref} accepted")
        nx, nl = cnt(r), cnt(r, "SELECT COUNT(*) n FROM claim_evidence WHERE relation='refutes'")
        check((nx, nl) == ((1, 1) if genuine else (0, 0)), f"E1 {verdict} refs={withref}: contradictions/refutes links = {(nx, nl)}")

# original note preserved verbatim (unicode, multiline) + versioned context line with canonical deduped ids
r, k, (e1, e2, e3), at = e1_run("e1note")
t = dict(r.one("SELECT * FROM tasks WHERE id=?", (at,)))
note = "반증 시도 — 결과 없음\n둘째 줄 \"quote\""
st, chid = ingest.add_challenge(r, {"claim_id": k, "expected_falsifier": "f", "search_log": "q", "found": False, "verdict": "stands", "note": note,
                                    "evidence_refs": ["ref1", e3, "ref1", e3, e1]}, at, {"task": t, "refs_ev": {"ref1": e3}})
saved = r.one("SELECT note n FROM challenges WHERE id=?", (chid,))["n"]
check(saved == note + "\n[rlab challenge-context v1] " + json.dumps({"evidence_ids": [e3, e1]}, ensure_ascii=False), "E1 note verbatim + context line with canonical deduped ids")
check(chal(r, k, at, "stands", [e3])[0] == "ok" and r.one("SELECT note n FROM challenges ORDER BY id DESC")["n"] == "[rlab challenge-context v1] " + json.dumps({"evidence_ids": [e3]}), "E1 null note -> only context line")
st, chid = chal(r, k, at, "stands", None, note="plain")
check(r.one("SELECT note n FROM challenges WHERE id=?", (chid,))["n"] == "plain", "E1 stands without refs: note untouched")

# validation unchanged
r, k, (e1, e2, e3), at = e1_run("e1val")
for verdict in ("stands", "inconclusive"):
    st, msg = chal(r, k, at, verdict, ["E9999"])
    check(st == "err" and "unknown evidence id" in msg, f"E1 {verdict} unknown evidence rejected")
st, msg = chal(r, k, at, "stands", [e3], found=True)
check(st == "err" and "found=true" in msg, "E1 stands + found=true rejected")
check(chal(r, "K9999", at, "stands")[0] == "err" and cnt(r, "SELECT COUNT(*) n FROM challenges") == 0, "E1 rejected challenges leave no rows")

# analyst contradiction survives a later stands challenge; status/gate change only for genuine contradictions
r, k, (e1, e2, e3), at = e1_run("e1surv")
a2 = task(r, "analyze-claims", None)
ingest.add_claim(r, {"text": "c", "question_id": "Q1", "ctype": "fact", "strength": "moderate", "evidence_ids": [e1, e2], "counter_evidence_ids": [e3]}, a2, ctx_of(r, a2))
ingest.recompute_claims(r)
check(cnt(r) == 1 and r.one("SELECT status s FROM claims")["s"] == "contested", "E1 analyst counter evidence contests claim")
chal(r, k, at, "stands", [e3]); chal(r, k, at, "inconclusive", [e3]); ingest.recompute_claims(r)
check(cnt(r, "SELECT COUNT(*) n FROM contradictions WHERE status='open' AND evidence_id='%s'" % e3) == 1 and cnt(r, "SELECT COUNT(*) n FROM claim_evidence WHERE relation='refutes'") == 1, "E1 analyst contradiction + refutes link survive later stands/inconclusive")
check(r.one("SELECT status s FROM claims")["s"] == "contested" and gates.g_contradictions(r)["status"] == "fail", "E1 still contested / gate failing because of the analyst contradiction")
r, k, (e1, e2, e3), at = e1_run("e1gate")
chal(r, k, at, "stands", [e3]); chal(r, k, at, "inconclusive", [e3]); ingest.recompute_claims(r)
check(r.one("SELECT status s FROM claims")["s"] != "contested" and gates.g_contradictions(r)["status"] == "pass", "E1 stands/inconclusive with refs: claim not contested, contradictions gate passes")
r2, k2, (f1, f2, f3), at2 = e1_run("e1gate2"); chal(r2, k2, at2, "weakened", [f3]); ingest.recompute_claims(r2)
check(r2.one("SELECT status s FROM claims")["s"] == "contested" and gates.g_contradictions(r2)["status"] == "fail", "E1 weakened still contests claim and fails gate")

# inconclusive visible in limitations
r, k, (e1, e2, e3), at = e1_run("e1lim")
chal(r, k, at, "stands"); lim0 = runtime.report_md(r).split("## Limitations (auto)")[1]
chal(r, k, at, "inconclusive", [e3], note="n"); lim1 = runtime.report_md(r).split("## Limitations (auto)")[1]
check("inconclusive" not in lim0 and "inconclusive" in lim1 and k in lim1, "E1 inconclusive challenge appears in limitations; stands does not")

# rejected load / check rolls back challenge note additions
r, k, (e1, e2, e3), at = e1_run("e1roll")
rows = [{"kind": "challenges", "claim_id": k, "expected_falsifier": "f", "search_log": "q", "found": False, "verdict": "stands", "evidence_refs": [e3], "note": "x"},
        {"kind": "challenges", "claim_id": "K9999", "expected_falsifier": "f", "search_log": "q", "verdict": "stands"}]
pth = BASE / "e1roll.jsonl"; pth.write_text("\n".join(json.dumps(x) for x in rows), encoding="utf-8")
res = ingest.ingest_file(r, at, pth, commit=True, force_unproven=True)
check(res["status"] == "failed" and cnt(r, "SELECT COUNT(*) n FROM challenges") == 0, "E1 rejected load rolls back challenge rows incl. context note")
res = ingest.ingest_file(r, at, pth, commit=False, force_unproven=True, accept_rejects=True)
check(res["status"] == "check_ok" and cnt(r, "SELECT COUNT(*) n FROM challenges") == 0, "E1 check (dry run) leaves no challenge rows")

# 21 E1: resolve keeps provenance note, records events, repeated resolve keeps all history
import argparse
r, k, (e1, e2, e3), at = e1_run("e1res")
chal(r, k, at, "weakened", [e3], note="n"); ingest.recompute_claims(r)
x = r.one("SELECT id, note FROM contradictions")
prov = x["note"]
ns = argparse.Namespace(run=str(r.root), id=x["id"], status="disclosed", note="첫 사유")
from rlab_core import cli  # noqa: E402
check(cli.cmd_resolve(ns) == 0, "E1 resolve single-item CLI returns 0")
r = core.Run(r.root)
row = r.one("SELECT status s, note n FROM contradictions WHERE id=?", (x["id"],))
evs = [json.loads(e["d"]) for e in r.q("SELECT detail d FROM events WHERE kind='contradiction_resolved' ORDER BY id")]
check(row["s"] == "disclosed" and row["n"] == prov, "E1 resolve updates status only, provenance note kept")
check(len(evs) == 1 and evs[0]["resolution_note"] == "첫 사유" and evs[0]["provenance_note"] == prov and evs[0]["old_status"] == "open" and evs[0]["new_status"] == "disclosed"
      and evs[0]["contradiction_id"] == x["id"] and evs[0]["claim_id"] == k and evs[0]["evidence_id"] == e3, "E1 resolve event carries ids, statuses, both notes")
check(r.one("SELECT status s FROM claims")["s"] != "contested", "E1 resolve recomputes claim status")
cli.cmd_resolve(argparse.Namespace(run=str(r.root), id=x["id"], status="resolved", note="둘째 사유"))
r = core.Run(r.root)
evs = [json.loads(e["d"]) for e in r.q("SELECT detail d FROM events WHERE kind='contradiction_resolved' ORDER BY id")]
check(len(evs) == 2 and evs[0]["resolution_note"] == "첫 사유" and evs[1]["resolution_note"] == "둘째 사유" and evs[1]["old_status"] == "disclosed"
      and r.one("SELECT note n FROM contradictions WHERE id=?", (x["id"],))["n"] == prov, "E1 repeated resolve appends event; earlier history and provenance kept")
try:
    cli.cmd_resolve(argparse.Namespace(run=str(r.root), id="X9999", status="resolved", note="n")); unk = False
except core.RlabError:
    unk = True
check(unk and len(r.q("SELECT 1 FROM events WHERE kind='contradiction_resolved'")) == 2, "E1 unknown contradiction id dies without event")
cli.cmd_resolve(argparse.Namespace(run=str(r.root), id=x["id"], status="resolved", note=None))
r = core.Run(r.root)
check(r.one("SELECT note n FROM contradictions WHERE id=?", (x["id"],))["n"] == prov, "E1 resolve without note keeps provenance")

import time
# 22 E9: batch resolve --file
r, k, (e1, e2, e3), at = e1_run("e9")
CT = {}
def e9_add(n):
    ids = []
    for i in range(n):
        x = r.nid("X")
        r.db.execute("INSERT INTO contradictions(id,claim_id,evidence_id,status,note) VALUES(?,?,?,?,?)", (x, k, e3, "open", f"prov {i}"))
        ids.append(x)
    return ids
def e9_ns(**kw):
    return argparse.Namespace(**{"run": str(r.root), "id": None, "status": None, "note": None, "file": None, **kw})
def e9_file(name, lines):
    p = BASE / name; p.write_text("\n".join(lines) + "\n", encoding="utf-8"); return str(p)
SHARED = []
def e9_snap():
    rr = SHARED[0] if SHARED else core.Run(r.root)
    return ([tuple(x) for x in rr.db.execute("SELECT id,status,note FROM contradictions ORDER BY id").fetchall()],
            rr.one("SELECT COUNT(*) n FROM events WHERE kind='contradiction_resolved'")["n"], rr.one("SELECT COUNT(*) n FROM events")["n"])
def e9_rej(**kw):
    before = e9_snap()
    try:
        cli.cmd_resolve(e9_ns(**kw)); raised = False
    except core.RlabError as ex:
        raised = str(ex)
    return raised, e9_snap() == before
ids = e9_add(4)
J = lambda i, s, n=None: json.dumps({"id": i, "status": s, **({"note": n} if n is not None else {})}, ensure_ascii=False)
prov0 = {x["id"]: x["note"] for x in r.q("SELECT id, note FROM contradictions")}
calls = []
_orig_rc = ingest.recompute_claims
ingest.recompute_claims = lambda run: (calls.append(1), _orig_rc(run))[1]
f = e9_file("e9ok.jsonl", [J(ids[0], "resolved", "사유 A"), J(ids[1], "disclosed", "사유 B"), J(ids[2], "resolved")])
check(cli.cmd_resolve(e9_ns(file=f)) == 0, "E9 batch resolve returns 0")
ingest.recompute_claims = _orig_rc
rr = core.Run(r.root)
st = {x["id"]: x["status"] for x in rr.q("SELECT id,status FROM contradictions")}
evs = [json.loads(e["d"]) for e in rr.q("SELECT detail d FROM events WHERE kind='contradiction_resolved' ORDER BY id")]
check(st[ids[0]] == "resolved" and st[ids[1]] == "disclosed" and st[ids[2]] == "resolved" and st[ids[3]] == "open", "E9 batch sets each row's status; others stay open")
check([e["contradiction_id"] for e in evs] == ids[:3] and [e["resolution_note"] for e in evs] == ["사유 A", "사유 B", None]
      and all(e["claim_id"] == k and e["evidence_id"] == e3 and e["old_status"] == "open" and e["provenance_note"] == prov0[e["contradiction_id"]] for e in evs)
      and [e["new_status"] for e in evs] == ["resolved", "disclosed", "resolved"], "E9 batch events carry each row's note and same detail fields as single mode")
check(all(x["note"] == prov0[x["id"]] for x in rr.q("SELECT id,note FROM contradictions")), "E9 batch leaves provenance notes untouched")
check(len(calls) == 1, f"E9 batch recomputes claims exactly once (calls={len(calls)})")
# argument exclusivity
rej, same = e9_rej(file=f, id=ids[3], status="resolved")
check(rej and same, "E9 --file with --id/--status rejected without changes")
rej, same = e9_rej(file=f, note="x")
check(rej and same, "E9 --file with --note rejected without changes")
rej, same = e9_rej()
check(rej and same, "E9 neither --file nor --id rejected")
# whole-file rejection
bad = {"malformed": [J(ids[3], "resolved", "ok"), "{not json"],
       "unknown": [J(ids[3], "resolved", "ok"), J("X9999", "resolved", "n")],
       "badstatus": [J(ids[3], "resolved", "ok"), J(ids[0], "open", "n")],
       "dup": [J(ids[3], "resolved", "ok"), J(ids[3], "disclosed", "again")],
       "missing": [J(ids[3], "resolved", "ok"), json.dumps({"id": ids[0]}), json.dumps({"status": "resolved"})]}
for name, lines in bad.items():
    rej, same = e9_rej(file=e9_file(f"e9_{name}.jsonl", lines))
    check(rej and same and "line 2" in rej, f"E9 {name} line rejects whole file with line number, no changes")
rej, _ = e9_rej(file=e9_file("e9_multi.jsonl", ["{x", J("X9999", "resolved"), J(ids[3], "bogus")]))
check(rej and all(f"line {n}" in rej for n in (1, 2, 3)), "E9 reject message lists all offending line numbers")
rej, same = e9_rej(file=str(BASE / "nope.jsonl"))
check(rej and same, "E9 missing file rejected")
rej, same = e9_rej(file=e9_file("e9_empty.jsonl", []))
check(rej and same, "E9 empty file rejected")
# injected failure mid-batch rolls back everything
ids2 = e9_add(5)
fb = e9_file("e9inj.jsonl", [J(i, "resolved", f"n{j}") for j, i in enumerate(ids2)])
SHARED.append(core.Run(r.root)); _orig_run = cli._run; cli._run = lambda a: SHARED[0]  # same connection: leaked uncommitted writes would be visible
before = e9_snap()
_orig_ev = core.Run.event; n_ev = []
def flaky(self, kind, task_id=None, **d):
    n_ev.append(1)
    if len(n_ev) == 3: raise RuntimeError("boom")
    return _orig_ev(self, kind, task_id, **d)
core.Run.event = flaky
try:
    cli.cmd_resolve(e9_ns(file=fb)); boom = False
except RuntimeError:
    boom = True
finally:
    core.Run.event = _orig_ev
check(boom and len(n_ev) == 3 and e9_snap() == before, "E9 failure on 3rd event rolls back all statuses and events")
def rc_boom(run): raise RuntimeError("rc boom")
ingest.recompute_claims = rc_boom
try:
    cli.cmd_resolve(e9_ns(file=fb)); boom = False
except RuntimeError:
    boom = True
finally:
    ingest.recompute_claims = _orig_rc
check(boom and e9_snap() == before, "E9 failure in final recompute_claims rolls back all statuses and events")
cli._run = _orig_run; SHARED.clear()
# single mode unchanged through shared helper
cli.cmd_resolve(e9_ns(id=ids2[0], status="disclosed", note="single"))
check(core.Run(r.root).one("SELECT status s FROM contradictions WHERE id=?", (ids2[0],))["s"] == "disclosed", "E9 single-item mode still works")
# 300-row performance
big = e9_add(300)
fbig = e9_file("e9big.jsonl", [J(i, "resolved" if j % 2 else "disclosed", f"note {j}") for j, i in enumerate(big)])
t0 = time.time(); cli.cmd_resolve(e9_ns(file=fbig)); dt = time.time() - t0
print(f"E9 300-row batch took {dt:.2f}s")
check(dt < 30 and cnt(core.Run(r.root), "SELECT COUNT(*) n FROM contradictions WHERE status='open'") == 5, "E9 300-row batch under 30s, all 300 applied")
check(core.Run(r.root).one("SELECT COUNT(*) n FROM events WHERE kind='contradiction_resolved'")["n"] == 3 + 1 + 300, "E9 300-row batch wrote 300 events")

shutil.rmtree(BASE, ignore_errors=True)
print("UNIT PASS" if all(RESULTS) else f"UNIT FAIL ({RESULTS.count(False)} of {len(RESULTS)})")
sys.exit(0 if all(RESULTS) else 1)
