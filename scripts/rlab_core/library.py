"""Workflow library: saved workflow specs, run outcomes, lessons, fitness."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .core import die, jdump, lab_home, now, slug

REG_SCHEMA = """
CREATE TABLE IF NOT EXISTS workflows(
  id TEXT PRIMARY KEY, name TEXT, version INTEGER, parent TEXT, domain TEXT, direction TEXT,
  traits TEXT, spec_path TEXT, created TEXT, status TEXT DEFAULT 'active');
CREATE TABLE IF NOT EXISTS runs(
  run_id TEXT PRIMARY KEY, workflow_id TEXT, root TEXT, started TEXT, finished TEXT,
  metrics TEXT, score REAL, proxy REAL, notes TEXT);
CREATE TABLE IF NOT EXISTS lessons(
  id INTEGER PRIMARY KEY AUTOINCREMENT, workflow_id TEXT, tags TEXT, kind TEXT, text TEXT, created TEXT);
"""


def home() -> Path:
    h = lab_home()
    (h / "workflows").mkdir(parents=True, exist_ok=True)
    (h / "runs").mkdir(parents=True, exist_ok=True)
    return h


def reg() -> sqlite3.Connection:
    c = sqlite3.connect(str(home() / "registry.sqlite"), timeout=30, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.executescript(REG_SCHEMA)
    return c


def save_workflow(spec: dict, name: str | None = None) -> dict:
    from .forge import render_md
    c = reg()
    base = slug(name or spec.get("name") or "wf")
    n = c.execute("SELECT COALESCE(MAX(version),0)+1 FROM workflows WHERE name=?", (base,)).fetchone()[0]
    wid = f"{base}-v{n}"
    spec = dict(spec)
    spec.update({"id": wid, "name": base, "version": n, "saved": now()})
    d = home() / "workflows"
    (d / f"{wid}.json").write_text(jdump(spec), encoding="utf-8")
    (d / f"{wid}.md").write_text(render_md(spec), encoding="utf-8")
    t = spec["traits"]
    c.execute("INSERT INTO workflows(id,name,version,parent,domain,direction,traits,spec_path,created) VALUES(?,?,?,?,?,?,?,?,?)",
              (wid, base, n, spec.get("parent"), t.get("domain"), t.get("direction"),
               json.dumps(t, ensure_ascii=False), str(d / f"{wid}.json"), now()))
    c.close()
    return spec


def get_workflow(ref: str) -> dict:
    """ref = exact id (name-vN) or bare name (latest version)."""
    c = reg()
    r = c.execute("SELECT spec_path FROM workflows WHERE id=?", (ref,)).fetchone()
    if not r:
        r = c.execute("SELECT spec_path FROM workflows WHERE name=? ORDER BY version DESC LIMIT 1", (slug(ref),)).fetchone()
    c.close()
    if not r:
        die(f"workflow not found in library: {ref}")
    return json.loads(Path(r[0]).read_text(encoding="utf-8"))


def fitness(c, wid: str) -> tuple[float | None, int]:
    rows = c.execute("SELECT score, proxy FROM runs WHERE workflow_id=? AND finished IS NOT NULL", (wid,)).fetchall()
    vals = []
    for r in rows:
        if r["score"] is not None:
            vals.append(float(r["score"]) / 5.0)
        elif r["proxy"] is not None:
            vals.append(float(r["proxy"]))
    return (sum(vals) / len(vals) if vals else None), len(rows)


def list_workflows() -> list[dict]:
    c = reg()
    out = []
    for r in c.execute("SELECT * FROM workflows ORDER BY created DESC").fetchall():
        f, n = fitness(c, r["id"])
        out.append({"id": r["id"], "domain": r["domain"], "direction": r["direction"], "parent": r["parent"],
                    "runs": n, "fitness": None if f is None else round(f, 3), "created": r["created"]})
    c.close()
    return out


def match(traits: dict, k: int = 3) -> list[dict]:
    from .forge import distance
    c = reg()
    scored = []
    for r in c.execute("SELECT id, traits FROM workflows WHERE status='active'").fetchall():
        d = distance(traits, json.loads(r["traits"]))
        f, n = fitness(c, r["id"])
        scored.append({"id": r["id"], "distance": round(d, 3), "fitness": None if f is None else round(f, 3), "runs": n})
    c.close()
    # lower distance first; among near ties prefer higher fitness
    scored.sort(key=lambda x: (x["distance"], -(x["fitness"] or 0.0)))
    return scored[:k]


def record_run(run_id, workflow_id, root, metrics, proxy, score=None, notes=None, started=None):
    c = reg()
    c.execute("INSERT INTO runs(run_id,workflow_id,root,started,finished,metrics,score,proxy,notes) VALUES(?,?,?,?,?,?,?,?,?) "
              "ON CONFLICT(run_id) DO UPDATE SET finished=excluded.finished, metrics=excluded.metrics, score=excluded.score, proxy=excluded.proxy, notes=excluded.notes",
              (run_id, workflow_id, str(root), started, now(), json.dumps(metrics, ensure_ascii=False), score, proxy, notes))
    c.close()


def register_run_start(run_id, workflow_id, root):
    c = reg()
    c.execute("INSERT OR IGNORE INTO runs(run_id,workflow_id,root,started) VALUES(?,?,?,?)", (run_id, workflow_id, str(root), now()))
    c.close()


def add_lesson(workflow_id, text, kind="lesson", tags=None):
    c = reg()
    c.execute("INSERT INTO lessons(workflow_id,tags,kind,text,created) VALUES(?,?,?,?,?)",
              (workflow_id, json.dumps(tags or [], ensure_ascii=False), kind, text, now()))
    c.close()


def lessons_for(traits: dict, workflow_ids: list[str], limit: int = 8) -> list[dict]:
    """Lessons attached to matched workflows, plus tag matches (domain/direction/mode)."""
    c = reg()
    keys = {str(traits.get("mode", "")).lower(), str(traits.get("domain", "")).lower(), str(traits.get("direction", "")).lower()} - {""}
    out = []
    for r in c.execute("SELECT * FROM lessons ORDER BY id DESC").fetchall():
        tags = {str(t).lower() for t in json.loads(r["tags"] or "[]")}
        if r["workflow_id"] in workflow_ids or (tags & keys):
            out.append({"workflow": r["workflow_id"], "kind": r["kind"], "text": r["text"]})
        if len(out) >= limit:
            break
    c.close()
    return out
