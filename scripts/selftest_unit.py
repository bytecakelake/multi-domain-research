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
check(n1["n"] and "failed" in n1["n"] and "HTTP 429 new-account-rpm" in n1["n"] and "auto: retried" in n1["n"], "blank retry records automatic reason from prior status/notes")
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

# 23 E3: classify_failure is a pure, high-confidence pattern table (env vs output vs unknown)
CF = runtime.classify_failure
for txt, want in [("HTTP 402 Payment Required", ("env", "billing")), ("billing hard limit reached", ("env", "billing")), ("credits exhausted", ("env", "billing")),
                  ("insufficient credits on account", ("env", "billing")), ("insufficient_quota", ("env", "billing")),
                  ("HTTP 429 new-account-rpm", ("env", "rate_limit")), ("Rate limit reached for model", ("env", "rate_limit")),
                  ("You have hit your usage limit. It resets at 5pm", ("env", "rate_limit")),
                  ("HTTP 401 Unauthorized", ("env", "auth")), ("OAuth token has been invalidated", ("env", "auth")), ("unauthorized", ("env", "auth")),
                  ("request timed out after 60s", ("env", "network")), ("Timeout while reading", ("env", "network")), ("connection reset by peer", ("env", "network")),
                  ("Connection refused", ("env", "network")), ("HTTP 503 service unavailable", ("env", "network")), ("upstream returned HTTP 502", ("env", "network")),
                  ("proof: output file truncated", ("output", "proof")), ("PROOF FAILED: no receipt", ("output", "proof")),
                  ("rejected 3 of 10 rows", ("output", "rejected")), ("quote not found verbatim", ("output", "rejected")), ("unknown evidence id E9", ("output", "rejected")),
                  ("missing _meta line", ("output", "rejected")), ("n_rows mismatch", ("output", "rejected"))]:
    check(CF(txt)[:2] == want and CF(txt)[2] == "pattern", f"classify_failure({txt!r}) -> {want}")
for txt in ["HTTP 4020", "ID 14029 not valid", "found 402 rows", "error 40290", "port 5029", "the model refused", "something odd", "HTTP 4290"]:
    check(CF(txt) == ("unknown", None, "none"), f"classify_failure near-miss {txt!r} stays unknown")
check(CF("") == ("unknown", None, "none") and CF(None) == ("unknown", None, "none") and CF("   ") == ("unknown", None, "none"), "classify_failure empty/None/blank -> unknown")
check(CF("요청 실패: HTTP 429 — 사용량 초과 😀")[:2] == ("env", "rate_limit"), "classify_failure finds HTTP 429 inside unicode text")
check(CF("http 402")[:2] == ("env", "billing") and CF("RATE LIMIT")[:2] == ("env", "rate_limit"), "classify_failure is case-insensitive")
check(CF("proof: quote not found, then HTTP 402 in quoted text")[:2] == ("output", "proof"), "ingest outcome text wins over an env word quoted inside it")

# 24 E3: retry stores class/kind/source, tags only known classes, explicit --cause wins, auto reason classifies from prior notes
def e3_ev(r, n=1):
    return json.loads(r.q("SELECT detail d FROM events WHERE kind='retry' ORDER BY id DESC")[n - 1]["d"])
def e3_fail(r, t, notes=None, status="failed"):
    r.db.execute("UPDATE tasks SET status=?, notes=? WHERE id=?", (status, notes, t))
def e3_note(r, t):
    return r.one("SELECT notes n FROM tasks WHERE id=?", (t,))["n"]
r = setup("e3cls", ["scout"]); t = task(r, "scout", None)
e3_fail(r, t); runtime.retry_task(r, t, note="HTTP 402 credits exhausted")
e = e3_ev(r)
check((e["failure_class"], e["failure_kind"], e["class_source"]) == ("env", "billing", "pattern") and e["note"] == e3_note(r, t), "retry event stores class/kind/source=pattern")
check(e3_note(r, t) == "[env:billing] HTTP 402 credits exhausted", "known class prefixes a tag and keeps explicit note text verbatim")
e3_fail(r, t); runtime.retry_task(r, t, note="the model gave up")
e = e3_ev(r)
check((e["failure_class"], e["failure_kind"], e["class_source"]) == ("unknown", None, "none") and e3_note(r, t) == "the model gave up", "unknown class: stored with source none and no tag")
e3_fail(r, t); runtime.retry_task(r, t, note="HTTP 429 rate limit", cause="model")
e = e3_ev(r)
check((e["failure_class"], e["class_source"]) == ("model", "explicit") and e3_note(r, t) == "[model] HTTP 429 rate limit", "explicit --cause model wins over pattern")
e3_fail(r, t); runtime.retry_task(r, t, note="weird", cause="contract")
check(e3_ev(r)["failure_class"] == "contract" and e3_ev(r)["class_source"] == "explicit" and e3_note(r, t) == "[contract] weird", "explicit --cause contract on unknown text")
e3_fail(r, t); runtime.retry_task(r, t, note="HTTP 402", cause="env")
e = e3_ev(r)
check((e["failure_class"], e["failure_kind"], e["class_source"]) == ("env", "billing", "explicit") and e3_note(r, t) == "[env:billing] HTTP 402", "explicit --cause env keeps pattern kind")
e3_fail(r, t); runtime.retry_task(r, t, note="odd", cause="env")
check(e3_ev(r)["failure_kind"] is None and e3_note(r, t) == "[env] odd", "explicit env without recognisable kind: tag has no kind")
before = (e3_note(r, t), r.one("SELECT attempts a FROM tasks WHERE id=?", (t,))["a"], len(r.q("SELECT 1 FROM events WHERE kind='retry'")))
try:
    runtime.retry_task(r, t, note="x", cause="banana"); bad = False
