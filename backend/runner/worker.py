"""Sandbox worker: runs ONE job against the learner's Django app in a fresh process.

Invoked by runner.sandbox as::

    python worker.py <project_dir> <job.json> <result.json>

The process configures a minimal Django project around the learner's ``store`` app,
performs the job (migrate / request / check) and writes a JSON result. Each job is
a new interpreter, so edited code is always re-imported from scratch.

This gives process isolation and a timeout only. It is NOT a security boundary:
a hosted deployment must run it inside a container or microVM without network
access or host credentials.
"""
import importlib
import io
import json
import os
import re
import sys
import time
import traceback
from contextlib import redirect_stderr, redirect_stdout

sys.dont_write_bytecode = True

PROJECT = ""


def configure(project_dir, db_path):
    from django.conf import settings

    settings.configure(
        DEBUG=True,
        SECRET_KEY="sandbox-only",
        ALLOWED_HOSTS=["*"],
        INSTALLED_APPS=[
            "django.contrib.contenttypes",
            "django.contrib.auth",
            "rest_framework",
            "store",
        ],
        MIDDLEWARE=["django.middleware.common.CommonMiddleware"],
        ROOT_URLCONF="sandbox_urls",
        DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": db_path}},
        DEFAULT_AUTO_FIELD="django.db.models.AutoField",
        USE_TZ=True,
        TIME_ZONE="UTC",
        REST_FRAMEWORK={
            "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
            "DEFAULT_AUTHENTICATION_CLASSES": [],
            "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
        },
    )
    import django

    django.setup()


# ----------------------------------------------------------------------- helpers


def jsonable(value):
    return json.loads(json.dumps(value, default=str))


def describe(exc):
    """Exception → {type, message, location} pointing at the learner's own file and line."""
    store_dir = os.path.abspath(os.path.join(PROJECT, "store"))
    location = None
    for frame in traceback.extract_tb(exc.__traceback__):
        path = os.path.abspath(frame.filename)
        if path.startswith(store_dir):
            location = {"file": os.path.relpath(path, store_dir).replace("\\", "/"), "line": frame.lineno,
                        "code": frame.line}
    if isinstance(exc, SyntaxError) and exc.filename and os.path.abspath(exc.filename).startswith(store_dir):
        location = {"file": os.path.relpath(os.path.abspath(exc.filename), store_dir).replace("\\", "/"),
                    "line": exc.lineno, "code": (exc.text or "").strip()}
    text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    return {"type": type(exc).__name__, "message": str(exc), "location": location, "traceback": text[-6000:]}


def render_sql(sql, params):
    if not params:
        return sql

    def quote(p):
        if p is None:
            return "NULL"
        if isinstance(p, (int, float)):
            return str(p)
        return "'" + str(p).replace("'", "''") + "'"

    try:
        return sql % tuple(quote(p) for p in params)
    except Exception:
        return f"{sql}  -- params: {params!r}"


def migration_files():
    folder = os.path.join(PROJECT, "store", "migrations")
    if not os.path.isdir(folder):
        return []
    return sorted(f for f in os.listdir(folder) if re.match(r"^\d{4}_.*\.py$", f))


def response_body(response):
    content_type = response.get("Content-Type", "")
    raw = response.content.decode("utf-8", errors="replace")
    if "json" in content_type:
        try:
            return json.loads(raw) if raw else None, "json"
        except ValueError:
            pass
    if "html" in content_type:
        title = re.search(r"<title>(.*?)</title>", raw, re.S)
        return (title.group(1).strip() if title else raw[:400]), "html"
    return raw[:4000], "text"


# ---------------------------------------------------------------- request probes


