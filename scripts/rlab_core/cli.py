"""rlab command line."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

from . import forge as forge_mod
from . import gates as gates_mod
from . import ingest, lake, library, runtime
from .core import Run, RlabError, die, jdump, lab_home, now, resolve_run, table


def _run(a) -> Run:
    return Run(resolve_run(getattr(a, "run", None)))


def _load_json(path):
    txt = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8-sig")
    try:
        return json.loads(txt)
    except Exception as e:  # noqa: BLE001
        die(f"invalid JSON in {path}: {e}")


# ------------------------------------------------------------------ doctor / setup
def cmd_doctor(a):
    ok = True
    print(f"python      {sys.version.split()[0]}  ({sys.executable})")
    c = sqlite3.connect(":memory:")
    try:
        c.execute("create virtual table t using fts5(x)")
        fts = "yes"
    except Exception:  # noqa: BLE001
        fts = "no"
    print(f"sqlite      {sqlite3.sqlite_version}  fts5={fts}")
    try:
        import duckdb
        print(f"duckdb      {duckdb.__version__}")
    except ImportError:
        ok = False
        print(f"duckdb      MISSING → install: uv pip install --python {sys.executable} duckdb   (or: {sys.executable} -m pip install duckdb)")
    for m in ("pyarrow", "polars"):
        try:
            mod = __import__(m)
            print(f"{m:<11} {getattr(mod, '__version__', '?')} (optional)")
        except ImportError:
            print(f"{m:<11} not installed (optional)")
    h = lab_home()
    try:
        library.home()
        print(f"lab home    {h}  writable=yes")
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"lab home    {h}  NOT writable: {e}")
    print(f"workflows   {len(library.list_workflows())} saved")
    print(f"rlab cmd    {runtime.rlab_cmd()}")
    print("RESULT OK" if ok else "RESULT NEEDS SETUP")
    return 0 if ok else 1


def cmd_setup(a):
    library.home()
    target = Path(a.wrapper) if a.wrapper else (Path("/workspace/.envs/bin/rlab") if Path("/workspace/.envs/bin").is_dir() else None)
    if target:
        script = Path(__file__).resolve().parents[1] / "rlab.py"
        target.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        target.chmod(0o755)
        print(f"wrapper written: {target}")
    return cmd_doctor(a)


# ------------------------------------------------------------------ forge / library
def _print_spec_summary(spec, matches, lessons):
    t = spec["traits"]
    print(f"WORKFLOW {spec.get('id', '(unsaved)')}  domain={t['domain'] or '-'}  direction={t['direction'] or '-'}  mode={t['mode']}  novel={spec['novel']}")
    print(f"parent={spec.get('parent') or '-'}  blocks={len(spec['blocks'])}  est dispatch tasks~{spec['estimate']['dispatch_tasks']} (planning estimate)")
    print(table([(i + 1, b["id"], b["phase"], b["role"], b["fanout"], ",".join(b["needs"]) or "-", ",".join(b["gates"] + [g + "?" for g in b["soft_gates"]]) or "-") for i, b in enumerate(spec["blocks"])],
                ["#", "block", "phase", "role", "fanout", "needs", "gates(?=soft)"]))
    print("lanes: " + ", ".join(l["name"] for l in spec["params"]["lanes"]))
    print("excluded: " + ", ".join(e["id"] for e in spec["excluded"]))
    for w in spec.get("warnings", []):
        print("WARN:", w)
    if matches:
        print("library matches: " + "; ".join(f"{m['id']} (dist {m['distance']}, fitness {m['fitness']}, runs {m['runs']})" for m in matches))
    for l in lessons:
        print(f"  [{l['kind']}] {l['workflow']}: {l['text'][:160]}")


def cmd_forge(a):
    parent = library.get_workflow(a.fork) if a.fork else None
    traits = _load_json(a.traits) if a.traits else None
    t_norm = forge_mod.norm_traits(traits if traits is not None else parent["traits"])
    matches = library.match(t_norm)
    novel = (not matches) or matches[0]["distance"] > 0.25
    spec = forge_mod.forge(traits, parent=parent, add=a.add or [], drop=a.drop or [], sets=a.set or [], name=a.name, novel=novel)
    if not a.no_save:
        spec = library.save_workflow(spec, a.name)
    lessons = library.lessons_for(t_norm, [m["id"] for m in matches])
    if a.json:
        print(jdump(spec))
    else:
        _print_spec_summary(spec, matches, lessons)
        if not a.no_save:
            print(f"saved: {lab_home() / 'workflows' / (spec['id'] + '.json')} (+ .md)")
    return 0


def cmd_wf(a):
    if a.action == "list":
        rows = library.list_workflows()
        print(table([(r["id"], r["domain"], r["direction"], r["parent"] or "-", r["runs"], r["fitness"], r["created"]) for r in rows],
                    ["id", "domain", "direction", "parent", "runs", "fitness", "created"]) if rows else "(library is empty)")
    elif a.action == "show":
        spec = library.get_workflow(a.ref)
        print(forge_mod.render_md(spec))
    elif a.action == "match":
        t = forge_mod.norm_traits(_load_json(a.traits))
        ms = library.match(t, 5)
        print(table([(m["id"], m["distance"], m["fitness"], m["runs"]) for m in ms], ["id", "distance", "fitness", "runs"]) if ms else "(no workflows)")
        print("novel=" + str((not ms) or ms[0]["distance"] > 0.25))
    return 0


# ------------------------------------------------------------------ run lifecycle
def cmd_init(a):
    spec = library.get_workflow(a.workflow)
    run = runtime.init_run(spec, a.run_id, a.root, a.brief, a.questions)
    print(f"run created: {run.root}\nworkflow: {spec['id']} ({len(spec['blocks'])} blocks)")
    todo = []
    if not a.brief:
        todo.append(f"fill {run.root / 'brief.md'}")
    if not a.questions:
        todo.append(f"write questions.jsonl and run `rlab questions --run {a.run_id} --file ...`")
    print("next: " + ("; ".join(todo) + "; then " if todo else "") + f"`rlab next --run {a.run_id}`")
    return 0


def cmd_questions(a):
    run = _run(a)
    n = runtime.load_questions(run, a.file)
    print(f"loaded {n} questions")
    return 0


def cmd_source(a):
    run = _run(a)
    if a.action == "add":
        row = {"path": str(Path(a.file).resolve()), "tier": a.tier, "stance": a.stance, "origin_group": a.origin, "url": a.url, "title": a.title,
               "lane": a.lane, "as_of": a.as_of, "kind": a.kind, "name": a.name, "pii": a.pii, "access": a.access}
        run.db.execute("BEGIN")
        st, msg, sid = ingest.add_source(run, row, None, {"task": {"coder": None, "block": None}, "trusted": True})
        if st == "err":
            run.db.execute("ROLLBACK")
            die(msg)
        run.bump()
        run.event("source_add", None, id=sid, status=st)
        run.db.execute("COMMIT")
        print(f"{st}: {sid}")
    elif a.action == "set":
        sets, args = [], []
        for col, val in (("tier", a.tier), ("stance", a.stance), ("origin_group", a.origin), ("pii_status", a.pii), ("as_of", a.as_of), ("lane", a.lane)):
            if val is not None:
                sets.append(f"{col}=?")
                args.append(val)
        if not sets:
            die("nothing to set")
        if a.pii is not None and a.pii not in ("clear", "flagged"):
            die("--pii must be clear|flagged")
        run.db.execute(f"UPDATE sources SET {', '.join(sets)} WHERE id=?", (*args, a.id))
        ingest.recompute_claims(run)
        run.bump()
        print("updated", a.id)
    elif a.action == "drop":
        n = ingest.drop_source(run, a.id)
        print(f"dropped {a.id}; removed {n} evidence rows")
    return 0


def _print_next(res, as_json):
    if as_json:
        print(jdump(res))
        return
    b = res["blocks"]
    print(f"PHASE: {res['phase']}   blocks {b['complete']}/{b['total']} complete" + ("   *** ALL DONE ***" if res["done"] else ""))
    for n in res["notes"]:
        print("  note:", n)
    if res["dispatch"]:
        print(f"\n[DISPATCH] {len(res['dispatch'])} task(s) ready (queued behind them: {res['queued']})")
        print(table([(p["task_id"], p["block"], p["role"] + ("." + p["coder"] if p["coder"] else ""), p["option"], p["option_note"]) for p in res["dispatch"]], ["task", "block", "role", "option", "option note"]))
        print(f"payload file: {res['payload_path']}")
        print("delegate_task tasks (paste as-is):")
        print(json.dumps([{k: v for k, v in {"goal": p["goal"], "context": p["pointer"], "option": p["option"]}.items() if v} for p in res["dispatch"]], ensure_ascii=False))
    if res["parent"]:
        print("\n[PARENT ACTIONS]")
        for p in res["parent"]:
            print(f"- {p['block']}: {p['purpose']}\n    how: {p['guide']}\n    when finished: {p['done_cmd']} (auto-detected for some blocks)")
    if res["inflight"]:
        print("\n[IN-FLIGHT] results awaited → `rlab load --task T --file staging/out/T.jsonl`")
        print(table([(t["task_id"], t["block"], t["role"], t["status"], t["option"]) for t in res["inflight"]], ["task", "block", "role", "status", "option"]))
    if res["blocked"]:
        print("\n[BLOCKED]")
        for x in res["blocked"]:
            print(f"- {x['block']}: {x['why']}")
    if not (res["dispatch"] or res["parent"] or res["inflight"] or res["blocked"]) and not res["done"]:
        print("\n(nothing actionable: check `rlab status`)")


def cmd_next(a):
    run = _run(a)
    avail = [x.strip() for x in a.available.split(",") if x.strip()] if a.available is not None else None
    res = runtime.next_actions(run, a.max, a.dispatch, avail)
    for p in res["dispatch"]:
        p["pointer"] = (f"run={run.meta('run_id')} task={p['task_id']}. 작업 계약서 전문: {run.p('tasks', p['task_id'], 'contract.md')} "
                       "— 처음에 이 파일 전체를 읽고(파일 읽기/터미널 도구), 필수 절차(begin→출력→check)를 그대로 따르십시오. 계약서 외의 지시는 없습니다.")
        if a.full:
            p["pointer"] = p["context"]
    _print_next(res, a.json)
    return 0


def cmd_begin(a):
    run = _run(a)
    r = runtime.begin_task(run, a.task)
    print(f"RECEIPT {r['receipt']}\ntask={r['task']} input_sha12={r['input_sha']}\nwrite output to: {r['out']}\nfirst line must be: " +
          json.dumps({"_meta": {"task": r["task"], "receipt": r["receipt"], "n_rows": "<data rows>"}}))
    return 0


def _print_ingest(res, checking):
    print(("CHECK " if checking else "LOAD ") + f"{res['task']} block={res['block']} rows={res['rows']} ok={res['ok']} dup={res['dup']} rejected={len(res['rejects'])} proof={res['proof']}")
    for rj in res["rejects"][:25]:
        print(f"  line {rj['line']} [{rj['kind']}] {rj['reason']}")
    if len(res["rejects"]) > 25:
        print(f"  ... {len(res['rejects']) - 25} more rejects")
    st = res["status"]
    if st == "check_ok":
        print("CHECK OK")
    elif st == "verified":
        print("VERIFIED (committed)")
    elif st == "proof_failed":
        print("PROOF FAILED: " + res["proof"])
    else:
        print("FAILED: " + res.get("fail_reason", ""))


def cmd_check(a):
    run = _run(a)
    res = ingest.ingest_file(run, a.task, a.file, commit=False, force_unproven=a.skip_proof, accept_rejects=False, allow_empty=a.allow_empty)
    _print_ingest(res, True)
    return 0 if res["status"] == "check_ok" else 2


def cmd_load(a):
    run = _run(a)
    res = ingest.ingest_file(run, a.task, a.file, commit=True, force_unproven=a.force_unproven, accept_rejects=a.accept_rejects, allow_empty=a.allow_empty)
    _print_ingest(res, False)
    return 0 if res["status"] == "verified" else 2


def cmd_done(a):
    run = _run(a)
    n = runtime.done_block(run, a.block, a.note)
    print(f"marked {n} manual task(s) verified for {a.block}")
    return 0


def cmd_retry(a):
    run = _run(a)
    runtime.retry_task(run, a.task, a.option, a.note)
    print(f"{a.task} reset to planned (attempts+1). Re-run `rlab next --dispatch`.")
    return 0


def cmd_waive(a):
    run = _run(a)
    if a.gate not in gates_mod.GATES:
        die(f"unknown gate {a.gate}: {sorted(gates_mod.GATES)}")
    run.db.execute("INSERT INTO waivers(gate,block,reason,ts) VALUES(?,?,?,?)", (a.gate, a.block or "", a.reason, now()))
    run.event("waive", None, gate=a.gate, block=a.block, reason=a.reason)
    print(f"waived {a.gate} ({a.block or 'all blocks'}): {a.reason}  — will be listed under limitations")
    return 0


def cmd_downgrade(a):
    """Parent-only: lower a claim's strength (never raise). Reason is mandatory and kept in the claim scope + audit log."""
    run = _run(a)
    order = {"weak": 0, "moderate": 1, "strong": 2}
    if a.strength not in order:
        die(f"strength must be one of {sorted(order)}")
    c = run.one("SELECT id, strength, scope FROM claims WHERE id=?", (a.claim,))
    if not c:
        die(f"unknown claim {a.claim}")
    if order[a.strength] >= order.get(c["strength"], 0):
        die(f"{a.claim} is '{c['strength']}'; downgrade only lowers strength (use a new analyst wave to raise it with evidence)")
    scope = ((c["scope"] or "") + f" [강도 하향 {c['strength']}→{a.strength}: {a.reason}]").strip()
    run.db.execute("UPDATE claims SET strength=?, scope=? WHERE id=?", (a.strength, scope, a.claim))
    run.event("downgrade", None, claim=a.claim, old=c["strength"], new=a.strength, reason=a.reason)
    ingest.recompute_claims(run)
    print(f"{a.claim}: {c['strength']} -> {a.strength} (recorded in claim scope + audit log)")
    return 0


