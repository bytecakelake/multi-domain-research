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

shutil.rmtree(BASE, ignore_errors=True)
print("UNIT PASS" if all(RESULTS) else f"UNIT FAIL ({RESULTS.count(False)} of {len(RESULTS)})")
sys.exit(0 if all(RESULTS) else 1)