class Probe:
    """Records an ordered timeline of serializer events and SQL during a request."""

    def __init__(self):
        self.events = []
        self.depth = 0

    def install(self):
        from rest_framework import serializers as s

        probe = self
        orig_is_valid = s.BaseSerializer.is_valid
        orig_save = s.BaseSerializer.save

        def is_valid(ser, *args, **kwargs):
            event = {"stage": "serializer", "action": "validate", "serializer": type(ser).__name__,
                     "input": jsonable(getattr(ser, "initial_data", None))}
            probe.events.append(event)
            try:
                ok = orig_is_valid(ser, *args, **kwargs)
            except Exception:
                event.update(valid=False, errors=jsonable(getattr(ser, "_errors", None)))
                raise
            event.update(valid=ok, errors=None if ok else jsonable(ser.errors),
                         validated_data=jsonable(dict(ser.validated_data)) if ok else None)
            return ok

        def save(ser, **kwargs):
            event = {"stage": "serializer", "action": "save", "serializer": type(ser).__name__,
                     "operation": "update" if ser.instance is not None else "create"}
            probe.events.append(event)
            instance = orig_save(ser, **kwargs)
            event.update(instance=str(instance), model=type(instance).__name__, pk=getattr(instance, "pk", None))
            return instance

        s.BaseSerializer.is_valid = is_valid
        s.BaseSerializer.save = save
        for cls in (s.Serializer, s.ListSerializer):
            self._wrap_data(cls, s.ListSerializer)

    def _wrap_data(self, cls, list_cls):
        probe = self
        original = cls.data

        def data(ser):
            probe.depth += 1
            event = None
            if probe.depth == 1:
                many = isinstance(ser, list_cls)
                name = f"{type(ser.child).__name__}(many=True)" if many else type(ser).__name__
                event = {"stage": "serializer", "action": "serialize", "serializer": name, "many": many}
                probe.events.append(event)
            try:
                result = original.fget(ser)
            finally:
                probe.depth -= 1
            if event is not None:
                out = jsonable(result)
                event["items"] = len(out) if isinstance(out, list) else None
                event["output"] = out[:3] if isinstance(out, list) else out
            return result

        cls.data = property(data)

    def sql_wrapper(self):
        probe = self

        def wrapper(execute, sql, params, many, context):
            start = time.perf_counter()
            event = {"stage": "sql", "sql": render_sql(sql, params), "verb": sql.split(None, 1)[0].upper()}
            probe.events.append(event)
            try:
                return execute(sql, params, many, context)
            except Exception as exc:
                event["error"] = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                event["ms"] = round((time.perf_counter() - start) * 1000, 2)

        return wrapper


def view_info(match):
    import inspect

    func = match.func
    cls = getattr(func, "cls", None) or getattr(func, "view_class", None)
    info = {"stage": "view", "name": getattr(cls, "__name__", None) or func.__name__,
            "kind": "function" if cls is None else "class", "actions": getattr(func, "actions", None)}
    if cls is not None:
        ser = getattr(cls, "serializer_class", None)
        info["serializer"] = getattr(ser, "__name__", None)
        qs = getattr(cls, "queryset", None)
        info["model"] = getattr(getattr(qs, "model", None), "__name__", None)
        info["bases"] = [b.__name__ for b in cls.__mro__[1:4]]
        if getattr(cls, "__module__", "") == "rest_framework.decorators":
            info["kind"] = "api_function"
    target = cls if cls is not None and info["kind"] != "api_function" else getattr(func, "__wrapped__", func)
    try:
        lines, start = inspect.getsourcelines(target)
        source = inspect.getsourcefile(target) or ""
        if os.path.abspath(source).startswith(os.path.abspath(os.path.join(PROJECT, "store"))):
            info["location"] = {"file": os.path.basename(source), "line": start, "end_line": start + len(lines) - 1}
    except (TypeError, OSError):
        pass
    return info


# ------------------------------------------------------------------------ actions


def action_migrate(job):
    from django.core.management import call_command

    log = io.StringIO()
    before = set(migration_files())
    try:
        call_command("makemigrations", "store", interactive=False, stdout=log, stderr=log, no_color=True)
    except SystemExit:
        output = log.getvalue().strip()
        return {"ok": False, "stage": "makemigrations", "output": output,
                "error": {"type": "MakemigrationsAborted", "message": output or "makemigrations stopped.",
                          "location": None}}
    except Exception as exc:
        return {"ok": False, "stage": "makemigrations", "output": log.getvalue(), "error": describe(exc)}
    importlib.invalidate_caches()
    created = sorted(set(migration_files()) - before)
    sql = {}
    for name in created:
        try:
            sql[name] = call_command("sqlmigrate", "store", name[:4], stdout=io.StringIO(), no_color=True)
        except Exception as exc:
            sql[name] = f"-- could not render SQL: {exc}"
    try:
        call_command("migrate", interactive=False, stdout=log, stderr=log, no_color=True)
    except Exception as exc:
        return {"ok": False, "stage": "migrate", "output": log.getvalue(), "created": created, "sql": sql,
                "error": describe(exc)}
    return {"ok": True, "stage": "migrate", "created": created, "sql": sql, "output": log.getvalue()}