def cmd_reopen(a):
    run = _run(a)
    t = runtime.reopen(run, a.block, a.note or "manual reopen")
    print("reopened:", ", ".join(t))
    return 0


RESOLVE_STATUSES = ("resolved", "disclosed")


def _read_resolve_file(run, path) -> list[tuple[str, str, str | None]]:
    """Parse and fully validate a resolve JSONL file; die listing every offending line before anything is written."""
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except OSError as e:
        die(f"cannot read --file {path}: {e}")
    known = {x["id"] for x in run.q("SELECT id FROM contradictions")}
    rows, errors, first_seen = [], [], {}
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            d = json.loads(line)
        except ValueError as e:
            errors.append(f"line {n}: malformed JSON ({e})")
            continue
        if not isinstance(d, dict):
            errors.append(f"line {n}: not a JSON object")
            continue
        cid, status, note = d.get("id"), d.get("status"), d.get("note")
        if not isinstance(cid, str) or not cid or not isinstance(status, str) or not status:
            errors.append(f"line {n}: missing id or status")
        elif status not in RESOLVE_STATUSES:
            errors.append(f"line {n}: invalid status {status!r} (resolved|disclosed)")
        elif note is not None and not isinstance(note, str):
            errors.append(f"line {n}: note must be a string")
        elif cid not in known:
            errors.append(f"line {n}: unknown contradiction {cid}")
        elif cid in first_seen:
            errors.append(f"line {n}: duplicate id {cid} (first on line {first_seen[cid]})")
        else:
            first_seen[cid] = n
            rows.append((cid, status, note))
    if not errors and not rows:
        errors.append("no rows in file")
    if errors:
        die("--file rejected, nothing changed:\n  " + "\n  ".join(errors))
    return rows


