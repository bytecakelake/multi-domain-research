#!/usr/bin/env python3
"""rlab selftest: plays the parent AND fake subagents against the real CLI with SYNTHETIC data.

Usage: python selftest.py            # e2e compare + describe (temp lab) + unit regressions -> SELFTEST PASS|FAIL
       python selftest.py compare    # one e2e mode
Covers negative paths: wrong receipt, non-verbatim/ellipsis quotes, rollback, SQL hash mismatch, SQL guard, ctype ceiling.
"""
import json, os, re, subprocess, sys, shutil, tempfile
from pathlib import Path

PY = sys.executable
HERE = Path(__file__).resolve().parent
RLAB = str(HERE / "rlab.py")
MODES = ("compare", "describe")
if len(sys.argv) <= 1:
    base = Path(tempfile.mkdtemp(prefix="rlab-selftest-"))
    bad = []
    for m in MODES:
        p = subprocess.run([PY, __file__, m, str(base / m)], capture_output=True, text=True)
        tail = [l for l in p.stdout.splitlines() if l.startswith(("PASS", "FAIL ", "!!"))]
        print(f"--- e2e {m}: rc={p.returncode}, {sum(l.startswith('PASS') for l in tail)} pass, {sum(not l.startswith('PASS') for l in tail)} fail")
        for l in tail:
            if not l.startswith("PASS"):
                print("   ", l)
        if p.returncode:
            bad.append(m)
            print(p.stdout[-1500:], p.stderr[-800:])
    p = subprocess.run([PY, str(HERE / "selftest_unit.py")], capture_output=True, text=True)
    print("--- unit regressions:", (p.stdout.strip().splitlines() or ["(no output)"])[-1])
    if p.returncode:
        bad.append("unit")
        print(p.stdout[-1500:], p.stderr[-800:])
    shutil.rmtree(base, ignore_errors=True)
    print("SELFTEST PASS" if not bad else f"SELFTEST FAIL: {bad}")
    sys.exit(1 if bad else 0)
MODE = sys.argv[1]
BASE = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(tempfile.mkdtemp(prefix="rlab-selftest-"))
LAB = BASE / "lab"
os.environ["RLAB_HOME"] = str(LAB)
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
RUN = f"t-{MODE}"
FAILS = []


def R(*args, ok=(0,)):
    p = subprocess.run([PY, RLAB, *map(str, args)], capture_output=True, text=True)
    if p.returncode not in ok:
        print(f"!! rlab {' '.join(map(str, args))} -> rc={p.returncode}\n{p.stdout}\n{p.stderr}")
        FAILS.append(" ".join(map(str, args)))
    return p.stdout + p.stderr


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


if LAB.exists():
    shutil.rmtree(LAB)
LAB.mkdir(parents=True, exist_ok=True)
W = BASE / "work"; shutil.rmtree(W, ignore_errors=True); W.mkdir(parents=True)

TRAITS = {
    "compare": dict(domain="OSS 기술(테스트)", direction="대안 비교", mode="compare", modality=["web", "tabular"], verifiability="checkable",
                    stakes="med", volume="small", volatility="fast", noise="low", quant=True),
    "describe": dict(domain="인물 고증(테스트)", direction="서술", mode="describe", modality=["web", "social"], verifiability="interpretive",
                     stakes="low", volume="small", volatility="slow", noise="med", ethics="personal_data", temporal=True),
}[MODE]
(W / "traits.json").write_text(json.dumps(TRAITS, ensure_ascii=False))
extra = ["--set", "overlap_frac=1.0"] if MODE == "describe" else []
out = R("forge", "--traits", W / "traits.json", "--name", f"t-{MODE}", *extra)
check("saved:" in out, "forge saved workflow")