def action_request(job):
    from django.db import connection
    from django.test import Client
    from django.urls import Resolver404, resolve

    method, path, body = job["method"].upper(), job["path"], job.get("body")
    trace = [{"stage": "request", "method": method, "path": path, "body": body}]
    try:
        match = resolve(path.split("?")[0])
    except Resolver404:
        from store import urls as store_urls

        trace.append({"stage": "url", "matched": False,
                      "tried": [str(getattr(p, "pattern", p)) for p in getattr(store_urls, "urlpatterns", [])]})
    except Exception as exc:
        return {"ok": False, "trace": trace, "error": describe(exc), "failed_stage": "url"}
    else:
        trace.append({"stage": "url", "matched": True, "route": str(match.route), "url_name": match.url_name,
                      "kwargs": jsonable(match.kwargs)})
        trace.append(view_info(match))

    probe = Probe()
    probe.install()
    client = Client(raise_request_exception=True)
    payload = json.dumps(body) if body is not None and method not in ("GET", "HEAD") else ""
    error, response = None, None
    start = time.perf_counter()
    with connection.execute_wrapper(probe.sql_wrapper()):
        try:
            response = client.generic(method, path, data=payload, content_type="application/json")
        except Exception as exc:
            error = describe(exc)
    duration = round((time.perf_counter() - start) * 1000, 1)
    trace.extend(probe.events)
    if response is not None:
        data, kind = response_body(response)
        trace.append({"stage": "response", "status": response.status_code, "reason": response.reason_phrase,
                      "body": data, "body_kind": kind, "location": response.get("Location")})
    else:
        trace.append({"stage": "response", "status": 500, "reason": "Internal Server Error", "body": None,
                      "body_kind": "error"})
    queries = [e for e in probe.events if e["stage"] == "sql"]
    return {"ok": error is None, "trace": trace, "error": error, "duration_ms": duration,
            "query_count": len(queries)}


class CheckFailed(Exception):
    pass


def expect(condition, message):
    if not condition:
        raise CheckFailed(message)


def resolve_refs(value, refs, as_pk):
    if isinstance(value, dict):
        return {k: resolve_refs(v, refs, as_pk) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_refs(v, refs, as_pk) for v in value]
    if isinstance(value, str) and value.startswith("@") and value[1:] in refs:
        obj = refs[value[1:]]
        return obj.pk if as_pk else obj
    return value


