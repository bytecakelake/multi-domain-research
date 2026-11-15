"""Local data lake: SQLite ledger -> DuckDB analysis db + Parquet exports; read-only SQL with recipes."""
from __future__ import annotations

import json
import os
import re
from decimal import Decimal
from pathlib import Path

from .core import Run, die, sha256_text, table

LAKE_TABLES = ["questions", "sources", "chunks", "candidates", "tasks", "evidence", "claims", "claim_evidence",
               "challenges", "contradictions", "findings", "rejects", "events", "datasets"]
TYPEMAP = {"INTEGER": "BIGINT", "REAL": "DOUBLE", "TEXT": "VARCHAR"}

VIEWS = {
    "v_evidence": "SELECT e.*, s.tier, s.stance, s.origin_group, s.lane, s.url, s.title, s.as_of AS source_as_of "
                  "FROM evidence e JOIN sources s ON s.id=e.source_id",
    "v_claims": "SELECT c.*, (SELECT count(*) FROM claim_evidence ce WHERE ce.claim_id=c.id AND ce.relation='supports') AS n_support, "
                "(SELECT count(*) FROM claim_evidence ce WHERE ce.claim_id=c.id AND ce.relation='refutes') AS n_refute, "
                "(SELECT count(*) FROM challenges h WHERE h.claim_id=c.id) AS n_challenges FROM claims c",
}

RECIPES = {
    "coverage": ("질문별 근거 수·독립 원천 수·최고 tier",
                 "SELECT q.id, q.kind, count(DISTINCT e.id) AS n_evidence, count(DISTINCT s.origin_group) AS n_groups, min(s.tier) AS best_tier "
                 "FROM questions q LEFT JOIN evidence e ON e.question_id=q.id AND e.is_null=0 LEFT JOIN sources s ON s.id=e.source_id "
                 "GROUP BY q.id, q.kind ORDER BY q.id"),
    "source_mix": ("출처 풀의 lane·tier·stance 분포",
                   "SELECT lane, tier, stance, count(*) AS n FROM sources WHERE status='active' GROUP BY ALL ORDER BY n DESC"),
    "origin_share": ("origin_group별 근거 점유율(단일 원천 지배 감지)",
                     "SELECT s.origin_group, count(*) AS n_evidence, round(100.0*count(*)/sum(count(*)) OVER (),1) AS pct "
                     "FROM evidence e JOIN sources s ON s.id=e.source_id WHERE e.is_null=0 GROUP BY 1 ORDER BY n_evidence DESC"),
    "saturation": ("출처 순서별 신규 코드 수(포화 곡선)",
                   "WITH ev AS (SELECT s.seq, e.question_id q, e.label, coalesce(e.entity,'') ent FROM evidence e JOIN sources s ON s.id=e.source_id WHERE e.is_null=0), "
                   "first_seen AS (SELECT q, label, ent, min(seq) AS first_seq FROM ev GROUP BY ALL) "
                   "SELECT s.seq, s.id, count(f.q) AS new_codes, sum(count(f.q)) OVER (ORDER BY s.seq) AS cumulative "
                   "FROM sources s LEFT JOIN first_seen f ON f.first_seq=s.seq WHERE s.kind!='dataset' GROUP BY s.seq, s.id ORDER BY s.seq"),
    "agreement": ("이중 코딩 단위별 A/B 라벨 일치",
                  "WITH u AS (SELECT source_id, question_id, coder, mode(label) AS label FROM evidence WHERE coder IN ('A','B') GROUP BY ALL) "
                  "SELECT a.source_id, a.question_id, a.label AS label_A, b.label AS label_B, (a.label=b.label) AS agree "
                  "FROM u a JOIN u b ON a.source_id=b.source_id AND a.question_id=b.question_id AND a.coder='A' AND b.coder='B' ORDER BY 1,2"),
    "claims": ("주장 상태·강도·유형 분포", "SELECT status, strength, ctype, count(*) AS n FROM claims GROUP BY ALL ORDER BY status, strength"),
    "entity_matrix": ("대상×속성 수치 행렬(value_num 평균)",
                      "PIVOT (SELECT entity, attribute, round(avg(value_num),4) AS v FROM evidence WHERE value_num IS NOT NULL AND entity IS NOT NULL "
                      "AND attribute IS NOT NULL GROUP BY ALL) ON attribute USING first(v) ORDER BY entity"),
    "timeline": ("날짜가 있는 근거의 시간순",
                 "SELECT coalesce(e.as_of, s.as_of) AS d, e.entity, e.attribute, e.value, s.id AS source, e.id AS evidence "
                 "FROM evidence e JOIN sources s ON s.id=e.source_id WHERE coalesce(e.as_of, s.as_of) IS NOT NULL ORDER BY d"),
    "contradictions": ("미해결 모순", "SELECT x.id, x.claim_id, x.evidence_id, x.status, c.text FROM contradictions x JOIN claims c ON c.id=x.claim_id WHERE x.status='open'"),
    "tasks": ("블록별 task 상태", "SELECT block, status, count(*) AS n, sum(rows_ok) AS rows_ok, sum(rows_rejected) AS rejected FROM tasks GROUP BY ALL ORDER BY block"),
    "rejects": ("거부 사유 통계", "SELECT kind, reason, count(*) AS n FROM rejects GROUP BY ALL ORDER BY n DESC"),
}