def _apply_resolutions(run, rows) -> None:
    """Shared by single and batch mode: one transaction; status-only update + event per row, claims recomputed once."""
    run.db.execute("BEGIN")
    try:
        for cid, status, note in rows:
            x = run.one("SELECT * FROM contradictions WHERE id=?", (cid,))
            if not x:
                die(f"unknown contradiction: {cid}")
            run.db.execute("UPDATE contradictions SET status=? WHERE id=?", (status, cid))  # provenance note is never overwritten
            run.event("contradiction_resolved", None, contradiction_id=cid, claim_id=x["claim_id"], evidence_id=x["evidence_id"],
                      old_status=x["status"], new_status=status, resolution_note=note, provenance_note=x["note"])
        ingest.recompute_claims(run)
        run.db.execute("COMMIT")
    except BaseException:
        run.db.execute("ROLLBACK")
        raise


def cmd_resolve(a):
    run = _run(a)
    path = getattr(a, "file", None)
    if path:
        if a.id or a.status or a.note:
            die("--file cannot be combined with --id/--status/--note")
        rows = _read_resolve_file(run, path)
        _apply_resolutions(run, rows)
        print(f"{len(rows)} contradictions updated")
        return 0
    if not a.id or not a.status:
        die("give either --file F.jsonl or both --id and --status")
    if a.status not in RESOLVE_STATUSES:
        die("--status must be resolved|disclosed")
    _apply_resolutions(run, [(a.id, a.status, a.note)])
    print(f"{a.id} -> {a.status}")
    return 0