def run_request_check(check):
    from django.apps import apps
    from django.db import connection, transaction
    from django.test import Client

    with transaction.atomic():
        refs = {}
        for item in check.get("setup", []):
            model = apps.get_model("store", item["model"])
            refs[item["ref"]] = model.objects.create(**resolve_refs(item["data"], refs, as_pk=False))
        path = re.sub(r"@(\w+)", lambda m: str(refs[m.group(1)].pk) if m.group(1) in refs else m.group(0),
                      check["path"])
        body = resolve_refs(check.get("body"), refs, as_pk=True)
        method = check["method"].upper()
        queries = []
        with connection.execute_wrapper(lambda ex, sql, params, many, ctx: queries.append(sql) or
                                        ex(sql, params, many, ctx)):
            response = Client(raise_request_exception=True).generic(
                method, path, data=json.dumps(body) if body is not None and method != "GET" else "",
                content_type="application/json")
        data, kind = response_body(response)
        exp = check["expect"]
        shown = json.dumps(data)[:300] if kind == "json" else str(data)[:200]
        if "status" in exp:
            expect(response.status_code == exp["status"],
                   f"Expected HTTP {exp['status']}, got {response.status_code}. Response: {shown}")
        if exp.get("is_list"):
            expect(isinstance(data, list), f"Expected a JSON list, got: {shown}")
        if "length" in exp:
            expect(isinstance(data, list) and len(data) == exp["length"],
                   f"Expected {exp['length']} items, got {len(data) if isinstance(data, list) else shown}.")
        target = data[0] if isinstance(data, list) and data else data
        if exp.get("keys"):
            missing = [k for k in exp["keys"] if not isinstance(target, dict) or k not in target]
            expect(not missing, f"Missing keys {missing} in {shown}")
        for key, want in (exp.get("json_subset") or {}).items():
            got = target.get(key) if isinstance(target, dict) else None
            expect(got == want, f"Expected {key}={want!r}, got {got!r}.")
        if exp.get("error_keys"):
            missing = [k for k in exp["error_keys"] if not isinstance(data, dict) or k not in data]
            expect(not missing, f"Expected validation errors for {missing}. Response: {shown}")
        if "max_queries" in exp:
            expect(len(queries) <= exp["max_queries"],
                   f"Ran {len(queries)} SQL queries; the goal is at most {exp['max_queries']}. "
                   "Look for N+1 patterns (select_related / prefetch_related).")
        if exp.get("db_count"):
            model = apps.get_model("store", exp["db_count"]["model"])
            count = model.objects.count()
            expect(count == exp["db_count"]["count"],
                   f"Expected {exp['db_count']['count']} {model.__name__} row(s) in the database, found {count}.")
        transaction.set_rollback(True)
    return f"HTTP {response.status_code} · {len(queries)} quer{'y' if len(queries) == 1 else 'ies'}"


def run_model_check(check):
    from django.apps import apps
    from django.core.exceptions import FieldDoesNotExist

    try:
        model = apps.get_model("store", check["model"])
    except LookupError:
        raise CheckFailed(f"Model {check['model']} not found in models.py.")
    for name, spec in check.get("fields", {}).items():
        try:
            field = model._meta.get_field(name)
        except FieldDoesNotExist:
            raise CheckFailed(f"{model.__name__}.{name} is missing.")
        for key, want in spec.items():
            if key == "type":
                got = type(field).__name__
            elif key == "to":
                got = getattr(field.related_model, "__name__", None)
            elif key == "on_delete":
                got = getattr(getattr(field.remote_field, "on_delete", None), "__name__", None)
            elif key == "related_name":
                got = getattr(field.remote_field, "related_name", None)
            else:
                got = getattr(field, key, None)
            expect(got == want, f"{model.__name__}.{name}: expected {key}={want!r}, found {got!r}.")
    return "Model verified by Django's app registry."


def run_unique_check(check):
    from django.apps import apps
    from django.db.models import UniqueConstraint

    model = apps.get_model("store", check["model"])
    groups = [set(c.fields) for c in model._meta.constraints if isinstance(c, UniqueConstraint)]
    groups += [set(u) for u in model._meta.unique_together]
    expect(set(check["fields"]) in groups, f"No unique constraint on ({', '.join(check['fields'])}).")
    return "Constraint registered."


def run_serializer_check(check):
    module = importlib.import_module("store.serializers")
    cls = getattr(module, check["serializer"], None)
    expect(cls is not None, f"{check['serializer']} not found in serializers.py.")
    if check.get("model"):
        model = getattr(getattr(cls, "Meta", None), "model", None)
        expect(getattr(model, "__name__", None) == check["model"],
               f"{cls.__name__}.Meta.model should be {check['model']}.")
    fields = set(cls().fields)
    missing = [f for f in check.get("fields", []) if f not in fields]
    expect(not missing, f"{cls.__name__} is missing fields: {', '.join(missing)}.")
    return f"Fields: {', '.join(sorted(fields))}."


