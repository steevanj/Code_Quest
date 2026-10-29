"""Per-session sandbox projects: write the learner's code, run worker jobs, read the DB.

Layout of one session (``SANDBOX_ROOT/<session>/``)::

    sandbox_urls.py        root URLconf -> include("store.urls")
    store/                 the learner's app (models, serializers, views, urls, migrations/)
    db.sqlite3             the learner's database, persisted between requests
"""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
from contextlib import closing
from pathlib import Path

from django.conf import settings
from rest_framework.exceptions import ParseError

from analyzer.engine import FILES

SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
WORKER = Path(__file__).with_name("worker.py")
ROW_LIMIT = 50

APPS_PY = '''from django.apps import AppConfig


class StoreConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "store"
'''
ROOT_URLS = '''from django.urls import include, path

urlpatterns = [path("", include("store.urls"))]
'''

_locks = {}
_locks_guard = threading.Lock()


class SandboxError(ParseError):
    """Bad session / payload — rendered by DRF as a 400 response."""


def session_dir(session):
    if not isinstance(session, str) or not SESSION_RE.match(session):
        raise SandboxError("Invalid or missing session id.")
    return Path(settings.SANDBOX_ROOT) / session


def session_lock(session):
    with _locks_guard:
        return _locks.setdefault(session, threading.Lock())


def write_project(root, files):
    store = root / "store"
    (store / "migrations").mkdir(parents=True, exist_ok=True)
    (store / "__init__.py").write_text("", encoding="utf-8")
    (store / "apps.py").write_text(APPS_PY, encoding="utf-8")
    init = store / "migrations" / "__init__.py"
    if not init.exists():
        init.write_text("", encoding="utf-8")
    (root / "sandbox_urls.py").write_text(ROOT_URLS, encoding="utf-8")
    for name in FILES:
        (store / name).write_text(files.get(name, ""), encoding="utf-8")


def run_worker(root, job, db_path):
    with tempfile.TemporaryDirectory(prefix="forge-job-") as tmp:
        job_path, result_path = Path(tmp) / "job.json", Path(tmp) / "result.json"
        job_path.write_text(json.dumps({**job, "db_path": str(db_path)}), encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if k not in ("DJANGO_SETTINGS_MODULE", "PYTHONPATH")}
        env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
        try:
            proc = subprocess.run(
                [sys.executable, str(WORKER), str(root), str(job_path), str(result_path)],
                cwd=str(root), env=env, capture_output=True, text=True, timeout=settings.RUNNER_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "stage": "timeout", "results": [],
                    "error": {"type": "Timeout", "location": None,
                              "message": f"Your code ran longer than {settings.RUNNER_TIMEOUT}s and was stopped. "
                                         "Look for an infinite loop."}}
        if not result_path.exists():
            return {"ok": False, "stage": "crash", "results": [],
                    "error": {"type": "WorkerCrash", "location": None,
                              "message": (proc.stderr or proc.stdout or "The sandbox exited unexpectedly.")[-3000:]}}
        return json.loads(result_path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------- inspection


def migration_files(root):
    folder = root / "store" / "migrations"
    if not folder.is_dir():
        return []
    return [{"name": p.name, "content": p.read_text(encoding="utf-8")}
            for p in sorted(folder.glob("[0-9][0-9][0-9][0-9]_*.py"))]


def snapshot(root):
    """The applied schema and data, read straight from SQLite (no Django involved)."""
    db_path = root / "db.sqlite3"
    if not db_path.exists():
        return {"exists": False, "tables": [], "applied_migrations": []}
    with closing(sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)) as con:
        con.row_factory = sqlite3.Row
        names = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'store\\_%' ESCAPE '\\' ORDER BY name")]
        tables = []
        for name in names:
            q = name.replace('"', '""')
            fks = {r["from"]: {"table": r["table"], "column": r["to"]}
                   for r in con.execute(f'PRAGMA foreign_key_list("{q}")')}
            unique_cols, indexed_cols, unique_groups = set(), set(), []
            for idx in con.execute(f'PRAGMA index_list("{q}")'):
                cols = [r["name"] for r in con.execute(f'PRAGMA index_info("{idx["name"]}")')]
                if idx["unique"] and len(cols) == 1:
                    unique_cols.add(cols[0])
                elif idx["unique"]:
                    unique_groups.append(cols)
                elif len(cols) == 1:
                    indexed_cols.add(cols[0])
            columns = [{
                "name": r["name"], "type": r["type"].lower(), "pk": bool(r["pk"]), "null": not r["notnull"],
                "unique": r["name"] in unique_cols or bool(r["pk"]), "index": r["name"] in indexed_cols,
                "default": r["dflt_value"], "fk": fks.get(r["name"]),
            } for r in con.execute(f'PRAGMA table_info("{q}")')]
            count = con.execute(f'SELECT COUNT(*) FROM "{q}"').fetchone()[0]
            rows = [dict(r) for r in con.execute(f'SELECT * FROM "{q}" ORDER BY 1 LIMIT {ROW_LIMIT}')]
            tables.append({"name": name, "columns": columns, "rows": rows, "count": count,
                           "unique_together": unique_groups})
        applied = []
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='django_migrations'").fetchone():
            applied = [r[0] for r in con.execute(
                "SELECT name FROM django_migrations WHERE app='store' ORDER BY id")]
    return {"exists": True, "tables": tables, "applied_migrations": applied}


def state(session):
    root = session_dir(session)
    return {"schema": snapshot(root), "migrations": migration_files(root)}


# ------------------------------------------------------------------------- actions


def migrate(session, files):
    root = session_dir(session)
    with session_lock(session):
        write_project(root, files)
        result = run_worker(root, {"action": "migrate"}, root / "db.sqlite3")
        result.update(state(session))
    return result


def request(session, files, method, path, body):
    root = session_dir(session)
    with session_lock(session):
        write_project(root, files)
        result = run_worker(root, {"action": "request", "method": method, "path": path, "body": body},
                            root / "db.sqlite3")
        result.update(state(session))
    return result


def seed(session, files, items):
    root = session_dir(session)
    with session_lock(session):
        write_project(root, files)
        result = run_worker(root, {"action": "seed", "items": items}, root / "db.sqlite3")
        result.update(state(session))
    return result


def run_checks(session, files, checks):
    """Verify checks in a disposable copy (code + the learner's migrations), leaving their DB untouched."""
    root = session_dir(session)
    with session_lock(session), tempfile.TemporaryDirectory(prefix="forge-check-") as tmp:
        copy = Path(tmp)
        write_project(copy, files)
        for mig in migration_files(root):
            (copy / "store" / "migrations" / mig["name"]).write_text(mig["content"], encoding="utf-8")
        return run_worker(copy, {"action": "check", "checks": checks}, copy / "db.sqlite3")


def reset(session):
    root = session_dir(session)
    with session_lock(session):
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)
    return state(session)
