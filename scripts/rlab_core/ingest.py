"""Ingest subagent output into the ledger with machine verification.

Every row is validated; quotes must occur verbatim (after normalisation) in the stored source text;
SQL evidence is re-executed and its result hash must match; tasks must present the receipt issued by `begin`.
A task load is transactional: too many rejects => rollback.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
from pathlib import Path

from . import lake as lake_mod
from .core import Run, die, norm, now, read_jsonl, sha256_text

KIND_ORDER = ["candidates", "sources", "evidence", "claims", "challenges", "findings"]
BLOCK_EXTRA = {"adversary": {"sources", "evidence"}, "analyze-claims": {"findings"}, "compare-matrix": {"findings"},
               "timeline-build": {"findings"}, "rival-hypotheses": {"findings"}, "base-rates": {"findings"}}
POLARITY = {"supports", "refutes", "neutral"}
STRENGTHS = {"weak", "moderate", "strong"}
VERDICTS = {"stands", "weakened", "refuted", "inconclusive"}
SEVERITY = {"info", "warn", "block"}
BINARY_EXT = {".pdf", ".docx", ".pptx", ".xlsx", ".png", ".jpg", ".jpeg", ".gif", ".mp3", ".mp4", ".wav", ".zip", ".webp"}
MAX_BYTES = 30 * 1024 * 1024


def _s(row, key):
    v = row.get(key)
    if v is None:
        return None
    v = str(v).strip()
    return v or None


def _truthy(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "y")


def strip_html(s: str) -> str:
    s = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|tr|section|article)>", "\n", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n\n", s).strip()


def to_text(p: Path) -> str:
    ext = p.suffix.lower()
    if ext in BINARY_EXT:
        die(f"binary format {ext}: convert to text first")
    if p.stat().st_size > MAX_BYTES:
        die("file too large (>30MB)")
    raw = p.read_bytes()
    if b"\x00" in raw[:4096]:
        die("binary content detected: convert to text first")
    s = raw.decode("utf-8", errors="replace")
    return strip_html(s) if ext in (".html", ".htm") else s


def chunk_text(text: str, maxc: int = 1200) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    out, cur = [], ""
    for p in paras:
        pieces = [p[i:i + maxc] for i in range(0, len(p), maxc)] if len(p) > maxc else [p]
        for piece in pieces:
            if cur and len(cur) + len(piece) + 2 > maxc:
                out.append(cur)
                cur = piece
            else:
                cur = f"{cur}\n\n{piece}" if cur else piece
    if cur:
        out.append(cur)
    return out


def source_text(run: Run, sid: str, ctx: dict) -> str | None:
    cache = ctx.setdefault("text_cache", {})
    if sid not in cache:
        p = run.p("raw", f"{sid}.txt")
        cache[sid] = norm(p.read_text(encoding="utf-8", errors="replace")) if p.exists() else None
    return cache[sid]


# ---------------------------------------------------------------- sources
def add_source(run: Run, row: dict, tid: str | None, ctx: dict) -> tuple[str, str, str | None]:
    """returns (status, message, source_id) with status in ok|dup|err."""
    raw_path = _s(row, "path")
    if not raw_path:
        return "err", "missing required field: path", None
    p = Path(raw_path).expanduser()
    if not p.is_absolute():
        p = run.root / p
    if not p.is_file():
        return "err", f"path does not exist: {p}", None
    if not ctx.get("trusted"):
        # subagent-supplied paths must live under staging/incoming (blocks reading arbitrary files such as secrets)
        try:
            p.resolve().relative_to((run.root / "staging" / "incoming").resolve())
        except ValueError:
            return "err", f"path must be inside {run.root / 'staging' / 'incoming'} (got {p})", None
    try:
        tier = int(row.get("tier"))
    except (TypeError, ValueError):
        return "err", "tier must be an integer 1-4", None
    if tier not in (1, 2, 3, 4):
        return "err", "tier must be 1-4", None
    stance, og = _s(row, "stance"), _s(row, "origin_group")
    if not stance or not og:
        return "err", "stance and origin_group are required", None
    url, title = _s(row, "url"), _s(row, "title")
    if not url and not title:
        return "err", "need url or title", None
    kind = _s(row, "kind") or "text"
    if url:
        ex = run.one("SELECT id FROM sources WHERE url=? AND status='active'", (url,))
        if ex:
            _link(run, row, ex["id"], ctx)
            return "dup", f"url already ingested as {ex['id']}", ex["id"]
    try:
        if kind == "dataset":
            ds = lake_mod.register_dataset(run, p, _s(row, "name") or title or p.stem)
            text = ds["profile"]
            ctx.setdefault("created", []).append(Path(ds["parquet"]))
        else:
            text = to_text(p)
            ds = None
    except Exception as e:  # noqa: BLE001
        return "err", str(e)[:300], None
    if len(norm(text)) < 20:
        return "err", "source text is empty/too short", None
    h = sha256_text(norm(text))
    ex = run.one("SELECT id FROM sources WHERE sha256=? AND status='active'", (h,))
    if ex and kind != "dataset":
        _link(run, row, ex["id"], ctx)
        return "dup", f"identical text already ingested as {ex['id']}", ex["id"]
    sid = run.nid("S")
    (run.p("raw") / f"{sid}.txt").write_text(text, encoding="utf-8")
    ctx.setdefault("created", []).append(run.p("raw") / f"{sid}.txt")
    if p.suffix.lower() not in (".txt",):
        shutil.copy2(p, run.p("raw") / f"{sid}.orig{p.suffix.lower()}")
        ctx["created"].append(run.p("raw") / f"{sid}.orig{p.suffix.lower()}")
    seq = (run.one("SELECT COALESCE(MAX(seq),0)+1 n FROM sources")["n"])
    pii = "flagged" if _truthy(row.get("pii")) else "clear"
    run.db.execute("INSERT INTO sources(id,kind,url,title,tier,stance,origin_group,lane,as_of,captured_at,path,sha256,n_chars,pii_status,access,task_id,seq) "
                   "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (sid, kind, url, title, tier, stance, og, _s(row, "lane"), _s(row, "as_of"), now(), str(run.p("raw") / f"{sid}.txt"),
                    h, len(text), pii, _s(row, "access"), tid, seq))
    if ds:
        run.db.execute("INSERT INTO datasets(name,source_id,parquet,n_rows,n_cols,profile) VALUES(?,?,?,?,?,?)",
                       (ds["name"], sid, ds["parquet"], ds["n_rows"], ds["n_cols"], ds["profile"]))
    else:
        for i, ch in enumerate(chunk_text(text), 1):
            run.db.execute("INSERT INTO chunks(id,source_id,ord,text) VALUES(?,?,?,?)", (f"{sid}.c{i:03d}", sid, i, ch))
    _link(run, row, sid, ctx)
    return "ok", sid, sid


def _link(run: Run, row: dict, sid: str, ctx: dict) -> None:
    if _truthy(row.get("pii")):  # a duplicate report must never un-flag, only flag
        run.db.execute("UPDATE sources SET pii_status='flagged' WHERE id=?", (sid,))
    if _s(row, "ref"):
        ctx.setdefault("refs_src", {})[_s(row, "ref")] = sid
    cid = row.get("cid")
    if cid is not None:
        try:
            run.db.execute("UPDATE candidates SET status='collected' WHERE id=?", (int(cid),))
        except (TypeError, ValueError):
            pass


def add_candidate(run: Run, row: dict, tid: str, ctx: dict):
    url = _s(row, "url")
    if not url:
        return "err", "missing required field: url"
    if not (_s(row, "title") or _s(row, "why")):
        return "err", "need title or why"
    if run.one("SELECT 1 FROM candidates WHERE url=?", (url,)) or run.one("SELECT 1 FROM sources WHERE url=? AND status='active'", (url,)):
        return "dup", "url already known"
    try:
        tg = int(row["tier_guess"]) if row.get("tier_guess") is not None else None
    except (TypeError, ValueError):
        return "err", "tier_guess must be integer 1-4"
    wave = ctx.get("task", {}).get("wave")
    run.db.execute("INSERT INTO candidates(url,title,why,lane,tier_guess,origin_guess,task_id,wave) VALUES(?,?,?,?,?,?,?,?)",
                   (url, _s(row, "title"), _s(row, "why"), _s(row, "lane"), tg, _s(row, "origin_guess"), tid, wave))
    return "ok", ""


# ---------------------------------------------------------------- evidence
def _question_labels(run: Run, qid: str) -> list[str]:
    r = run.one("SELECT labels FROM questions WHERE id=?", (qid,))
    if r and r["labels"]:
        try:
            return list(json.loads(r["labels"]))
        except Exception:  # noqa: BLE001
            return []
    return []


def add_evidence(run: Run, row: dict, tid: str, ctx: dict):
    task = ctx["task"]
    sid = _s(row, "source_id")
    sid = ctx.get("refs_src", {}).get(sid, sid)
    if not sid or not run.one("SELECT 1 FROM sources WHERE id=? AND status='active'", (sid,)):
        return "err", f"unknown or inactive source_id: {sid}"
    qid = _s(row, "question_id")
    if not qid or not run.one("SELECT 1 FROM questions WHERE id=?", (qid,)):
        return "err", f"unknown question_id: {qid}"
    label = _s(row, "label")
    if not label:
        return "err", "label is required"
    labels = _question_labels(run, qid) or ["relevant"]
    if label != "none" and label not in labels:
        return "err", f"label '{label}' not in codebook for {qid}: {labels + ['none']}"
    pol = _s(row, "polarity") or "neutral"
    if pol not in POLARITY:
        return "err", f"polarity must be one of {sorted(POLARITY)}"
    conf = None
    if row.get("confidence") is not None:
        try:
            conf = float(row["confidence"])
        except (TypeError, ValueError):
            return "err", "confidence must be a number 0-1"
        if not 0 <= conf <= 1:
            return "err", "confidence must be within 0-1"
    vnum = None
    if row.get("value_num") is not None:
        try:
            vnum = float(row["value_num"])
        except (TypeError, ValueError):
            return "err", "value_num must be numeric"
    method = _s(row, "method") or "quote"
    quote, sql, rsha, is_null = row.get("quote"), None, None, 0
    if method == "sql":
        sql, rsha = _s(row, "sql"), _s(row, "result_sha")
        if not sql or not rsha:
            return "err", "sql evidence needs sql and result_sha"
        srow = run.one("SELECT kind FROM sources WHERE id=?", (sid,))
        if srow["kind"] != "dataset":
            return "err", "sql evidence must cite a dataset source"
        if label == "none":
            return "err", "label 'none' cannot be used with sql evidence"
        dn = run.one("SELECT name FROM datasets WHERE source_id=?", (sid,))
        if not dn or not re.search(rf"\b{re.escape(dn['name'])}\b", sql, re.I):
            return "err", f"sql must reference the cited dataset table '{dn['name'] if dn else '?'}' (source {sid})"
        try:
            cols, rows = lake_mod.run_sql(run, sql, ledger=False)
        except Exception as e:  # noqa: BLE001
            return "err", f"sql re-execution failed: {e}"
        got = lake_mod.result_hash(cols, rows)
        if got != rsha:
            return "err", f"result_sha mismatch (re-executed {got}, claimed {rsha})"
        quote = "SQL: " + sql + " -> " + json.dumps([list(map(lake_mod._canon, r)) for r in rows[:3]], ensure_ascii=False, default=str)
    elif method == "quote":
        if label == "none" and quote not in (None, "") and str(quote).strip() != "":
            return "err", "label 'none' requires quote=null (a none row carrying a quote would count as evidence)"
        if quote is None or str(quote).strip() == "":
            if label != "none":
                return "err", "quote is required unless label='none'"
            is_null, quote = 1, None
        else:
            q = str(quote)
            if "..." in q or "\u2026" in q:
                return "err", "quote contains an ellipsis; quote one continuous passage"
            nq = norm(q)
            if len(nq) < 8:
                return "err", "quote too short (<8 chars)"
            text = source_text(run, sid, ctx)
            if text is None:
                return "err", f"source text missing for {sid}"
            if nq not in text:
                return "err", "quote not found verbatim in source text"
            quote = q.strip()
    else:
        return "err", "method must be quote or sql"
    coder = task["coder"]
    same = run.q("SELECT id, quote, label, is_null, COALESCE(entity,'') ent, COALESCE(attribute,'') att FROM evidence "
                 "WHERE source_id=? AND question_id=? AND COALESCE(coder,'')=COALESCE(?, '')", (sid, qid, coder))
    for ex in same:
        same_row = (is_null and ex["is_null"]) or (not is_null and not ex["is_null"] and norm(ex["quote"] or "") == norm(quote or "")
                                                   and ex["label"] == label and ex["ent"] == (_s(row, "entity") or "") and ex["att"] == (_s(row, "attribute") or ""))
        if same_row:
            if _s(row, "ref"):
                ctx.setdefault("refs_ev", {})[_s(row, "ref")] = ex["id"]
            return "dup", f"same evidence exists as {ex['id']}"
    for ex in same:
        if bool(ex["is_null"]) != bool(is_null):
            return "err", "this coder already coded the source×question as " + ("'none'" if ex["is_null"] else "evidence") + "; one coding per unit"
        if coder in ("A", "B") and ex["label"] != label:
            return "err", f"dual coding allows ONE label per source×question (already '{ex['label']}')"
    eid = run.nid("E", 6)
    run.db.execute("INSERT INTO evidence(id,task_id,source_id,question_id,locator,quote,label,polarity,entity,attribute,value,value_num,unit,as_of,confidence,coder,method,sql,result_sha,is_null,note) "
                   "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (eid, tid, sid, qid, _s(row, "locator"), quote, label, pol, _s(row, "entity"), _s(row, "attribute"),
                    _s(row, "value"), vnum, _s(row, "unit"), _s(row, "as_of"), conf, task["coder"], method, sql, rsha, is_null, _s(row, "note")))
    if _s(row, "ref"):
        ctx.setdefault("refs_ev", {})[_s(row, "ref")] = eid
    return "ok", eid


# ---------------------------------------------------------------- claims & challenges
def _resolve_ev(run: Run, ids, ctx, allow_null=False):
    if isinstance(ids, str):
        ids = [ids]
    out = []
    for x in ids or []:
        x = str(x).strip()
        eid = ctx.get("refs_ev", {}).get(x, x)
        r = run.one("SELECT is_null FROM evidence WHERE id=?", (eid,))
        if not r:
            return None, f"unknown evidence id: {x}"
        if r["is_null"] and not allow_null:
            return None, f"{eid} is a 'none' row and cannot support a claim"
        out.append(eid)
    return list(dict.fromkeys(out)), None


def add_claim(run: Run, row: dict, tid: str, ctx: dict):
    task = ctx["task"]
    bid = task["block"]
    bp = run.params(bid)
    text, qid = _s(row, "text"), _s(row, "question_id")
    if not text:
        return "err", "text is required"
    if not qid or not run.one("SELECT 1 FROM questions WHERE id=?", (qid,)):
        return "err", f"unknown question_id: {qid}"
    ctype, strength = _s(row, "ctype"), _s(row, "strength")
    allowed = bp.get("allowed_ctypes", [])
    if ctype not in allowed:
        return "err", f"ctype '{ctype}' not allowed for this direction (allowed: {allowed})"
    if strength not in STRENGTHS:
        return "err", f"strength must be one of {sorted(STRENGTHS)}"
    if strength == "strong" and ctype not in ("fact", "measurement"):
        return "err", "strength 'strong' is limited to fact/measurement claims"
    for f in bp.get("require_fields", []):
        if not _s(row, f):
            return "err", f"field '{f}' is required for this block"
    sup, e1 = _resolve_ev(run, row.get("evidence_ids"), ctx)
    if e1:
        return "err", e1
    if not sup:
        return "err", "evidence_ids must contain at least one evidence id"
    cnt, e2 = _resolve_ev(run, row.get("counter_evidence_ids"), ctx)
    if e2:
        return "err", e2
    dup = run.one("SELECT id FROM claims WHERE question_id=? AND text=?", (qid, text))
    if dup:
        n_new = 0
        for e in sup:
            n_new += run.db.execute("INSERT OR IGNORE INTO claim_evidence VALUES(?,?,?)", (dup["id"], e, "supports")).rowcount
        for e in cnt or []:
            if run.db.execute("INSERT OR IGNORE INTO claim_evidence VALUES(?,?,?)", (dup["id"], e, "refutes")).rowcount:
                n_new += 1
                run.db.execute("INSERT INTO contradictions(id,claim_id,evidence_id,status,note) VALUES(?,?,?,?,?)",
                               (run.nid("X"), dup["id"], e, "open", "counter evidence linked by analyst"))
        return "dup", f"same claim exists as {dup['id']} (merged {n_new} new evidence link(s))"
    cid = run.nid("K")
    run.db.execute("INSERT INTO claims(id,task_id,question_id,text,ctype,strength,scope,time_sensitive,falsifier,block) VALUES(?,?,?,?,?,?,?,?,?,?)",
                   (cid, tid, qid, text, ctype, strength, _s(row, "scope"), 1 if _truthy(row.get("time_sensitive")) else 0, _s(row, "falsifier"), bid))
    for e in sup:
        run.db.execute("INSERT OR IGNORE INTO claim_evidence VALUES(?,?,?)", (cid, e, "supports"))
    for e in cnt or []:
        run.db.execute("INSERT OR IGNORE INTO claim_evidence VALUES(?,?,?)", (cid, e, "refutes"))
        x = run.nid("X")
        run.db.execute("INSERT INTO contradictions(id,claim_id,evidence_id,status,note) VALUES(?,?,?,?,?)", (x, cid, e, "open", "counter evidence linked by analyst"))
    return "ok", cid


def add_challenge(run: Run, row: dict, tid: str, ctx: dict):
    cid = _s(row, "claim_id")
    if not cid or not run.one("SELECT 1 FROM claims WHERE id=?", (cid,)):
        return "err", f"unknown claim_id: {cid}"
    ef, log = _s(row, "expected_falsifier"), row.get("search_log")
    if isinstance(log, (list, dict)):
        log = json.dumps(log, ensure_ascii=False)
    log = _s({"v": log}, "v")
    if not ef or not log:
        return "err", "expected_falsifier and search_log are required"
    verdict = _s(row, "verdict")
    if verdict not in VERDICTS:
        return "err", f"verdict must be one of {sorted(VERDICTS)}"
    found = _truthy(row.get("found"))
    ids = row.get("evidence_refs") or row.get("evidence_ids") or []
    ev, err = _resolve_ev(run, ids, ctx)
    if err:
        return "err", err
    if verdict in ("weakened", "refuted") and not ev:
        return "err", f"verdict '{verdict}' needs evidence_refs/evidence_ids"
    if verdict == "stands" and found:
        return "err", "found=true contradicts verdict 'stands'"
    chid = run.nid("C")
    run.db.execute("INSERT INTO challenges(id,task_id,claim_id,expected_falsifier,search_log,found,verdict,note) VALUES(?,?,?,?,?,?,?,?)",
                   (chid, tid, cid, ef, log, 1 if found else 0, verdict, _s(row, "note")))
    for e in ev or []:
        run.db.execute("INSERT OR IGNORE INTO claim_evidence VALUES(?,?,?)", (cid, e, "refutes"))
        x = run.nid("X")
        run.db.execute("INSERT INTO contradictions(id,claim_id,evidence_id,status,note) VALUES(?,?,?,?,?)", (x, cid, e, "open", f"from challenge {chid} ({verdict})"))
    return "ok", chid


def add_finding(run: Run, row: dict, tid: str, ctx: dict):
    kind = _s(row, "type") or (_s(row, "kind") if _s(row, "kind") != "findings" else None)
    sev, note = _s(row, "severity"), _s(row, "note")
    if not kind or not note:
        return "err", "finding needs a classification (`kind`, or `type` when kind='findings') and a note"
    if sev not in SEVERITY:
        return "err", f"severity must be one of {sorted(SEVERITY)}"
    fid = run.nid("F")
    run.db.execute("INSERT INTO findings(id,task_id,block,kind,severity,ref,note) VALUES(?,?,?,?,?,?,?)",
                   (fid, tid, ctx["task"]["block"], kind, sev, _s(row, "ref"), note))
    return "ok", fid


# ---------------------------------------------------------------- claim status
def recompute_claims(run: Run) -> None:
    minind = run.params().get("min_independent", 2)
    for c in run.q("SELECT id FROM claims"):
        sup = run.q("SELECT s.origin_group og, s.tier tier FROM claim_evidence ce JOIN evidence e ON e.id=ce.evidence_id JOIN sources s ON s.id=e.source_id "
                    "WHERE ce.claim_id=? AND ce.relation='supports' AND e.is_null=0 AND s.status='active'", (c["id"],))
        ref = run.q("SELECT DISTINCT s.origin_group og FROM claim_evidence ce JOIN evidence e ON e.id=ce.evidence_id JOIN sources s ON s.id=e.source_id "
                    "WHERE ce.claim_id=? AND ce.relation='refutes'", (c["id"],))
        groups = {r["og"] for r in sup}
        best = min([r["tier"] for r in sup], default=None)
        openx = run.one("SELECT COUNT(*) n FROM contradictions WHERE claim_id=? AND status='open'", (c["id"],))["n"]
        if not sup:
            st = "unsupported"
        elif openx:
            st = "contested"
        elif len(groups) >= minind and best <= 2:
            st = "supported"
        elif (best <= 2) or len(groups) >= minind:
            st = "partial"
        else:
            st = "weak"
        run.db.execute("UPDATE claims SET status=?, n_groups=?, best_tier=?, n_refute_groups=? WHERE id=?", (st, len(groups), best, len(ref), c["id"]))


# ---------------------------------------------------------------- task load / check
ADDERS = {"candidates": add_candidate, "evidence": add_evidence, "claims": add_claim, "challenges": add_challenge, "findings": add_finding}


def check_proof(task, meta_rows, n_rows):
    if task["manual"]:
        return True, "manual"
    if not meta_rows:
        return False, "missing _meta line (first line must be {\"_meta\": {task, receipt, n_rows}})"
    m = meta_rows[0]["_meta"] if isinstance(meta_rows[0].get("_meta"), dict) else {}
    if m.get("task") != task["id"]:
        return False, f"_meta.task '{m.get('task')}' != {task['id']}"
    if str(m.get("receipt")) != task["receipt"]:
        return False, "receipt mismatch: run `rlab begin --task ...` and copy its receipt (a guessed or stale receipt is rejected)"
    if not task["begun"]:
        return False, "`rlab begin` was never run for this task attempt"
    try:
        declared = int(m.get("n_rows"))
    except (TypeError, ValueError):
        return False, "_meta.n_rows (integer) is required"
    if declared != n_rows:
        return False, f"_meta.n_rows={m['n_rows']} but file has {n_rows} data rows (truncated or edited after meta)"
    return True, "ok"


def ingest_file(run: Run, tid: str, path, commit: bool = True, force_unproven: bool = False,
                accept_rejects: bool = False, allow_empty: bool = False) -> dict:
    task = run.one("SELECT * FROM tasks WHERE id=?", (tid,))
    if not task:
        die(f"unknown task: {tid}")
    if task["status"] == "verified":
        die(f"{tid} is already verified; use `rlab retry` only for failed tasks")
    p = Path(path)
    if not p.is_file():
        die(f"file not found: {p}")
    b = run.block(task["block"])
    default_kind = b.get("kind")
    allowed = ({default_kind} if default_kind else set()) | BLOCK_EXTRA.get(b["id"], set())
    rows_all = read_jsonl(p)
    meta = [r for r in rows_all if "_meta" in r]
    rows = [r for r in rows_all if "_meta" not in r]
    res = {"task": tid, "block": b["id"], "rows": len(rows), "ok": 0, "dup": 0, "rejects": [], "proof": None, "committed": False, "status": None}
    proof_ok, proof_msg = check_proof(task, meta, len(rows))
    res["proof"] = proof_msg
    m0 = meta[0].get("_meta") if meta and isinstance(meta[0].get("_meta"), dict) else {}
    blocker = None
    if m0.get("empty") is True and not rows:  # deliberate empty result with a stated blocker
        allow_empty, blocker = True, str(m0.get("blocker") or "")[:300]
    if not proof_ok and not force_unproven:
        res["status"] = "proof_failed"
        if commit:
            run.db.execute("UPDATE tasks SET status='proof_failed', returned=?, notes=? WHERE id=?", (now(), "proof: " + proof_msg, tid))
            run.event("proof_failed", tid, reason=proof_msg)
        return res
    ctx: dict = {"task": dict(task)}
    grouped: dict[str, list] = {k: [] for k in KIND_ORDER}
    for r in rows:
        if "_parse_error" in r:
            res["rejects"].append({"kind": "?", "line": r["_line"], "reason": "invalid JSON: " + r["_parse_error"], "row": r.get("_raw")})
            continue
        kind = r.get("kind")
        if kind not in KIND_ORDER:
            # `kind` doubles as the finding classification in findings rows; only canonical row kinds select a parser
            kind = default_kind
        if kind not in allowed:
            res["rejects"].append({"kind": str(kind), "line": r["_line"], "reason": f"kind '{kind}' not allowed in block {b['id']} (allowed: {sorted(allowed)})", "row": json.dumps(r, ensure_ascii=False)[:200]})
            continue
        grouped[kind].append(r)
    run.db.execute("BEGIN")
    try:
        for kind in KIND_ORDER:
            for r in grouped[kind]:
                if kind == "sources":
                    st, msg, _ = add_source(run, r, tid, ctx)
                else:
                    st, msg = ADDERS[kind](run, r, tid, ctx)
                if st == "ok":
                    res["ok"] += 1
                elif st == "dup":
                    res["dup"] += 1
                else:
                    res["rejects"].append({"kind": kind, "line": r["_line"], "reason": msg, "row": json.dumps({k: v for k, v in r.items() if not k.startswith("_")}, ensure_ascii=False)[:300]})
        n_rej = len(res["rejects"])
        total = res["ok"] + n_rej
        rate = n_rej / total if total else 0.0
        thr = run.params(b["id"]).get("max_reject_rate", 0.05)
        too_many = rate > thr and not accept_rejects
        empty = (res["ok"] + res["dup"] == 0) and not allow_empty
        res["reject_rate"] = round(rate, 4)
        res["threshold"] = thr
        if too_many or empty:
            res["status"] = "failed"
            res["fail_reason"] = (f"reject rate {rate:.1%} > {thr:.0%}" if too_many else "no valid rows (use --allow-empty if intentionally empty)")
            run.db.execute("ROLLBACK")
        elif not commit:
            res["status"] = "check_ok"
            run.db.execute("ROLLBACK")
        else:
            if b["id"] == "collect":
                run.db.execute("UPDATE candidates SET status='unreached' WHERE assigned_to=? AND status='assigned'", (tid,))
            recompute_claims(run)
            run.db.execute("UPDATE tasks SET status='verified', returned=?, verified=?, rows_ok=?, rows_rejected=?, rows_dup=?, notes=? WHERE id=?",
                           (now(), now(), res["ok"], n_rej, res["dup"], ("unproven: " + proof_msg) if not proof_ok else (("empty: " + blocker) if blocker is not None else None), tid))
            run.bump()
            run.event("verified", tid, ok=res["ok"], dup=res["dup"], rejected=n_rej)
            run.db.execute("COMMIT")
            res["status"], res["committed"] = "verified", True
    except Exception:
        run.db.execute("ROLLBACK")
        raise
    if res["status"] != "verified":  # rolled back or dry-run: remove files written during processing (raw text, datasets)
        for fp in ctx.get("created", []):
            try:
                Path(fp).unlink()
            except OSError:
                pass
    if commit and res["status"] == "failed":
        for rj in res["rejects"]:
            run.db.execute("INSERT INTO rejects(task_id,kind,line,reason,row_json,ts) VALUES(?,?,?,?,?,?)", (tid, rj["kind"], rj["line"], rj["reason"], rj["row"], now()))
        run.db.execute("UPDATE tasks SET status='failed', returned=?, rows_ok=?, rows_rejected=?, notes=? WHERE id=?",
                       (now(), 0, len(res["rejects"]), res.get("fail_reason"), tid))
        run.event("failed", tid, reason=res.get("fail_reason"))
    elif commit and res["status"] == "verified" and res["rejects"]:
        for rj in res["rejects"]:
            run.db.execute("INSERT INTO rejects(task_id,kind,line,reason,row_json,ts) VALUES(?,?,?,?,?,?)", (tid, rj["kind"], rj["line"], rj["reason"], rj["row"], now()))
    return res


# ---------------------------------------------------------------- source maintenance
def drop_source(run: Run, sid: str) -> int:
    if not run.one("SELECT 1 FROM sources WHERE id=?", (sid,)):
        die(f"unknown source: {sid}")
    run.db.execute("BEGIN")
    evs = [r["id"] for r in run.q("SELECT id FROM evidence WHERE source_id=?", (sid,))]
    for e in evs:
        run.db.execute("DELETE FROM claim_evidence WHERE evidence_id=?", (e,))
        run.db.execute("DELETE FROM contradictions WHERE evidence_id=?", (e,))
    run.db.execute("DELETE FROM evidence WHERE source_id=?", (sid,))
    run.db.execute("DELETE FROM chunks WHERE source_id=?", (sid,))
    run.db.execute("UPDATE sources SET status='dropped' WHERE id=?", (sid,))
    recompute_claims(run)
    run.bump()
    run.event("source_dropped", None, source=sid, evidence_removed=len(evs))
    run.db.execute("COMMIT")
    p = run.p("raw", f"{sid}.txt")
    if p.exists():
        p.write_text("", encoding="utf-8")
    for f in run.p("raw").glob(f"{sid}.orig*"):
        f.unlink()
    return len(evs)