def action_check(job):
    from django.core.management import call_command

    log = io.StringIO()
    migrations_current, migrate_error = True, None
    try:
        call_command("makemigrations", "store", check_changes=True, dry_run=True, interactive=False,
                     stdout=log, stderr=log, no_color=True)
    except SystemExit:
        migrations_current = False
    except Exception as exc:
        return {"ok": False, "stage": "setup", "error": describe(exc), "results": []}
    if not migrations_current:
        # Build the throwaway copy's schema from the current code, so behavior checks
        # still run even when the learner hasn't migrated yet.
        try:
            call_command("makemigrations", "store", interactive=False, stdout=log, stderr=log, no_color=True)
        except SystemExit:
            migrate_error = log.getvalue().strip()
        importlib.invalidate_caches()
    if migrate_error is None:
        try:
            call_command("migrate", interactive=False, stdout=log, stderr=log, no_color=True)
        except Exception as exc:
            migrate_error = f"{type(exc).__name__}: {exc}"

    results = []
    for i, check in enumerate(job["checks"]):
        result = {"index": i, "label": check["label"], "passed": False, "message": "", "error": None}
        try:
            if check["type"] == "migrations_current":
                expect(migrations_current, "Your models have changes that aren't in a migration yet. "
                                           "Click Make migrations.")
                result["message"] = "No pending model changes."
            elif migrate_error and check["type"] == "request":
                raise CheckFailed(f"Couldn't build the database: {migrate_error[:300]}")
            elif check["type"] == "request":
                result["message"] = run_request_check(check)
            elif check["type"] == "model":
                result["message"] = run_model_check(check)
            elif check["type"] == "unique_together":
                result["message"] = run_unique_check(check)
            elif check["type"] == "serializer":
                result["message"] = run_serializer_check(check)
            result["passed"] = True
        except CheckFailed as exc:
            result["message"] = str(exc)
        except Exception as exc:
            result["error"] = describe(exc)
            result["message"] = f"{type(exc).__name__}: {exc}"
        results.append(result)
    return {"ok": True, "stage": "check", "results": results, "migrations_current": migrations_current}


def action_seed(job):
    """Insert sample rows, adapting to whatever models and fields exist right now."""
    from django.apps import apps
    from django.db import DatabaseError, transaction

    refs, created, skipped = {}, [], []
    try:
        with transaction.atomic():
            for item in job["items"]:
                try:
                    model = apps.get_model("store", item["model"])
                except LookupError:
                    skipped.append(f"{item['model']} (no such model yet)")
                    continue
                names = {f.name for f in model._meta.get_fields() if f.concrete and not f.many_to_many}
                m2m = {f.name for f in model._meta.many_to_many}
                data = resolve_refs({k: v for k, v in item["data"].items() if k in names}, refs, as_pk=False)
                if any(isinstance(v, str) and v.startswith("@") for v in data.values()):
                    skipped.append(f"{item['model']} {item['data'].get('name', '')} (missing related row)")
                    continue
                key = next((k for k in ("slug", "name") if k in data), None)
                lookup = {key: data.pop(key)} if key else {}
                obj, was_created = (model.objects.get_or_create(**lookup, defaults=data) if lookup
                                    else (model.objects.create(**data), True))
                for key in m2m & set(item.get("m2m", {})):
                    getattr(obj, key).set([refs[r[1:]] for r in item["m2m"][key] if r[1:] in refs])
                refs[item["ref"]] = obj
                if was_created:
                    created.append(f"{model.__name__}: {obj}")
    except DatabaseError as exc:
        return {"ok": False, "stage": "seed", "created": [], "skipped": skipped,
                "error": {"type": type(exc).__name__, "location": None,
                          "message": f"{exc}. Did you run Make migrations?"}}
    return {"ok": True, "stage": "seed", "created": created, "skipped": skipped}


ACTIONS = {"migrate": action_migrate, "request": action_request, "check": action_check, "seed": action_seed}


def main():
    global PROJECT
    PROJECT, job_path, result_path = sys.argv[1:4]
    with open(job_path, encoding="utf-8") as fh:
        job = json.load(fh)
    sys.path.insert(0, PROJECT)
    logs = io.StringIO()
    try:
        with redirect_stdout(logs), redirect_stderr(logs):
            try:
                configure(PROJECT, job["db_path"])
            except Exception as exc:
                result = {"ok": False, "stage": "setup", "error": describe(exc), "results": []}
            else:
                result = ACTIONS[job["action"]](job)
    except BaseException as exc:  # SystemExit / KeyboardInterrupt raised by learner code
        result = {"ok": False, "stage": "crash", "error": describe(exc), "results": []}
    result["logs"] = logs.getvalue()[-20000:]
    with open(result_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, default=str)


if __name__ == "__main__":
    main()
