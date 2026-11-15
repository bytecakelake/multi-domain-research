"""Shared helpers: paths, ledger schema, Run handle, text normalisation."""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[2]
ASSETS = SKILL_DIR / "assets"


class RlabError(Exception):
    """User-facing error (printed without traceback)."""


def die(msg: str):
    raise RlabError(msg)


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def lab_home() -> Path:
    h = os.environ.get("RLAB_HOME")
    if h:
        return Path(h)
    if Path("/workspace").is_dir():
        return Path("/workspace/research-lab")
    return Path.home() / ".hermes" / "research-lab"


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def sha256_text(s: str) -> str:
    return sha256_bytes(s.encode("utf-8"))


_WS = re.compile(r"\s+")
_ZW = dict.fromkeys(map(ord, "\u200b\u200c\u200d\ufeff"), None)
_QT = {ord(c): "'" for c in "\u2018\u2019\u201a\u2032"}
_QT.update({ord(c): '"' for c in "\u201c\u201d\u201e\u2033"})


def norm(s: str) -> str:
    """Normalise for quote matching: NFKC, curly quotes, zero-width, whitespace."""
    s = unicodedata.normalize("NFKC", s).translate(_ZW).translate(_QT)
    return _WS.sub(" ", s).strip()


def read_jsonl(path) -> list[dict]:
    """Tolerant JSONL reader: skips blanks and code-fence lines; parse errors become rows."""
    rows: list[dict] = []
    text = Path(path).read_text(encoding="utf-8-sig")
    for i, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("```"):
            continue
        try:
            obj = json.loads(s)
        except Exception as e:  # noqa: BLE001
            rows.append({"_parse_error": str(e)[:120], "_line": i, "_raw": s[:160]})
            continue
        if not isinstance(obj, dict):
            rows.append({"_parse_error": "row is not an object", "_line": i, "_raw": s[:160]})
            continue
        obj["_line"] = i
        rows.append(obj)
    return rows


def write_jsonl(path, rows) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def jdump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=False)


def slug(s: str) -> str:
    s = re.sub(r"[^0-9A-Za-z\uac00-\ud7a3]+", "-", s.strip().lower()).strip("-")
    return s[:48] or "wf"


SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS questions(
  id TEXT PRIMARY KEY, parent TEXT, text TEXT, kind TEXT, priority INTEGER DEFAULT 1,
  labels TEXT, label_defs TEXT);
CREATE TABLE IF NOT EXISTS candidates(
  id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT, title TEXT, why TEXT, lane TEXT,
  tier_guess INTEGER, origin_guess TEXT, task_id TEXT, wave INTEGER, status TEXT DEFAULT 'new',
  assigned_to TEXT);
CREATE TABLE IF NOT EXISTS sources(
  id TEXT PRIMARY KEY, kind TEXT, url TEXT, title TEXT, tier INTEGER, stance TEXT,
  origin_group TEXT, lane TEXT, as_of TEXT, captured_at TEXT, path TEXT, sha256 TEXT,
  n_chars INTEGER, pii_status TEXT DEFAULT 'clear', access TEXT, task_id TEXT, seq INTEGER,
  status TEXT DEFAULT 'active');
CREATE TABLE IF NOT EXISTS chunks(
  id TEXT PRIMARY KEY, source_id TEXT, ord INTEGER, text TEXT);
CREATE TABLE IF NOT EXISTS tasks(
  id TEXT PRIMARY KEY, block TEXT, wave INTEGER, role TEXT, coder TEXT, status TEXT,
  fanout_key TEXT, input_sha TEXT, receipt TEXT, option TEXT, attempts INTEGER DEFAULT 0,
  created TEXT, dispatched TEXT, begun TEXT, returned TEXT, verified TEXT,
  rows_ok INTEGER DEFAULT 0, rows_rejected INTEGER DEFAULT 0, rows_dup INTEGER DEFAULT 0,
  manual INTEGER DEFAULT 0, notes TEXT);
CREATE TABLE IF NOT EXISTS block_state(
  block TEXT PRIMARY KEY, status TEXT DEFAULT 'pending', waves INTEGER DEFAULT 0, note TEXT);
CREATE TABLE IF NOT EXISTS evidence(
  id TEXT PRIMARY KEY, task_id TEXT, source_id TEXT, question_id TEXT, locator TEXT,
  quote TEXT, label TEXT, polarity TEXT, entity TEXT, attribute TEXT, value TEXT,
  value_num REAL, unit TEXT, as_of TEXT, confidence REAL, coder TEXT, method TEXT,
  sql TEXT, result_sha TEXT, is_null INTEGER DEFAULT 0, note TEXT);
CREATE TABLE IF NOT EXISTS claims(
  id TEXT PRIMARY KEY, task_id TEXT, question_id TEXT, text TEXT, ctype TEXT,
  strength TEXT, scope TEXT, time_sensitive INTEGER DEFAULT 0, falsifier TEXT,
  status TEXT DEFAULT 'unsupported', n_groups INTEGER DEFAULT 0, best_tier INTEGER,
  n_refute_groups INTEGER DEFAULT 0, block TEXT);
CREATE TABLE IF NOT EXISTS claim_evidence(
  claim_id TEXT, evidence_id TEXT, relation TEXT, PRIMARY KEY(claim_id, evidence_id, relation));