Q = [
    {"id": "Q1", "text": "처리 속도는 어느 쪽이 빠른가?", "kind": "measure", "labels": ["faster", "slower", "similar"] if MODE == "compare" else ["positive", "negative", "neutral"]},
    {"id": "Q2", "text": "라이선스와 유지보수 상태는?", "kind": "describe", "labels": ["permissive", "restrictive", "unclear"] if MODE == "compare" else ["a", "b"]},
]
if MODE == "describe":
    Q.append({"id": "Q3", "text": "관측 불가능한 질문(커버리지 공백 테스트)", "kind": "describe"})
(W / "q.jsonl").write_text("\n".join(json.dumps(q, ensure_ascii=False) for q in Q))
(W / "brief.md").write_text("# brief\n" + ("결정 대상: 로컬 분석 엔진 선택(테스트 데이터). " * 12) + "\n완료 판정: 두 질문에 대해 근거 있는 주장이 있다.\n")
R("init", "--workflow", f"t-{MODE}-v1", "--run-id", RUN, "--brief", W / "brief.md", "--questions", W / "q.jsonl")
RUNDIR = LAB / "runs" / RUN


def jl(path):
    return [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]


def write_out(tid, rows, receipt=None):
    meta = {"_meta": {"task": tid, "receipt": receipt, "n_rows": len(rows)}}
    p = RUNDIR / "staging" / "out" / f"{tid}.jsonl"
    p.write_text(json.dumps(meta) + "\n" + "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return p


def begin(tid):
    return re.search(r"RECEIPT (\w+)", R("begin", "--run", RUN, "--task", tid)).group(1)


def sqlite_one(sql):
    import sqlite3
    return sqlite3.connect(RUNDIR / "ledger.sqlite").execute(sql).fetchone()[0]


CORP = {
    "alpha": "Alpha engine runs aggregation queries in 12 ms on the benchmark. The project uses a permissive MIT license. It is actively maintained with weekly releases.",
    "beta": "Beta library finished the same aggregation in 48 ms. Its license is permissive Apache-2.0. Maintenance slowed down after 2025 with monthly releases.",
    "gamma": "Gamma tool is similar in speed at 15 ms for aggregation. It ships under a restrictive commercial license. Updates are irregular and unclear.",
}
state = {"attempt": {}}


def sentences(path):
    return [x.strip() for x in re.split(r"(?<=\.)\s", Path(path).read_text()) if x.strip()]


def fake(task):
    tid, blk, coder = task["task_id"], task["block"], task["coder"]
    inp = RUNDIR / "tasks" / tid / "input"
    n = state["attempt"].get(tid, 0)
    state["attempt"][tid] = n + 1
    rc = begin(tid)
    rows = []
    if blk == "workflow-critic":
        rows = [{"kind": "missing_lane", "severity": "info", "ref": "Q1", "note": "벤치마크 저장소 레인 추가를 검토"}]
    elif blk == "scout":
        lj = json.loads((inp / "lane.json").read_text()); lane = lj["lane"]["name"]; wv = lj["wave"]
        rows = [{"url": f"https://ex.test/{lane}/w{wv}/{k}", "title": f"{lane} doc {k}", "why": "Q1/Q2 근거", "lane": lane, "tier_guess": 1 + (k % 3), "origin_guess": f"{lane}-{k}"} for k in range(1, 3 if lane != "datasets" else 2)]
        if not state.get("first_scout"):
            state["first_scout"] = tid
            p = write_out(tid, rows, receipt="deadbeef0000")  # negative test: wrong receipt
            o = R("load", "--run", RUN, "--task", tid, "--file", p, ok=(2,))
            check("PROOF FAILED" in o, "wrong receipt is rejected (proof_failed)")
            R("retry", "--run", RUN, "--task", tid, "--note", "test retry")
            rc = begin(tid)
    elif blk == "collect":
        cands = jl(inp / "candidates.jsonl")
        d = RUNDIR / "staging" / "incoming" / tid; d.mkdir(parents=True, exist_ok=True)
        for i, c in enumerate(cands):
            if c["lane"] == "datasets":
                f = d / f"bench{i}.csv"
                f.write_text("engine,ms\nalpha,12\nbeta,48\ngamma,15\nalpha,14\nbeta,50\n")
                rows.append({"cid": c["cid"], "kind": "dataset", "name": "bench", "path": str(f), "url": c["url"], "title": c["title"], "tier": 1, "stance": "first_party", "origin_group": "bench-vendor", "lane": c["lane"], "as_of": "2026-01-10"})
            else:
                key = ["alpha", "beta", "gamma"][i % 3]
                f = d / f"{key}{i}.txt"
                f.write_text(CORP[key] + f" (doc {i})")
                rows.append({"cid": c["cid"], "path": str(f), "url": c["url"], "title": c["title"], "tier": c["tier_guess"] or 2, "stance": "independent" if i % 2 else "first_party", "origin_group": f"og{i}", "lane": c["lane"], "as_of": f"2026-0{1 + i % 3}-15", "pii": (MODE == "describe" and i == 0)})
    elif blk.startswith("extract"):
        srcs = jl(inp / "sources.jsonl")
        for s in srcs:
            txt = Path(s["text_path"]).read_text()
            sents = sentences(s["text_path"])
            lab1 = ("faster" if "12 ms" in txt or "15 ms" in txt else "slower") if MODE == "compare" else "positive"
            lab2 = ("permissive" if "permissive" in txt else "restrictive") if MODE == "compare" else "a"
            ent = "alpha" if "Alpha" in txt else ("beta" if "Beta" in txt else "gamma")
            m = re.search(r"(\d+) ms", sents[0])
            rows.append({"source_id": s["id"], "question_id": "Q1", "label": lab1, "locator": "¶1", "quote": sents[0], "polarity": "supports", "confidence": 0.8, "entity": ent, "attribute": "agg_ms", "value_num": float(m.group(1)) if m else None, "unit": "ms", "as_of": "2026-01-10"})
            rows.append({"source_id": s["id"], "question_id": "Q2", "label": lab2, "locator": "¶2", "quote": sents[1], "polarity": "supports", "confidence": 0.7})
        if n == 0 and srcs and not state.get("did_bad"):
            state["did_bad"] = tid
            good0, good1 = rows[0]["quote"], rows[1]["quote"]
            rows[0]["quote"] = "This sentence does not exist in the source text."
            rows[1]["quote"] = "Alpha engine ... in 12 ms"
            p = write_out(tid, rows, rc)
            o = R("check", "--run", RUN, "--task", tid, "--file", p, ok=(2,))
            check("not found verbatim" in o and "ellipsis" in o, "check reports bad quote + ellipsis rows")
            o = R("load", "--run", RUN, "--task", tid, "--file", p, ok=(2,))
            check("FAILED" in o, "load rolls back when reject rate exceeds threshold")
            check(int(sqlite_one("SELECT COUNT(*) FROM evidence WHERE task_id='%s'" % tid)) == 0, "rolled back: no evidence rows persisted")
            check(int(sqlite_one("SELECT COUNT(*) FROM rejects WHERE task_id='%s'" % tid)) >= 2, "rejects recorded in ledger")
            R("retry", "--run", RUN, "--task", tid, "--note", "fix quotes")
            rc = begin(tid)
            rows[0]["quote"], rows[1]["quote"] = good0, good1
    elif blk == "data-analyze":
        sql = "SELECT engine, round(avg(ms),2) AS avg_ms FROM bench GROUP BY engine ORDER BY engine"
        sha = re.search(r"result_sha=(\w+)", R("sql", "--run", RUN, "--datasets-only", sql, "--hash")).group(1)
        ds = json.loads((inp / "datasets.json").read_text())[0]
        if n == 0:
            bad = {"method": "sql", "source_id": ds["source_id"], "question_id": "Q1", "label": "faster", "sql": sql, "result_sha": "0" * 16}
            o2 = R("load", "--run", RUN, "--task", tid, "--file", write_out(tid, [bad], rc), ok=(2,))
            check("result_sha mismatch" in o2, "sql evidence with wrong hash is rejected")
            R("retry", "--run", RUN, "--task", tid); rc = begin(tid)
        rows = [{"method": "sql", "source_id": ds["source_id"], "question_id": "Q1", "label": "faster", "sql": sql, "result_sha": sha, "entity": "alpha", "attribute": "avg_ms_sql", "value_num": 13.0, "unit": "ms", "polarity": "supports"}]
        o3 = R("sql", "--run", RUN, "--datasets-only", "SELECT * FROM read_csv('/etc/passwd')", ok=(1,))
        check("disallowed" in o3, "read-only SQL guard blocks read_csv")
    elif blk in ("analyze-claims", "rival-hypotheses"):
        ev = jl(inp / "evidence.jsonl")
        qid = json.loads((inp / "question.json").read_text())[0]["id"]
        by_og = {}
        for e in [e for e in ev if e["question_id"] == qid]:
            by_og.setdefault(e["origin_group"], []).append(e)
        ids = [v[0]["id"] for v in list(by_og.values())[:3]]
        if ids:
            rows.append({"text": f"[{blk}] {qid}에 대해 {len(ids)}개 독립 출처가 일관되게 보고한다.", "question_id": qid, "ctype": "fact" if blk == "analyze-claims" else "inference", "strength": "moderate", "evidence_ids": ids, "scope": "테스트 데이터", "time_sensitive": False, "falsifier": "다른 벤치마크에서 순위가 뒤집히는 자료"})
    elif blk == "compare-matrix":
        mat = json.loads((inp / "entity_matrix.json").read_text())
        eids = [v["evidence_id"] for ent in mat.values() for att in ent.values() for v in att][:2]
        rows = [{"text": "alpha가 beta보다 집계가 빠르다(테스트 근거 기준).", "question_id": "Q1", "ctype": "inference", "strength": "weak", "evidence_ids": eids, "scope": "가중치 없음", "falsifier": "역전 벤치마크"},
                {"kind": "findings", "type": "evidence_gap", "severity": "info", "ref": "Q2", "note": "gamma의 유지보수 칸은 근거가 없다"}]
        bad = write_out(tid, [{**rows[0], "text": "x" * 20, "strength": "strong"}], rc)
        o = R("check", "--run", RUN, "--task", tid, "--file", bad, ok=(2,))
        check("limited to fact/measurement" in o, "strong inference refused by direction ceiling")
    elif blk == "adversary":
        for c in jl(inp / "claims.jsonl"):
            rows.append({"claim_id": c["id"], "expected_falsifier": "역전 벤치마크가 공개되어 있어야 함", "search_log": "q1 -> none; q2 -> none", "found": False, "verdict": "stands"})
    elif blk in ("source-audit", "bias-audit", "qa-review"):
        rows = [{"kind": "stance_skew", "severity": "info", "ref": "Q1", "note": "독립 출처를 더 추가하면 편향이 줄어든다"}]
    elif blk == "timeline-build":
        ev = jl(inp / "evidence_dated.jsonl")
        if ev:
            rows = [{"text": "2026년 초 벤치마크가 갱신되었다.", "question_id": "Q1", "ctype": "fact", "strength": "weak", "evidence_ids": [ev[0]["id"]], "scope": "추정", "falsifier": "다른 날짜 공지"}]
    p = write_out(tid, rows, rc)
    o = R("check", "--run", RUN, "--task", tid, "--file", p, ok=(0, 2))
    if "CHECK OK" not in o:
        print(o)
    o = R("load", "--run", RUN, "--task", tid, "--file", p, ok=(0, 2))
    return "VERIFIED" in o, o


def parent_actions(res):
    for pa in res["parent"]:
        b = pa["block"]
        if b == "synthesize":
            cl = json.loads(R("sql", "--run", RUN, "SELECT id, status FROM claims ORDER BY id", "--format", "json"))
            body = "# 결과\n\n" + "\n".join(f"- 테스트 주장 문장이 근거 위에서 기술된다. 이 문장은 충분히 길게 작성된다 [{c['id']}]" for c in cl[:4]) + "\n\n## Limitations\n\n- 합성 테스트 데이터이며 실제 사실이 아님 [K0001]\n"
            (RUNDIR / "reports" / "deliverable.md").write_text(body)
        elif b == "privacy-gate":
            import sqlite3
            c = sqlite3.connect(RUNDIR / "ledger.sqlite")
            for (sid,) in c.execute("SELECT id FROM sources WHERE pii_status='flagged' AND status='active'").fetchall():
                R("source", "drop", "--run", RUN, "--id", sid)
        elif b in ("intake", "retro"):
            pass
        else:
            R("done", "--run", RUN, "--block", b)


for rnd in range(60):
    nxt = json.loads(R("next", "--run", RUN, "--dispatch", "--json"))
    if rnd == 0:
        check(bool(nxt["dispatch"]) or bool(nxt["parent"]), "first next yields work")
    if nxt["done"] or (not nxt["dispatch"] and not nxt["parent"] and not nxt["inflight"] and not nxt["blocked"]):
        break
    if nxt["parent"]:
        if any(p["block"] == "retro" for p in nxt["parent"]):
            R("retro", "--run", RUN, "--score", "4", "--lesson", "테스트 교훈: 계약서 포인터 방식이 동작함", "--tag", "test")
        parent_actions(nxt)
    if nxt["blocked"] and not nxt["dispatch"] and not nxt["parent"]:
        for bl in nxt["blocked"]:
            for tid in re.findall(r"(T\d{4})\((?:failed|proof_failed)", bl["why"]):
                R("retry", "--run", RUN, "--task", tid, "--note", "auto retry")
            m = re.search(r"gate fail: (\w+)", bl["why"]) if "failed tasks" not in bl["why"] else None
            if m:
                R("waive", "--run", RUN, "--gate", m.group(1), "--block", bl["block"], "--reason", "selftest waiver")
    if nxt["dispatch"]:  # emitted tasks are 'ready'; confirm by `dispatched` in even rounds, by the child's begin in odd rounds
        ids = ",".join(f"'{t['task_id']}'" for t in nxt["dispatch"])
        check(int(sqlite_one(f"SELECT COUNT(*) FROM tasks WHERE id IN ({ids}) AND status='ready' AND dispatched IS NULL")) == len(nxt["dispatch"]), f"[{rnd}] next --dispatch leaves its tasks ready")
        if rnd % 2 == 0:
            R("dispatched", "--run", RUN, "--payload", nxt["payload_path"])
            check(int(sqlite_one(f"SELECT COUNT(*) FROM tasks WHERE id IN ({ids}) AND status='dispatched' AND dispatched IS NOT NULL")) == len(nxt["dispatch"]), f"[{rnd}] dispatched --payload confirms them")
    for t in nxt["dispatch"]:
        ok, o = fake(t)
        print(f"  [{rnd}] {t['task_id']} {t['block']:<16} -> {'VERIFIED' if ok else 'NOT VERIFIED'}")
        if not ok:
            print(o)

st = json.loads(R("next", "--run", RUN, "--json"))
check(st["done"], "all blocks complete")
check((RUNDIR / "lake" / "analysis.duckdb").exists(), "duckdb lake built")
check((RUNDIR / "lake" / "parquet" / "evidence.parquet").exists(), "parquet export exists")
check(int(sqlite_one("SELECT COUNT(*) FROM claims")) >= 2, "claims exist")
if MODE == "describe":
    check(int(sqlite_one("SELECT waves FROM block_state WHERE block='scout'")) >= 2, "coverage gap auto-reopened scout (wave >= 2)")
    check("pass" in R("gate", "kappa", "--run", RUN, ok=(0, 3)), "kappa computed on dual-coded overlap")
o = R("forge", "--traits", W / "traits.json", "--no-save")
check("library matches" in o and "dist 0.0" in o, "second forge matches the saved workflow (distance 0)")
check("테스트 교훈" in o, "lesson recalled at next forge")
print("\nFAILS:", FAILS)
sys.exit(1 if FAILS else 0)