except core.RlabError:
    bad = True
check(bad and before == (e3_note(r, t), r.one("SELECT attempts a FROM tasks WHERE id=?", (t,))["a"], len(r.q("SELECT 1 FROM events WHERE kind='retry'"))), "invalid cause dies without touching the task or events")
e3_fail(r, t, "HTTP 402 billing"); runtime.retry_task(r, t)
e = e3_ev(r); n = e3_note(r, t)
check(e["auto"] is True and (e["failure_class"], e["failure_kind"], e["class_source"]) == ("env", "billing", "pattern") and n.startswith("[env:billing] auto:") and "HTTP 402 billing" in n, "auto-reason retry classifies from prior notes")
e3_fail(r, t, None); runtime.retry_task(r, t)
e = e3_ev(r)
check(e["auto"] is True and e["failure_class"] == "unknown" and e["class_source"] == "none" and e3_note(r, t).startswith("auto:"), "auto retry with no prior note: unknown, no tag")
e3_fail(r, t, "HTTP 402 billing"); runtime.retry_task(r, t, note="switched provider")
check(e3_ev(r)["failure_class"] == "unknown" and e3_note(r, t) == "switched provider", "an explicit note is classified on its own text, not on prior notes")

# 25 E3: per-option concurrency cap in next_actions
def e3_state(r):
    return {x["id"]: x["status"] for x in r.q("SELECT id, status FROM tasks")}
r = setup("e3cap", ["scout", "analyze-claims"], {"max_parallel": 10})
ts = [task(r, "scout", None) for _ in range(5)]
res = runtime.next_actions(r)
check(len(res["dispatch"]) == 3 and all(p["option"] == "M-Terra-Quick" for p in res["dispatch"]), "cap: 5 planned on one option, default cap 3 -> 3 emitted")
check(res["capped"] == [{"task_id": x, "option": "M-Terra-Quick", "cap": 3} for x in ts[3:]] and res["queued"] == 2, "cap: the other 2 are reported as capped and remain queued")
check(set(e3_state(r).values()) == {"planned"}, "cap: dry run dispatches nothing")
res = runtime.next_actions(r, dispatch=True)
st = e3_state(r)
check([st[x] for x in ts] == ["ready"] * 3 + ["planned"] * 2, "cap: dispatch marks only the 3 uncapped tasks ready")
res = runtime.next_actions(r)
check(res["dispatch"] == [] and [c["task_id"] for c in res["capped"]] == ts[3:], "cap: in-flight tasks count toward the option cap")
r.db.execute("UPDATE tasks SET status='returned' WHERE id=?", (ts[0],))
check(runtime.next_actions(r)["dispatch"] == [], "cap: returned tasks still count as in-flight")
r.db.execute("UPDATE tasks SET status='verified' WHERE id=?", (ts[0],))
res = runtime.next_actions(r)
check([p["task_id"] for p in res["dispatch"]] == [ts[3]] and [c["task_id"] for c in res["capped"]] == [ts[4]], "cap: a freed slot lets exactly one waiting task through")
a1 = task(r, "analyze-claims", None)
res = runtime.next_actions(r)
check(a1 in [p["task_id"] for p in res["dispatch"]] and all(c["option"] == "M-Terra-Quick" for c in res["capped"]), "cap: a different option is not blocked by a full option")
r2 = setup("e3cap2", ["scout"], {"max_parallel": 10, "max_per_option": 1})
for _ in range(3): task(r2, "scout", None)
res = runtime.next_actions(r2)
check(len(res["dispatch"]) == 1 and len(res["capped"]) == 2 and res["capped"][0]["cap"] == 1, "cap: params.max_per_option overrides the default")
r3 = setup("e3cap3", ["scout"], {"max_parallel": 10})
for _ in range(5): task(r3, "scout", None)
res = runtime.next_actions(r3, available=[])
check(len(res["dispatch"]) == 5 and all(p["option"] is None for p in res["dispatch"]) and res["capped"] == [], "cap: tasks with option None are not option-capped")
r4 = setup("e3cap4", ["scout"], {"max_parallel": 2})
for _ in range(5): task(r4, "scout", None)
res = runtime.next_actions(r4)
check(len(res["dispatch"]) == 2 and res["capped"] == [] and res["queued"] == 3, "cap: max_parallel still limits the total (2 < option cap 3)")
r5 = setup("e3cap5", ["scout", "analyze-claims"], {"max_parallel": 4})
for _ in range(4): task(r5, "scout", None)
task(r5, "analyze-claims", None)
res = runtime.next_actions(r5)
check(len(res["dispatch"]) == 4 and [c["task_id"] for c in res["capped"]] == ["T0004"] and res["queued"] == 1, "cap: a capped task does not waste a parallel slot (3 scouts + the analyst fill 4 slots)")