def _duck():
    try:
        import duckdb
    except ImportError:
        die("duckdb is not importable in this interpreter. Run `rlab doctor` for the install command.")
    return duckdb


def _q(s: str) -> str:
    return str(s).replace("'", "''")


def build(run: Run) -> Path:
    duckdb = _duck()
    lake = run.p("lake")
    (lake / "parquet").mkdir(parents=True, exist_ok=True)
    final = lake / "analysis.duckdb"
    tmp = lake / "analysis.build.duckdb"
    for f in (tmp, Path(str(tmp) + ".wal")):
        if f.exists():
            f.unlink()
    con = duckdb.connect(str(tmp))
    for t in LAKE_TABLES:
        info = run.q(f"PRAGMA table_info({t})")
        cols = [(r["name"], TYPEMAP.get((r["type"] or "TEXT").upper().split("(")[0], "VARCHAR")) for r in info]
        con.execute(f'CREATE TABLE {t} ({", ".join(chr(34) + n + chr(34) + " " + ty for n, ty in cols)})')
        rows = run.q(f"SELECT * FROM {t}")
        if rows:
            con.executemany(f'INSERT INTO {t} VALUES ({",".join("?" * len(cols))})', [tuple(r) for r in rows])
        con.execute(f"COPY {t} TO '{_q(str(lake / 'parquet' / (t + '.parquet')))}' (FORMAT PARQUET)")
    for d in run.q("SELECT name, parquet FROM datasets"):
        con.execute(f'CREATE TABLE "{d["name"]}" AS SELECT * FROM read_parquet(\'{_q(d["parquet"])}\')')
    for name, sql in VIEWS.items():
        con.execute(f"CREATE VIEW {name} AS {sql}")
    con.close()
    for f in (final, Path(str(final) + ".wal")):
        if f.exists():
            f.unlink()
    os.replace(tmp, final)
    (lake / ".rev").write_text(str(run.meta("rev", 0)), encoding="utf-8")
    return final


def ensure(run: Run) -> Path:
    db = run.p("lake", "analysis.duckdb")
    stamp = run.p("lake", ".rev")
    if not db.exists() or not stamp.exists() or stamp.read_text(encoding="utf-8").strip() != str(run.meta("rev", 0)):
        build(run)
    return db


def dataset_con(run: Run):
    """In-memory DuckDB holding only dataset tables (used to verify SQL evidence during load)."""
    duckdb = _duck()
    con = duckdb.connect(":memory:")
    for d in run.q("SELECT name, parquet FROM datasets"):
        con.execute(f'CREATE TABLE "{d["name"]}" AS SELECT * FROM read_parquet(\'{_q(d["parquet"])}\')')
    con.execute("SET enable_external_access=false")
    return con


_STARTS = re.compile(r"(?is)^\s*(select|with|describe|show|pivot|summarize|from|explain)\b")
_BAD = re.compile(r"(?i)\b(copy|attach|detach|install|load|export|import|pragma|call|set|create|insert|update|delete|drop|alter|read_\w+|glob|write_\w+|duckdb_\w+|pragma_\w+|sniff_\w+|current_setting|query_table|getenv)\b")