CREATE TABLE IF NOT EXISTS challenges(
  id TEXT PRIMARY KEY, task_id TEXT, claim_id TEXT, expected_falsifier TEXT,
  search_log TEXT, found INTEGER, verdict TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS contradictions(
  id TEXT PRIMARY KEY, claim_id TEXT, evidence_id TEXT, status TEXT DEFAULT 'open', note TEXT);
CREATE TABLE IF NOT EXISTS findings(
  id TEXT PRIMARY KEY, task_id TEXT, block TEXT, kind TEXT, severity TEXT, ref TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS datasets(
  name TEXT PRIMARY KEY, source_id TEXT, parquet TEXT, n_rows INTEGER, n_cols INTEGER, profile TEXT);
CREATE TABLE IF NOT EXISTS rejects(
  id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, kind TEXT, line INTEGER,
  reason TEXT, row_json TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS waivers(gate TEXT, block TEXT, reason TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, kind TEXT, task_id TEXT, detail TEXT);
CREATE INDEX IF NOT EXISTS ix_ev_q ON evidence(question_id);
CREATE INDEX IF NOT EXISTS ix_ev_s ON evidence(source_id);
CREATE INDEX IF NOT EXISTS ix_tasks_b ON tasks(block);
"""


def resolve_run(arg=None) -> Path:
    cands = []
    if arg:
        cands += [Path(arg), lab_home() / "runs" / str(arg)]
    if os.environ.get("RLAB_RUN"):
        cands.append(Path(os.environ["RLAB_RUN"]))
    cands.append(Path.cwd())
    for c in cands:
        if (c / "ledger.sqlite").exists():
            return c.resolve()
    die(f"run not found (tried: {', '.join(str(c) for c in cands)}). Use --run <path|run_id>.")


class Run:
    """Handle to one research run directory + its ledger."""

    def __init__(self, root):
        self.root = Path(root).resolve()
        if not (self.root / "ledger.sqlite").exists():
            die(f"not a run directory: {self.root}")
        self.db = sqlite3.connect(str(self.root / "ledger.sqlite"), timeout=30, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self._spec = None

    # ---- paths
    def p(self, *parts) -> Path:
        return self.root.joinpath(*parts)

    # ---- meta
    def meta(self, k, default=None):
        r = self.db.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return r[0] if r else default

    def set_meta(self, k, v):
        self.db.execute("INSERT INTO meta(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))

    def nid(self, prefix: str, width: int = 4) -> str:
        k = f"ctr:{prefix}"
        n = int(self.meta(k, 0)) + 1
        self.set_meta(k, n)
        return f"{prefix}{n:0{width}d}"

    def bump(self):
        self.set_meta("rev", int(self.meta("rev", 0)) + 1)

    def event(self, kind: str, task_id=None, **detail):
        self.db.execute("INSERT INTO events(ts,kind,task_id,detail) VALUES(?,?,?,?)",
                        (now(), kind, task_id, json.dumps(detail, ensure_ascii=False) if detail else None))
        self.bump()  # every audited mutation invalidates the lake cache

    # ---- workflow spec
    @property
    def spec(self) -> dict:
        if self._spec is None:
            self._spec = json.loads((self.root / "workflow.json").read_text(encoding="utf-8"))
        return self._spec

    def block(self, bid: str) -> dict:
        for b in self.spec["blocks"]:
            if b["id"] == bid:
                return b
        die(f"block not in workflow: {bid}")

    def params(self, bid: str | None = None) -> dict:
        p = dict(self.spec.get("params", {}))
        if bid:
            p.update(self.block(bid).get("params", {}))
        return p

    # ---- convenience
    def q(self, sql, args=()):
        return self.db.execute(sql, args).fetchall()

    def one(self, sql, args=()):
        return self.db.execute(sql, args).fetchone()

    def questions(self, top_only=False):
        sql = "SELECT * FROM questions" + (" WHERE parent IS NULL OR parent=''" if top_only else "") + " ORDER BY id"
        return self.q(sql)

    def close(self):
        self.db.close()


def new_run_db(root: Path, run_id: str) -> Run:
    root.mkdir(parents=True, exist_ok=True)
    for d in ("raw", "staging/incoming", "staging/out", "tasks", "lake", "reports"):
        (root / d).mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(root / "ledger.sqlite"), isolation_level=None)
    db.executescript(SCHEMA)
    db.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('run_id',?)", (run_id,))
    db.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('key',?)", (secrets.token_hex(16),))
    db.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('created',?)", (now(),))
    db.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('rev','0')")
    db.close()
    return Run(root)


def table(rows, headers=None, maxw=60) -> str:
    """Plain-text table from list of dict/Row/tuple."""
    rows = [list(r) if not isinstance(r, dict) else list(r.values()) for r in rows]
    if headers is None:
        headers = [f"c{i}" for i in range(len(rows[0]))] if rows else []
    data = [["" if v is None else (f"{v:.4g}" if isinstance(v, float) else str(v)) for v in r] for r in rows]
    data = [[c if len(c) <= maxw else c[: maxw - 1] + "\u2026" for c in r] for r in data]
    widths = [max([len(str(h))] + [len(r[i]) for r in data]) for i, h in enumerate(headers)]
    line = lambda cells: "  ".join(str(c).ljust(widths[i]) for i, c in enumerate(cells)).rstrip()  # noqa: E731
    out = [line(headers), line(["-" * w for w in widths])] + [line(r) for r in data]
    return "\n".join(out)