# 26 E3: billing auto-halt and resume
def e3_halt_run(case, n=2, wave=1, opt="M-Terra-Quick"):
    r = setup(case, ["scout", "analyze-claims"], {"max_parallel": 10})
    ts = [task(r, "scout", None, wave=wave) for _ in range(n)]
    for t in ts:
        r.db.execute("UPDATE tasks SET status='failed', option=?, dispatched='2026-01-01T00:00:00' WHERE id=?", (opt, t))
    return r, ts
def e3_halt(r):
    v = r.meta("halt")
    return json.loads(v) if v else None
r, ts = e3_halt_run("e3h1")
runtime.retry_task(r, ts[0], note="HTTP 402 payment required")
check(e3_halt(r) is None, "halt: one 402 in a two-task wave does not halt yet")
runtime.retry_task(r, ts[1], note="HTTP 402 payment required")
h = e3_halt(r)
check(h and h["kind"] == "billing" and h["block"] == "scout" and h["wave"] == 1 and h["option"] == "M-Terra-Quick" and sorted(h["tasks"]) == sorted(ts) and h["ts"], "halt: all non-verified tasks of the wave failed with 402 on one option -> halt object in meta")
res = runtime.next_actions(r, dispatch=True)
check(res["dispatch"] == [] and res["payload_path"] is None and res["halted"] == h and set(e3_state(r).values()) == {"planned"}, "halt: next emits nothing, dispatches nothing and reports halted")
check([json.loads(x["d"])["halt"] for x in r.q("SELECT detail d FROM events WHERE kind='halt'")] == [h], "halt: recorded as an event")
try:
    runtime.resume(r, ""); bad = False
except core.RlabError:
    bad = True
check(bad and e3_halt(r) == h, "resume: empty reason dies and keeps the halt")
runtime.resume(r, "topped up credits")
ev_r = [json.loads(x["d"]) for x in r.q("SELECT detail d FROM events WHERE kind='resume'")]
check(e3_halt(r) is None and len(ev_r) == 1 and ev_r[0]["reason"] == "topped up credits" and ev_r[0]["halt"] == h, "resume: clears the halt and records a resume event with reason and the cleared halt")
res = runtime.next_actions(r, dispatch=True)
check(len(res["dispatch"]) == 2 and not res.get("halted"), "resume: dispatch works again")
try:
    runtime.resume(r, "again"); bad = False
except core.RlabError as ex:
    bad = "no active halt" in str(ex)
check(bad, "resume without an active halt dies with a clear message")
r, ts = e3_halt_run("e3h2", n=1)
runtime.retry_task(r, ts[0], note="HTTP 402")
check(e3_halt(r) is None and runtime.next_actions(r).get("halted") is None, "halt: a single failed task never halts")
r, ts = e3_halt_run("e3h3")
r.db.execute("UPDATE tasks SET option='M-Haiku-Quick' WHERE id=?", (ts[1],))
runtime.retry_task(r, ts[0], note="HTTP 402"); runtime.retry_task(r, ts[1], note="HTTP 402", option="M-Haiku-Quick")
check(e3_halt(r) is None, "halt: 402 on different options does not halt")
for code, case in [("HTTP 429 rate limit", "e3h4"), ("HTTP 401 unauthorized", "e3h5"), ("connection reset", "e3h6")]:
    r, ts = e3_halt_run(case)
    for t in ts: runtime.retry_task(r, t, note=code)
    check(e3_halt(r) is None and runtime.next_actions(r).get("halted") is None, f"halt: {code!r} on every task never halts")
r, ts = e3_halt_run("e3h7", n=3)
r.db.execute("UPDATE tasks SET status='verified' WHERE id=?", (ts[2],))
runtime.retry_task(r, ts[0], note="HTTP 402"); runtime.retry_task(r, ts[1], note="HTTP 402")
check(e3_halt(r) is not None and ts[2] not in e3_halt(r)["tasks"], "halt: verified tasks of the wave are ignored")
r, ts = e3_halt_run("e3h8")
r.db.execute("UPDATE tasks SET status='planned' WHERE id=?", (ts[1],))
runtime.retry_task(r, ts[0], note="HTTP 402")
check(e3_halt(r) is None, "halt: a sibling that never failed with 402 (no retry event) blocks the halt")
r, ts = e3_halt_run("e3h9")
runtime.retry_task(r, ts[0], note="HTTP 402"); e3_fail(r, ts[0]); runtime.retry_task(r, ts[0], note="model returned junk"); runtime.retry_task(r, ts[1], note="HTTP 402")
check(e3_halt(r) is None, "halt: only the LATEST retry event of each task counts")
r, ts = e3_halt_run("e3h10", n=1)
other = task(r, "scout", None, wave=2); r.db.execute("UPDATE tasks SET status='failed', option='M-Terra-Quick' WHERE id=?", (other,))
third = task(r, "analyze-claims", None, wave=1); r.db.execute("UPDATE tasks SET status='failed', option='M-Terra-Quick' WHERE id=?", (third,))
runtime.retry_task(r, ts[0], note="HTTP 402"); runtime.retry_task(r, other, note="HTTP 402"); runtime.retry_task(r, third, note="HTTP 402")
check(e3_halt(r) is None, "halt: tasks of another wave or block do not count toward the group")
r, ts = e3_halt_run("e3h11")
runtime.retry_task(r, ts[0], note="HTTP 402"); runtime.retry_task(r, ts[1], note="billing issue", cause="env")
check(e3_halt(r) is not None, "halt: explicit --cause env with a billing note halts too")
r, ts = e3_halt_run("e3h12")
runtime.retry_task(r, ts[0], note="HTTP 402"); runtime.retry_task(r, ts[1], note="HTTP 402", cause="model")
check(e3_halt(r) is None, "halt: explicit --cause model overrides the 402 pattern and does not halt")