def _mask(s: str) -> str:
    """Blank out string literals, quoted identifiers and comments so keyword/;-checks only see real SQL tokens."""
    out, i, n = [], 0, len(s)
    while i < n:
        c = s[i]
        if c in ("'", '"'):
            j = i + 1
            while j < n:
                if s[j] == c:
                    if s[j + 1:j + 2] == c:
                        j += 2
                        continue
                    break
                j += 1
            out.append(c + c)
            i = j + 1
        elif s.startswith("--", i):
            j = s.find("\n", i)
            i = n if j < 0 else j
        elif s.startswith("/*", i):
            j = s.find("*/", i + 2)
            i = n if j < 0 else j + 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def check_sql(sql: str) -> str:
    s = sql.strip().rstrip(";").strip()
    if not s:
        die("empty SQL")
    m = _mask(s)
    if ";" in m.rstrip().rstrip(";"):
        die("only a single statement is allowed")
    if not _STARTS.match(m):
        die("only read queries are allowed (SELECT/WITH/DESCRIBE/SHOW/PIVOT/SUMMARIZE/FROM)")
    if re.search(r'""\s*\(', m):
        die("quoted function names are not allowed")
    bad = _BAD.search(m)
    if bad:
        die(f"disallowed keyword in read-only SQL: {bad.group(1)}")
    return s


def _canon(v):
    if v is None:
        return None
    if isinstance(v, float):
        return round(v, 6)
    if isinstance(v, Decimal):
        return round(float(v), 6)
    if isinstance(v, (int, str, bool)):
        return v
    return str(v)


def result_hash(cols, rows) -> str:
    canon = [[_canon(v) for v in r] for r in rows]
    canon.sort(key=lambda r: json.dumps(r, ensure_ascii=False, default=str))
    return sha256_text(json.dumps({"cols": list(cols), "rows": canon}, ensure_ascii=False, default=str))[:16]


def run_sql(run: Run, sql: str, ledger: bool = True, limit: int | None = None):
    """Execute read-only SQL. ledger=True uses the full lake; False uses datasets only."""
    s = check_sql(sql)
    duckdb = _duck()
    if ledger:
        db = ensure(run)
        con = duckdb.connect(str(db), read_only=True, config={"enable_external_access": False})
    else:
        con = dataset_con(run)
    try:
        cur = con.execute(s)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchmany(limit) if limit else cur.fetchall()
    except Exception as e:  # noqa: BLE001
        die(f"SQL error: {str(e).splitlines()[0][:300]}")
    finally:
        con.close()
    return cols, rows


def format_rows(cols, rows, fmt="table") -> str:
    if fmt == "json":
        return json.dumps([dict(zip(cols, [_canon(v) for v in r])) for r in rows], ensure_ascii=False, indent=2)
    if fmt == "csv":
        import csv
        import io
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(cols)
        w.writerows([["" if v is None else v for v in r] for r in rows])
        return buf.getvalue()
    return table(rows, list(cols)) if rows else "(0 rows)"


def register_dataset(run: Run, path: Path, name: str) -> dict:
    duckdb = _duck()
    name = re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_") or "dataset"
    if name[0].isdigit() or name in LAKE_TABLES or name in VIEWS:
        name = "ds_" + name
    if run.one("SELECT 1 FROM datasets WHERE name=?", (name,)):
        die(f"dataset name already registered: {name}")
    ext = path.suffix.lower()
    reader = {".csv": "read_csv_auto", ".tsv": "read_csv_auto", ".parquet": "read_parquet", ".json": "read_json_auto", ".jsonl": "read_json_auto"}.get(ext)
    if not reader:
        die(f"unsupported dataset format: {ext} (csv/tsv/parquet/json/jsonl)")
    out = run.p("lake", "datasets", f"{name}.parquet")
    out.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(":memory:")
    try:
        con.execute(f"COPY (SELECT * FROM {reader}('{_q(str(path))}')) TO '{_q(str(out))}' (FORMAT PARQUET)")
        pq = f"read_parquet('{_q(str(out))}')"
        desc = con.execute(f"DESCRIBE SELECT * FROM {pq}").fetchall()
        n = con.execute(f"SELECT count(*) FROM {pq}").fetchone()[0]
        cols = [d[0] for d in desc][:60]
        nn = con.execute("SELECT " + ", ".join(f'count("{c}")' for c in cols) + f" FROM {pq}").fetchone() if cols else ()
        sample = con.execute(f"SELECT * FROM {pq} LIMIT 5").fetchall()
    except Exception as e:  # noqa: BLE001
        die(f"dataset load failed: {str(e).splitlines()[0][:300]}")
    finally:
        con.close()
    lines = [f"dataset {name}: {n} rows, {len(desc)} cols (table name in SQL: {name})"]
    for i, d in enumerate(desc[:60]):
        lines.append(f"- {d[0]} {d[1]} nulls={n - nn[i]}")
    lines.append("sample rows:")
    lines += ["  " + json.dumps([_canon(v) for v in r], ensure_ascii=False, default=str) for r in sample]
    profile = "\n".join(lines)
    return {"name": name, "parquet": str(out), "n_rows": n, "n_cols": len(desc), "profile": profile}