def cmd_gate(a):
    run = _run(a)
    names = list(gates_mod.GATES) if a.name in (None, "all") else [a.name]
    rows = [gates_mod.evaluate(run, n, a.block) for n in names]
    if a.json:
        print(jdump(rows))
    else:
        print(table([(r["gate"], r["status"], r["value"], r["threshold"], r["detail"][:90]) for r in rows], ["gate", "status", "value", "threshold", "detail"]))
    return 0 if not any(r["status"] == "fail" for r in rows) else 3


def cmd_lake(a):
    run = _run(a)
    if a.action == "build":
        p = lake.build(run)
        print(f"built {p}  (parquet: {run.p('lake', 'parquet')})")
    else:
        print(lake.ensure(run))
    return 0


def cmd_sql(a):
    run = _run(a)
    if a.recipe:
        if a.recipe not in lake.RECIPES:
            die(f"unknown recipe; available: {sorted(lake.RECIPES)}")
        sql = lake.RECIPES[a.recipe][1]
    elif a.query:
        sql = a.query
    else:
        die("give a SQL string or --recipe NAME")
    cols, rows = lake.run_sql(run, sql, ledger=not a.datasets_only, limit=a.limit)
    print(lake.format_rows(cols, rows, a.format))
    if a.hash:
        print(f"\nrows={len(rows)} result_sha={lake.result_hash(cols, rows)}")
    return 0