# halt ignores tasks that were never dispatched (capped by max_per_option): they have no option and no retry event yet
r, ts = e3_halt_run("e3h13")
waiting = [task(r, "scout", None) for _ in range(2)]
runtime.retry_task(r, ts[0], note="HTTP 402"); runtime.retry_task(r, ts[1], note="HTTP 402")
h = e3_halt(r)
check(h is not None and sorted(h["tasks"]) == sorted(ts) and all(w not in h["tasks"] for w in waiting), "halt: never-dispatched (capped) siblings of the wave do not block the halt")
for txt in ["billing dispute policy not found", "the billing page lists no fee", "billing"]:
    check(CF(txt) == ("unknown", None, "none"), f"classify_failure: bare word in {txt!r} is not a billing outage")
check(CF("billing error: card declined")[:2] == ("env", "billing") and CF("billing hard limit reached")[:2] == ("env", "billing"), "classify_failure: billing error/limit phrases still classify as billing")

# 27 E3: CLI surface (retry --cause, resume, printed halt/capped blocks)
import io, contextlib
r, ts = e3_halt_run("e3cli")
ns = argparse.Namespace(run=str(r.root), task=ts[0], option=None, note="HTTP 402", cause="env")
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    cli.cmd_retry(ns); ns2 = argparse.Namespace(run=str(r.root), task=ts[1], option=None, note="HTTP 402", cause=None); cli.cmd_retry(ns2)
    res = runtime.next_actions(core.Run(r.root)); cli._print_next(res, False)
out = buf.getvalue()
check("[HALT]" in out and "rlab resume --reason" in out and "402" in out and "top" in out.lower(), "CLI prints a [HALT] block with the resume command")
with contextlib.redirect_stdout(io.StringIO()):
    rc = cli.cmd_resume(argparse.Namespace(run=str(r.root), reason="topped up"))
check(rc == 0, "CLI resume returns 0")
r = core.Run(r.root)
check(r.meta("halt") is None, "CLI resume cleared the halt")
r = setup("e3cli2", ["scout"], {"max_parallel": 10})
for _ in range(4): task(r, "scout", None)
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    res = runtime.next_actions(r)
    cli._print_next(res, False)
check("wait" in buf.getvalue().lower() and "M-Terra-Quick" in buf.getvalue() and "3" in buf.getvalue(), "CLI prints which tasks wait for a free option slot")
import subprocess as _sp
helptxt = _sp.run([sys.executable, str(Path(__file__).resolve().parent / "rlab.py"), "retry", "--help"], capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}).stdout
check("--cause" in helptxt and "env,contract,model" in helptxt.replace("{", "").replace("}", "").replace(" ", ""), "retry --cause offers env|contract|model choices")

# 28 E2: 'ready' (emitted in a payload) is separate from 'dispatched' (delegation confirmed); payload is ASCII-only
def e2_run(case, n=3, ids=("scout",), params=None):
    r = setup(case, list(ids), {"max_parallel": 10, **(params or {})})
    return r, [task(r, ids[0], None) for _ in range(n)]
def e2_row(r, t):
    return r.one("SELECT * FROM tasks WHERE id=?", (t,))
def e2_ev(r, kind, t=None):
    return [json.loads(x["d"] or "{}") | {"task": x["task_id"]} for x in r.q("SELECT task_id, detail d FROM events WHERE kind=? ORDER BY id", (kind,)) if t is None or x["task_id"] == t]
def e2_ns(r, **kw):
    return argparse.Namespace(run=str(r.root), payload=kw.pop("payload", None), task=kw.pop("task", None), **kw)
def e2_dies(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except core.RlabError as ex:
        return str(ex)
    return None
def e2_out(fn, *a):
    ob, eb = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(ob), contextlib.redirect_stderr(eb):
        rc = fn(*a)
    return rc, ob.getvalue(), eb.getvalue()
def e2_next(r, **kw):
    ns = argparse.Namespace(run=str(r.root), max=None, dispatch=True, available=None, json=True, full=False)
    for k, v in kw.items(): setattr(ns, k, v)
    return e2_out(cli.cmd_next, ns)
def e2_case(fn):
    try:
        fn()
    except Exception as ex:  # a missing feature must show up as a failed case, not abort the file
        check(False, f"{fn.__name__} raised {type(ex).__name__}: {ex}")

def e2_emit():
    r, ts = e2_run("e2emit")
    res = runtime.next_actions(r, dispatch=True)
    pf = Path(res["payload_path"]).name
    rows = [e2_row(r, t) for t in ts]
    check([x["status"] for x in rows] == ["ready"] * 3 and all(x["dispatched"] is None for x in rows), "E2: next --dispatch leaves tasks 'ready' with tasks.dispatched NULL")
    check(all(x["option"] == "M-Terra-Quick" for x in rows), "E2: emit still records the picked option")
    em = e2_ev(r, "dispatch_emitted")
    check([e["task"] for e in em] == ts and all(e["option"] == "M-Terra-Quick" and e["payload"] == pf for e in em), "E2: event dispatch_emitted records task, option and payload file name")
    check(e2_ev(r, "dispatch") == [], "E2: emit records no 'dispatch' event")
    res2 = runtime.next_actions(r, dispatch=True)
    check(res2["dispatch"] == [] and res2["payload_path"] is None and [e["task_id"] for e in res2["emitted"]] == ts and all(e["payload"] == pf for e in res2["emitted"]), "E2: a second next does not re-emit ready tasks and lists them as emitted")
    check(len(e2_ev(r, "dispatch_emitted")) == 3 and [e2_row(r, t)["status"] for t in ts] == ["ready"] * 3 and res2["inflight"] == [], "E2: second next changes nothing; ready tasks are not in the in-flight list")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cli._print_next(res2, False)
    out = buf.getvalue()
    check("[EMITTED, NOT CONFIRMED]" in out and all(t in out for t in ts) and pf in out and "rlab dispatched --payload" in out and "rlab unready --payload" in out, "E2: next prints [EMITTED, NOT CONFIRMED] with task, option, payload file and both ways out")
    r2, ts2 = e2_run("e2emit2", 2)
    res = runtime.next_actions(r2, dispatch=True)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cli._print_next(res, False)
    out = buf.getvalue()
    check("delegate_task" in out and "rlab dispatched --payload" in out and "rlab unready --payload" in out and "begin" in out, "E2: after [DISPATCH] next tells the parent to delegate, then run dispatched (or rely on begin), else unready")
    r3, ts3 = e2_run("e2dry", 2)
    res = runtime.next_actions(r3)
    check([e2_row(r3, t)["status"] for t in ts3] == ["planned"] * 2 and Path(res["payload_path"]).name == "dispatch_dryrun.json", "E2: a dry run marks nothing and writes a separate preview file")
    res = runtime.next_actions(r3, dispatch=True)
    pf3 = Path(res["payload_path"])
    before = pf3.read_bytes()
    runtime.next_actions(r3)
    check(pf3.read_bytes() == before and pf3.name == "dispatch_001.json", "E2: a later dry run never overwrites an emitted payload file")
e2_case(e2_emit)

def e2_capacity():
    r, ts = e2_run("e2par", 5, params={"max_parallel": 2, "max_per_option": 10})
    runtime.next_actions(r, dispatch=True)
    res = runtime.next_actions(r, dispatch=True)
    check(res["dispatch"] == [] and res["queued"] == 3 and [e2_row(r, t)["status"] for t in ts] == ["ready"] * 2 + ["planned"] * 3, "E2: ready tasks count toward max_parallel")
    r, ts = e2_run("e2cap", 5)
    runtime.next_actions(r, dispatch=True)
    res = runtime.next_actions(r, dispatch=True)
    check(res["dispatch"] == [] and [c["task_id"] for c in res["capped"]] == ts[3:] and [e2_row(r, t)["status"] for t in ts] == ["ready"] * 3 + ["planned"] * 2, "E2: ready tasks count toward the per-option cap")
e2_case(e2_capacity)

def e2_dispatched_cmd():
    r, ts = e2_run("e2dsp", 3, params={"max_parallel": 2})
    res = runtime.next_actions(r, dispatch=True)
    pf = Path(res["payload_path"])
    rc, out, _ = e2_out(cli.cmd_dispatched, e2_ns(r, payload=pf.name))
    rows = [e2_row(r, t) for t in ts]
    check(rc == 0 and [x["status"] for x in rows] == ["dispatched", "dispatched", "planned"] and rows[0]["dispatched"] and rows[1]["dispatched"] and rows[2]["dispatched"] is None, "E2: dispatched --payload <bare name> promotes ready -> dispatched and sets tasks.dispatched")
    check(all(x["option"] == "M-Terra-Quick" for x in rows[:2]) and [e["option"] for e in e2_ev(r, "dispatch")] == ["M-Terra-Quick"] * 2 and [e["task"] for e in e2_ev(r, "dispatch")] == ts[:2], "E2: dispatched keeps the option and records a 'dispatch' event per task")
    r.db.execute("UPDATE tasks SET dispatched='2026-01-01T00:00:00Z' WHERE id=?", (ts[0],))
    r.db.execute("UPDATE tasks SET status='returned' WHERE id=?", (ts[1],))
    n_ev = len(e2_ev(r, "dispatch"))
    rc, _, _ = e2_out(cli.cmd_dispatched, e2_ns(r, payload=str(pf)))
    check(rc == 0 and e2_row(r, ts[0])["dispatched"] == "2026-01-01T00:00:00Z" and e2_row(r, ts[1])["status"] == "returned" and len(e2_ev(r, "dispatch")) == n_ev, "E2: dispatched is idempotent for already dispatched / returned tasks (full path accepted)")
    r, ts = e2_run("e2dsp2", 3, params={"max_parallel": 2})
    pf = Path(runtime.next_actions(r, dispatch=True)["payload_path"])
    snap = lambda: ([dict(x) for x in r.q("SELECT * FROM tasks ORDER BY id")], r.one("SELECT COUNT(*) n FROM events")["n"])
    s0 = snap()
    msg = e2_dies(cli.cmd_dispatched, e2_ns(r, task=[ts[0], ts[2]]))
    check(msg and ts[2] in msg and "planned" in msg and snap() == s0, "E2: dispatched with a planned offender dies listing it and changes nothing")
    r.db.execute("UPDATE tasks SET status='verified' WHERE id=?", (ts[1],))
    s0 = snap()
    msg = e2_dies(cli.cmd_dispatched, e2_ns(r, payload=str(pf)))
    check(msg and ts[1] in msg and "verified" in msg and snap() == s0 and e2_row(r, ts[0])["status"] == "ready", "E2: dispatched --payload with a verified offender is all-or-nothing")
    msg = e2_dies(cli.cmd_dispatched, e2_ns(r, task=["T9999"]))
    check(msg and "T9999" in msg, "E2: dispatched with an unknown task dies")
    check(e2_dies(cli.cmd_dispatched, e2_ns(r, payload=str(pf), task=[ts[0]])) and e2_dies(cli.cmd_dispatched, e2_ns(r)) and e2_row(r, ts[0])["status"] == "ready", "E2: --payload and --task are mutually exclusive and one is required")
    msg = e2_dies(cli.cmd_dispatched, e2_ns(r, payload="dispatch_999.json"))
    check(msg and "dispatch_999.json" in msg, "E2: a missing payload dies clearly")
    bad = r.p("staging", "dispatch_bad.json"); bad.write_text("{not json")
    check(e2_dies(cli.cmd_dispatched, e2_ns(r, payload=bad.name)) and e2_dies(cli.cmd_unready, e2_ns(r, payload="dispatch_999.json")), "E2: an unreadable payload dies clearly (dispatched and unready)")
    rc, _, _ = e2_out(cli.cmd_dispatched, e2_ns(r, task=[ts[0]]))
    check(rc == 0 and e2_row(r, ts[0])["status"] == "dispatched", "E2: dispatched --task T works")
e2_case(e2_dispatched_cmd)

def e2_begin():
    r, ts = e2_run("e2begin", 3, params={"max_parallel": 1})
    runtime.next_actions(r, dispatch=True)
    r.db.execute("UPDATE tasks SET dispatched='2026-01-01T00:00:00Z' WHERE id=?", (ts[2],))
    for t in ts: runtime.begin_task(r, t)
    rows = [e2_row(r, t) for t in ts]
    check([x["status"] for x in rows] == ["dispatched"] * 3 and all(x["begun"] for x in rows), "E2: begin promotes both a ready and a planned task to dispatched")
    check(rows[0]["dispatched"] and rows[1]["dispatched"] and rows[2]["dispatched"] == "2026-01-01T00:00:00Z", "E2: begin sets tasks.dispatched (keeps an earlier timestamp)")
e2_case(e2_begin)

def e2_unready():
    r, ts = e2_run("e2un", 3)
    pf = Path(runtime.next_actions(r, dispatch=True)["payload_path"])
    before = {t: dict(e2_row(r, t)) for t in ts}
    rc, out, _ = e2_out(cli.cmd_unready, e2_ns(r, task=[ts[0], ts[1]]))
    rows = {t: dict(e2_row(r, t)) for t in ts}
    check(rc == 0 and [rows[t]["status"] for t in ts] == ["planned", "planned", "ready"], "E2: unready returns ready -> planned (only the named tasks)")
    check(all(rows[t]["attempts"] == before[t]["attempts"] == 0 and rows[t]["receipt"] == before[t]["receipt"] and rows[t]["begun"] is None for t in ts[:2]), "E2: unready keeps attempts and the receipt")
    check([e["task"] for e in e2_ev(r, "dispatch_cancelled")] == ts[:2] and all(e["option"] == "M-Terra-Quick" for e in e2_ev(r, "dispatch_cancelled")), "E2: unready records dispatch_cancelled events")
    res = runtime.next_actions(r, dispatch=True)
    check([p["task_id"] for p in res["dispatch"]] == ts[:2] and Path(res["payload_path"]).name == "dispatch_002.json" and [e["task_id"] for e in res["emitted"]] == [ts[2]], "E2: next re-emits the unreadied tasks in a new payload")
    runtime.confirm_dispatched(r, [ts[0]])
    s0 = [dict(x) for x in r.q("SELECT * FROM tasks ORDER BY id")]
    e0 = r.one("SELECT COUNT(*) n FROM events")["n"]
    msg = e2_dies(cli.cmd_unready, e2_ns(r, task=[ts[2], ts[0]]))
    check(msg and ts[0] in msg and "dispatched" in msg and [dict(x) for x in r.q("SELECT * FROM tasks ORDER BY id")] == s0 and r.one("SELECT COUNT(*) n FROM events")["n"] == e0, "E2: unready with a non-ready offender dies listing it and changes nothing")
    msg = e2_dies(cli.cmd_unready, e2_ns(r, payload=str(pf)))
    check(msg and [dict(x) for x in r.q("SELECT * FROM tasks ORDER BY id")] == s0, "E2: unready --payload is all-or-nothing too")
    check(e2_dies(cli.cmd_unready, e2_ns(r, payload=str(pf), task=[ts[2]])) and e2_dies(cli.cmd_unready, e2_ns(r)), "E2: unready needs exactly one of --payload / --task")
    r, ts = e2_run("e2un2", 2)
    pf = Path(runtime.next_actions(r, dispatch=True)["payload_path"])
    rc, _, _ = e2_out(cli.cmd_unready, e2_ns(r, payload=pf.name))
    check(rc == 0 and [e2_row(r, t)["status"] for t in ts] == ["planned"] * 2, "E2: unready --payload <file> returns all payload tasks")
e2_case(e2_unready)

def e2_retry_load():
    r, ts = e2_run("e2retry", 2)
    runtime.next_actions(r, dispatch=True)
    rcpt = e2_row(r, ts[0])["receipt"]
    runtime.retry_task(r, ts[0], note="parent decided to retry")
    x = e2_row(r, ts[0])
    check(x["status"] == "planned" and x["attempts"] == 1 and x["receipt"] != rcpt, "E2: retry on a ready task still works (planned, attempts+1, receipt rotated)")
    rp = e2_row(r, ts[1])["receipt"]
    out = r.p("staging", "out", ts[1] + ".jsonl"); out.write_text(json.dumps({"_meta": {"task": ts[1], "receipt": rp, "n_rows": 0, "empty": True, "blocker": "x"}}))
    res = ingest.ingest_file(r, ts[1], out, allow_empty=True)
    y = e2_row(r, ts[1])
    check(res["status"] == "proof_failed" and "begin" in res["proof"] and y["receipt"] == rp and y["begun"] is None and y["attempts"] == 0, "E2: loading a never-begun ready task is rejected by the begin proof, receipt untouched")
    r, ts = e2_run("e2load", 2)
    runtime.next_actions(r, dispatch=True); runtime.begin_task(r, ts[0])
    out = r.p("staging", "out", ts[0] + ".jsonl"); out.write_text(json.dumps({"_meta": {"task": ts[0], "receipt": e2_row(r, ts[0])["receipt"], "n_rows": 0, "empty": True, "blocker": "x"}}))
    check(ingest.ingest_file(r, ts[0], out, commit=False, allow_empty=True)["proof"] == "ok", "E2: a ready task that was begun passes the proof")
    out = r.p("staging", "out", ts[1] + ".jsonl"); out.write_text(json.dumps({"_meta": {"task": ts[1], "receipt": "guessed", "n_rows": 0}}))
    check(ingest.ingest_file(r, ts[1], out, commit=False)["status"] == "proof_failed" and e2_row(r, ts[1])["status"] == "ready", "E2: a guessed receipt on a ready task is still rejected (dry run leaves it ready)")
e2_case(e2_retry_load)

def e2_billing():
    r, ts = e2_run("e2bill", 3)
    runtime.next_actions(r, dispatch=True)
    runtime.confirm_dispatched(r, [ts[0]]); runtime.begin_task(r, ts[1])
    r.db.execute("UPDATE tasks SET status='failed' WHERE id IN (?,?)", (ts[0], ts[1]))
    runtime.retry_task(r, ts[0], note="HTTP 402"); runtime.retry_task(r, ts[1], note="HTTP 402")
    check(r.meta("halt") is None, "E2: billing stop waits while an emitted sibling has not reported yet (ready counts as unreported)")
    runtime.retry_task(r, ts[2], note="HTTP 402")  # still 'ready': a 402 at delegation time never reaches begin
    h = json.loads(r.meta("halt") or "null")
    check(h and sorted(h["tasks"]) == sorted(ts), "E2: once the last emitted sibling reports 402 too, the stop covers confirmed and never-confirmed tasks alike")
e2_case(e2_billing)

def e2_ascii():
    r, _ = e2_run("e2ascii", 0, ids=("scout", "analyze-claims"))
    spec = json.loads(r.p("workflow.json").read_text())
    for b in spec["blocks"]:
        b["purpose"] = "한국어 목적 설명 " + b["id"]; b["goal"] = "한국어 목표: 반드시 계약서를 따르십시오 " + b["id"]
    r.p("workflow.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8"); r._spec = None
    ts = [task(r, "scout", None), task(r, "scout", None), task(r, "analyze-claims", None)]
    rc, out, err = e2_next(r)
    res = json.loads(out)
    pf = json.loads(Path(res["payload_path"]).read_text(encoding="utf-8"))
    cp = {t: str(r.p("tasks", t, "contract.md")) for t in ts}
    check(rc == 0 and len(pf["tasks"]) == len(pf["meta"]) == 3 and all(x["goal"].isascii() and x["context"].isascii() for x in pf["tasks"]), "E2: payload file goal and context are ASCII-only although block purposes are Korean")
    check(all(x["goal"].isascii() and x["context"].isascii() for x in res["dispatch"]) and err == "", "E2: what next hands to the parent is ASCII-only and an ASCII run does not warn")
    check(all(m["task_id"] in x["goal"] and m["block"] in x["goal"] and m["role"] in x["goal"] and cp[m["task_id"]] in x["goal"] for m, x in zip(pf["meta"], pf["tasks"])), "E2: goal carries task id, block id, role and the contract path")
    check(all(m["task_id"] in x["context"] and cp[m["task_id"]] in x["context"] and r.meta("run_id") in x["context"] and "begin -> write output -> check" in x["context"] and "no instructions outside the contract" in x["context"] for m, x in zip(pf["meta"], pf["tasks"])), "E2: context is a pointer sentence with run id, task id, contract path and the procedure")
    check(all(not Path(cp[t]).read_text(encoding="utf-8").isascii() and "한국어 목표" in Path(cp[t]).read_text(encoding="utf-8") for t in ts) and "pointer" not in res["dispatch"][0], "E2: the Korean purpose and goal stay in contract.md")
    r2, ts2 = e2_run("e2full", 0)
    spec = json.loads(r2.p("workflow.json").read_text()); spec["blocks"][0]["goal"] = "한국어 목표 전체 계약"
    r2.p("workflow.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8"); r2._spec = None
    t2 = task(r2, "scout", None)
    rc, out, err = e2_next(r2, full=True)
    res = json.loads(out); pf = json.loads(Path(res["payload_path"]).read_text(encoding="utf-8"))
    full = r2.p("tasks", t2, "contract.md").read_text(encoding="utf-8")
    byid = {m["task_id"]: x for m, x in zip(pf["meta"], pf["tasks"])}
    check(byid[t2]["context"] == full and "한국어 목표 전체 계약" in byid[t2]["context"] and all(x["goal"].isascii() for x in pf["tasks"]) and any(d["context"] == full for d in res["dispatch"]), "E2: --full embeds the full Korean contract as context; goal stays ASCII")
e2_case(e2_ascii)

def e2_nonascii_path():
    r, ts = e2_run("한글-런", 1)
    rc, out, err = e2_next(r)
    check(rc == 0 and json.loads(out)["dispatch"] and "not ASCII-only" in err, "E2: a non-ASCII run path warns on stderr that the payload is not ASCII-only and does not crash")
e2_case(e2_nonascii_path)

# 29 E2 x E3: a delegation that fails with 402 never reaches begin, so the task is still 'ready' when the parent retries it
def e2_billing_run(case, n, per_option):
    r = setup(case, ["scout", "analyze-claims"], {"max_parallel": 10, "max_per_option": per_option})
    ts = [task(r, "scout", None) for _ in range(n)]
    res = runtime.next_actions(r, dispatch=True)
    return r, ts, [p["task_id"] for p in res["dispatch"]]
r, ts, sent = e2_billing_run("e2b1", 3, 2)
waiting = [t for t in ts if t not in sent]
check(len(sent) == 2 and len(waiting) == 1 and all(r.one("SELECT status s, dispatched d FROM tasks WHERE id=?", (t,))["s"] == "ready" for t in sent), "E2xE3 setup: two tasks emitted (ready), one held back by the cap")
runtime.retry_task(r, sent[0], note="HTTP 402 payment required")
check(e3_halt(r) is None, "E2xE3: first 402 retry does not stop while the sibling is still emitted and unreported")
runtime.retry_task(r, sent[1], note="HTTP 402 payment required")
h = e3_halt(r)
check(h is not None and sorted(h["tasks"]) == sorted(sent) and waiting[0] not in h["tasks"], "E2xE3: 402 retries of emitted (never confirmed) tasks stop dispatch; the held-back task is not part of the group")
check(all(r.one("SELECT dispatched d FROM tasks WHERE id=?", (t,))["d"] for t in sent), "E2xE3: retrying a ready task records that it had been delegated")
r, ts, sent = e2_billing_run("e2b2", 2, 3)
runtime.unready_tasks(r, sent)
check(all(r.one("SELECT status s, dispatched d FROM tasks WHERE id=?", (t,))["s"] == "planned" and r.one("SELECT dispatched d FROM tasks WHERE id=?", (t,))["d"] is None for t in sent), "E2xE3: unready leaves dispatched NULL (never delegated)")

shutil.rmtree(BASE, ignore_errors=True)
print("UNIT PASS" if all(RESULTS) else f"UNIT FAIL ({RESULTS.count(False)} of {len(RESULTS)})")
sys.exit(0 if all(RESULTS) else 1)