def cmd_recipes(a):
    print(table([(k, v[0]) for k, v in lake.RECIPES.items()], ["recipe", "description"]))
    print("\ntables: " + ", ".join(lake.LAKE_TABLES) + " + dataset tables; views: " + ", ".join(lake.VIEWS))
    return 0


def cmd_search(a):
    run = _run(a)
    rows = run.q("SELECT c.source_id, c.id, s.tier, s.stance, substr(c.text, 1, 160) t FROM chunks c JOIN sources s ON s.id=c.source_id "
                 "WHERE s.status='active' AND c.text LIKE ? LIMIT ?", (f"%{a.text}%", a.limit))
    print(table([(r["source_id"], r["id"], r["tier"], r["stance"], r["t"].replace("\n", " ")) for r in rows], ["source", "chunk", "tier", "stance", "text"]) if rows else "(no match)")
    return 0


def cmd_status(a):
    run = _run(a)
    runtime.advance(run)
    print(runtime.status_text(run))
    return 0


def cmd_report(a):
    run = _run(a)
    md = runtime.report_md(run)
    (run.p("reports") / "status.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


def cmd_retro(a):
    run = _run(a)
    if a.score is not None and not 0 <= a.score <= 5:
        die("--score must be 0-5")
    r = runtime.do_retro(run, a.score, a.lesson, a.tag, a.notes)
    print(f"retro recorded: proxy={r['proxy']} score={r['score']}")
    for s in r["suggestions"]:
        print("  mutation suggestion:", s)
    print(f"library updated: {lab_home() / 'registry.sqlite'}  → next forge for similar traits will see these lessons")
    return 0


# ------------------------------------------------------------------ parser
def build_parser():
    p = argparse.ArgumentParser(prog="rlab", description="Multi-domain research lab: forge workflows, run them on a local data lake.")
    sub = p.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--run", help="run directory or run_id (default: $RLAB_RUN or cwd)")

    s = sub.add_parser("doctor", help="check environment"); s.set_defaults(fn=cmd_doctor)
    s = sub.add_parser("setup", help="create lab home + wrapper script"); s.add_argument("--wrapper"); s.set_defaults(fn=cmd_setup)

    s = sub.add_parser("forge", help="synthesise a workflow from domain/direction traits")
    s.add_argument("--traits", help="traits JSON file or - for stdin")
    s.add_argument("--fork", help="saved workflow id/name to fork")
    s.add_argument("--add", action="append"); s.add_argument("--drop", action="append")
    s.add_argument("--set", action="append", help="param override key=value or block.key=value (JSON values)")
    s.add_argument("--name"); s.add_argument("--no-save", action="store_true"); s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_forge)

    s = sub.add_parser("wf", help="workflow library")
    s.add_argument("action", choices=["list", "show", "match"]); s.add_argument("ref", nargs="?"); s.add_argument("--traits")
    s.set_defaults(fn=cmd_wf)

    s = sub.add_parser("init", help="create a run from a saved workflow")
    s.add_argument("--workflow", required=True); s.add_argument("--run-id", required=True)
    s.add_argument("--root"); s.add_argument("--brief"); s.add_argument("--questions")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("questions", parents=[common], help="(re)load questions.jsonl"); s.add_argument("--file", required=True); s.set_defaults(fn=cmd_questions)

    s = sub.add_parser("source", parents=[common], help="add/set/drop a source (parent use)")
    s.add_argument("action", choices=["add", "set", "drop"])
    s.add_argument("--file"); s.add_argument("--id"); s.add_argument("--tier", type=int); s.add_argument("--stance"); s.add_argument("--origin")
    s.add_argument("--url"); s.add_argument("--title"); s.add_argument("--lane"); s.add_argument("--as-of", dest="as_of")
    s.add_argument("--kind"); s.add_argument("--name"); s.add_argument("--pii"); s.add_argument("--access")
    s.set_defaults(fn=cmd_source)

    s = sub.add_parser("next", parents=[common], help="advance the run; list ready subagent tasks")
    s.add_argument("--max", type=int); s.add_argument("--dispatch", action="store_true", help="mark ready tasks as dispatched")
    s.add_argument("--available", help="comma list of live delegate_task option names"); s.add_argument("--json", action="store_true"); s.add_argument("--full", action="store_true", help="embed full contract in payload")
    s.set_defaults(fn=cmd_next)

    s = sub.add_parser("begin", parents=[common], help="(subagent) get the receipt for a task"); s.add_argument("--task", required=True); s.set_defaults(fn=cmd_begin)
    s = sub.add_parser("check", parents=[common], help="(subagent) dry-run validate an output file")
    s.add_argument("--task", required=True); s.add_argument("--file", required=True); s.add_argument("--skip-proof", action="store_true"); s.add_argument("--allow-empty", action="store_true")
    s.set_defaults(fn=cmd_check)
    s = sub.add_parser("load", parents=[common], help="(parent) verify + ingest a task output")
    s.add_argument("--task", required=True); s.add_argument("--file", required=True)
    s.add_argument("--force-unproven", action="store_true"); s.add_argument("--accept-rejects", action="store_true"); s.add_argument("--allow-empty", action="store_true")
    s.set_defaults(fn=cmd_load)

    s = sub.add_parser("done", parents=[common], help="mark a parent block's manual task done"); s.add_argument("--block", required=True); s.add_argument("--note"); s.set_defaults(fn=cmd_done)
    s = sub.add_parser("retry", parents=[common], help="reset a failed task"); s.add_argument("--task", required=True); s.add_argument("--option"); s.add_argument("--note"); s.set_defaults(fn=cmd_retry)
    s = sub.add_parser("waive", parents=[common], help="waive a failing gate (recorded as limitation)")
    s.add_argument("--gate", required=True); s.add_argument("--block"); s.add_argument("--reason", required=True); s.set_defaults(fn=cmd_waive)
    s = sub.add_parser("downgrade", parents=[common], help="(parent) lower a claim's strength; reason required")
    s.add_argument("--claim", required=True); s.add_argument("--strength", required=True); s.add_argument("--reason", required=True); s.set_defaults(fn=cmd_downgrade)
    s = sub.add_parser("reopen", parents=[common], help="force another wave of a block"); s.add_argument("--block", required=True); s.add_argument("--note"); s.set_defaults(fn=cmd_reopen)
    s = sub.add_parser("resolve", parents=[common], help="resolve/disclose a contradiction")
    s.add_argument("--id", help="single mode: contradiction id (e.g. X0001)"); s.add_argument("--status", help="single mode: resolved|disclosed"); s.add_argument("--note", help="single mode: reason")
    s.add_argument("--file", help='batch mode: JSONL, one {"id":"X0001","status":"resolved|disclosed","note":"..."} per line; exclusive with --id/--status/--note; all-or-nothing')
    s.set_defaults(fn=cmd_resolve)
    s = sub.add_parser("gate", parents=[common], help="evaluate gates"); s.add_argument("name", nargs="?"); s.add_argument("--block"); s.add_argument("--json", action="store_true"); s.set_defaults(fn=cmd_gate)
    s = sub.add_parser("lake", parents=[common], help="build/locate the DuckDB+Parquet lake"); s.add_argument("action", choices=["build", "path"]); s.set_defaults(fn=cmd_lake)
    s = sub.add_parser("sql", parents=[common], help="read-only SQL over the lake")
    s.add_argument("query", nargs="?"); s.add_argument("--recipe"); s.add_argument("--hash", action="store_true"); s.add_argument("--format", default="table", choices=["table", "json", "csv"])
    s.add_argument("--limit", type=int); s.add_argument("--datasets-only", action="store_true"); s.set_defaults(fn=cmd_sql)
    s = sub.add_parser("recipes", help="list SQL recipes"); s.set_defaults(fn=cmd_recipes)
    s = sub.add_parser("search", parents=[common], help="substring search in source chunks"); s.add_argument("text"); s.add_argument("--limit", type=int, default=20); s.set_defaults(fn=cmd_search)
    s = sub.add_parser("status", parents=[common], help="run overview"); s.set_defaults(fn=cmd_status)
    s = sub.add_parser("report", parents=[common], help="status report with limitations"); s.set_defaults(fn=cmd_report)
    s = sub.add_parser("retro", parents=[common], help="record outcome into the workflow library")
    s.add_argument("--score", type=float); s.add_argument("--lesson", action="append"); s.add_argument("--tag", action="append"); s.add_argument("--notes")
    s.set_defaults(fn=cmd_retro)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args) or 0
    except RlabError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
