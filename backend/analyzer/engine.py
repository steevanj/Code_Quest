"""Static analysis of the learner's ``store`` app.

Parses models.py, serializers.py, views.py and urls.py with Python's ``ast`` module
and builds a structural picture of the project: tables, relationships, serializers,
views and routes, plus diagnostics phrased like the errors Django would raise.

Nothing is executed here, so every result is a *preview*. The sandbox runner
(runner/worker.py) is what verifies behaviour against a real Django process.
"""
import ast
import builtins
import difflib
import re

from . import explain

FILES = ("models.py", "serializers.py", "views.py", "urls.py")
APP_LABEL = "store"

# Column types as Django's SQLite backend declares them, so previews can be compared
# with the schema the sandbox actually created.
FIELD_DB_TYPES = {
    "AutoField": "integer",
    "BigAutoField": "integer",
    "SmallAutoField": "integer",
    "CharField": "varchar({max_length})",
    "SlugField": "varchar({max_length})",
    "EmailField": "varchar({max_length})",
    "URLField": "varchar({max_length})",
    "FileField": "varchar({max_length})",
    "ImageField": "varchar({max_length})",
    "TextField": "text",
    "IntegerField": "integer",
    "BigIntegerField": "bigint",
    "SmallIntegerField": "smallint",
    "PositiveIntegerField": "integer unsigned",
    "PositiveSmallIntegerField": "smallint unsigned",
    "PositiveBigIntegerField": "bigint unsigned",
    "FloatField": "real",
    "DecimalField": "decimal",
    "BooleanField": "bool",
    "DateField": "date",
    "DateTimeField": "datetime",
    "TimeField": "time",
    "DurationField": "bigint",
    "UUIDField": "char(32)",
    "JSONField": "text",
    "GenericIPAddressField": "char(39)",
    "BinaryField": "BLOB",
    "ForeignKey": "integer",
    "OneToOneField": "integer",
}
DEFAULT_MAX_LENGTH = {"SlugField": 50, "EmailField": 254, "URLField": 200, "FileField": 100, "ImageField": 100}
RELATION_FIELDS = {"ForeignKey", "OneToOneField", "ManyToManyField"}
KNOWN_FIELDS = set(FIELD_DB_TYPES) | {"ManyToManyField"}
ON_DELETE = {"CASCADE", "PROTECT", "RESTRICT", "SET_NULL", "SET_DEFAULT", "DO_NOTHING"}

SERIALIZER_BASES = {"Serializer", "ModelSerializer", "HyperlinkedModelSerializer"}
MODEL_SERIALIZER_BASES = {"ModelSerializer", "HyperlinkedModelSerializer"}

GENERIC_VIEWS = {
    "ListAPIView": ["GET"],
    "CreateAPIView": ["POST"],
    "ListCreateAPIView": ["GET", "POST"],
    "RetrieveAPIView": ["GET"],
    "UpdateAPIView": ["PUT", "PATCH"],
    "DestroyAPIView": ["DELETE"],
    "RetrieveUpdateAPIView": ["GET", "PUT", "PATCH"],
    "RetrieveDestroyAPIView": ["GET", "DELETE"],
    "RetrieveUpdateDestroyAPIView": ["GET", "PUT", "PATCH", "DELETE"],
}
VIEWSETS = {
    "ModelViewSet": (["GET", "POST"], ["GET", "PUT", "PATCH", "DELETE"]),
    "ReadOnlyModelViewSet": (["GET"], ["GET"]),
}
DETAIL_VIEWS = {name for name in GENERIC_VIEWS if name.startswith(("Retrieve", "Update", "Destroy"))}
QUERYSET_VIEWS = set(GENERIC_VIEWS) | set(VIEWSETS) | {"GenericAPIView", "GenericViewSet"}
CLASS_VIEW_BASES = QUERYSET_VIEWS | {"APIView", "View", "ViewSet"}
HTTP_METHODS = ("get", "post", "put", "patch", "delete")

IMPORT_HINTS = {
    "models": "from django.db import models",
    "serializers": "from rest_framework import serializers",
    "generics": "from rest_framework import generics",
    "viewsets": "from rest_framework import viewsets",
    "status": "from rest_framework import status",
    "Response": "from rest_framework.response import Response",
    "api_view": "from rest_framework.decorators import api_view",
    "JsonResponse": "from django.http import JsonResponse",
    "path": "from django.urls import path",
    "include": "from django.urls import include",
    "DefaultRouter": "from rest_framework.routers import DefaultRouter",
    "get_object_or_404": "from django.shortcuts import get_object_or_404",
    "views": "from . import views",
    "transaction": "from django.db import transaction",
}

CONVERTER_RE = re.compile(r"<(?:(?P<conv>\w+):)?(?P<name>\w+)>")
CONVERTER_PATTERNS = {"int": r"\d+", "slug": r"[-a-zA-Z0-9_]+", "str": r"[^/]+", "uuid": r"[0-9a-f-]+", "path": r".+"}


# ------------------------------------------------------------------------- helpers


def dotted(node):
    """'models.CharField' for attribute chains, 'CharField' for names, else None."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def last(name):
    return name.rsplit(".", 1)[-1] if name else None


def lit(node, default=None):
    if node is None:
        return default
    try:
        return ast.literal_eval(node)
    except Exception:
        return default


def src(node):
    try:
        return ast.unparse(node)
    except Exception:
        return "?"


def kwargs_of(call):
    return {k.arg: k.value for k in call.keywords if k.arg}


def single_target(stmt):
    """Name assigned by ``x = ...`` (or ``x: T = ...``), else None."""
    if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
        return stmt.targets[0].id
    if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.value is not None:
        return stmt.target.id
    return None


def returns_value(func):
    for node in ast.walk(func):
        if isinstance(node, ast.Return) and node.value is not None:
            return True
        if isinstance(node, ast.Raise):
            return True
    return False


def orm_chain(node):
    """Decode ``Model.objects.a(...).b(...)`` into {model, calls, text}, else None."""
    calls = []
    cur = node
    while True:
        if isinstance(cur, ast.Call) and isinstance(cur.func, ast.Attribute):
            calls.append({"method": cur.func.attr, "args": [lit(a, src(a)) for a in cur.args]})
            cur = cur.func.value
        elif isinstance(cur, ast.Attribute) and cur.attr == "objects" and isinstance(cur.value, ast.Name):
            return {"model": cur.value.id, "calls": list(reversed(calls)), "text": src(node)}
        elif isinstance(cur, ast.Attribute):
            calls.append({"method": cur.attr, "args": []})
            cur = cur.value
        else:
            return None


def module_bindings(tree):
    """Names bound at module level (imports, defs, assignments), plus whether a star-import exists."""
    names, star = set(), False

    def visit(stmts):
        nonlocal star
        for stmt in stmts:
            if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                for alias in stmt.names:
                    if alias.name == "*":
                        star = True
                    else:
                        names.add(alias.asname or alias.name.split(".")[0])
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(stmt.name)
            else:
                for node in ast.walk(stmt):
                    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                        names.add(node.id)
                for attr in ("body", "orelse", "finalbody"):
                    if hasattr(stmt, attr) and not isinstance(stmt, (ast.FunctionDef, ast.ClassDef)):
                        visit(getattr(stmt, attr))
                for handler in getattr(stmt, "handlers", []):
                    visit(handler.body)

    visit(tree.body)
    return names, star


class NameChecker(ast.NodeVisitor):
    """Finds names that are read but never bound — what Python reports as NameError."""

    def __init__(self, globals_):
        self.scopes = [globals_ | set(dir(builtins)) | {"__name__", "__file__"}]
        self.missing = []

    def _function_locals(self, node):
        names = set()
        args = node.args
        for a in args.posonlyargs + args.args + args.kwonlyargs + [args.vararg, args.kwarg]:
            if a is not None:
                names.add(a.arg)
        body = node.body if isinstance(node.body, list) else [node.body]
        for stmt in body:
            for sub in ast.walk(stmt):
                if isinstance(sub, ast.Name) and isinstance(sub.ctx, (ast.Store, ast.Del)):
                    names.add(sub.id)
                elif isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names.add(sub.name)
                elif isinstance(sub, ast.ExceptHandler) and sub.name:
                    names.add(sub.name)
                elif isinstance(sub, (ast.Import, ast.ImportFrom)):
                    names.update(a.asname or a.name.split(".")[0] for a in sub.names)
                elif isinstance(sub, ast.arg):
                    names.add(sub.arg)
        return names

    def _visit_function(self, node):
        for deco in node.decorator_list:
            self.visit(deco)
        for default in node.args.defaults + [d for d in node.args.kw_defaults if d is not None]:
            self.visit(default)
        self.scopes.append(self._function_locals(node))
        for stmt in node.body:
            self.visit(stmt)
        self.scopes.pop()

    visit_FunctionDef = visit_AsyncFunctionDef = _visit_function

    def visit_Lambda(self, node):
        self.scopes.append(self._function_locals(node))
        self.visit(node.body)
        self.scopes.pop()

    def visit_ClassDef(self, node):
        for n in node.bases + [k.value for k in node.keywords] + node.decorator_list:
            self.visit(n)
        names = set()
        for stmt in node.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(stmt.name)
            for sub in ast.walk(stmt) if not isinstance(stmt, (ast.FunctionDef, ast.ClassDef)) else []:
                if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                    names.add(sub.id)
        self.scopes.append(names)
        for stmt in node.body:
            self.visit(stmt)
        self.scopes.pop()

    def _visit_comprehension(self, node):
        names = set()
        for gen in node.generators:
            for sub in ast.walk(gen.target):
                if isinstance(sub, ast.Name):
                    names.add(sub.id)
        self.scopes.append(names)
        self.generic_visit(node)
        self.scopes.pop()

    visit_ListComp = visit_SetComp = visit_DictComp = visit_GeneratorExp = _visit_comprehension

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load) and not any(node.id in s for s in self.scopes):
            self.missing.append(node)


def route_regex(pattern):
    out, pos = "", 0
    for m in CONVERTER_RE.finditer(pattern):
        out += re.escape(pattern[pos:m.start()]) + f"(?:{CONVERTER_PATTERNS.get(m.group('conv') or 'str', '[^/]+')})"
        pos = m.end()
    return "^/" + out + re.escape(pattern[pos:]) + "$"


def match_route(routes, method, path):
    path = path.split("?")[0]
    for r in routes:
        if re.match(route_regex(r["pattern"]), path):
            return r if method.upper() in r["methods"] or not r["methods"] else {**r, "method_not_allowed": True}
    return None


# ------------------------------------------------------------------------ analyzer


class Analyzer:
    def __init__(self, files):
        self.files = {name: (files.get(name) or "") for name in FILES}
        self.trees = {}
        self.diagnostics = []
        self.annotations = []
        self.models, self.serializers, self.views, self.routes = [], [], [], []
        self.tables, self.edges = [], []
        self.bindings = {}

    # -- diagnostics ------------------------------------------------------------

    def diag(self, file, where, message, severity="error", hint=None):
        if isinstance(where, int):
            line, col, end_line, end_col = where, 0, where, None
        else:
            line = getattr(where, "lineno", 1)
            col = getattr(where, "col_offset", 0)
            end_line = getattr(where, "end_lineno", line) or line
            end_col = getattr(where, "end_col_offset", None)
        self.diagnostics.append({
            "file": file, "line": line, "col": col, "end_line": end_line, "end_col": end_col,
            "severity": severity, "message": message, "hint": hint,
        })

    def annotate(self, ann):
        if ann:
            self.annotations.append(ann)

    # -- entry point --------------------------------------------------------------

    def run(self):
        for name, text in self.files.items():
            try:
                self.trees[name] = ast.parse(text, filename=name)
            except SyntaxError as exc:
                self.diag(name, exc.lineno or 1, f"{type(exc).__name__}: {exc.msg}", hint=syntax_hint(exc))
        for name, tree in self.trees.items():
            self.bindings[name] = module_bindings(tree)

        if "models.py" in self.trees:
            self.parse_models(self.trees["models.py"])
        self.build_tables()
        if "serializers.py" in self.trees:
            self.parse_serializers(self.trees["serializers.py"])
        if "views.py" in self.trees:
            self.parse_views(self.trees["views.py"])
        if "urls.py" in self.trees:
            self.parse_urls(self.trees["urls.py"])

        for name, tree in self.trees.items():
            self.check_names(name, tree)
            self.check_imports(name, tree)

        self.diagnostics.sort(key=lambda d: (FILES.index(d["file"]), d["line"]))
        errors = sum(d["severity"] == "error" for d in self.diagnostics)
        return {
            "ok": errors == 0,
            "diagnostics": self.diagnostics,
            "models": self.models,
            "tables": self.tables,
            "edges": self.edges,
            "serializers": self.serializers,
            "views": self.views,
            "routes": self.routes,
            "annotations": self.annotations,
            "summary": {
                "models": len(self.models),
                "fields": sum(len(m["fields"]) for m in self.models),
                "relations": sum(1 for m in self.models for f in m["fields"] if f.get("relation")),
                "serializers": len(self.serializers),
                "views": len(self.views),
                "routes": len(self.routes),
                "errors": errors,
                "warnings": sum(d["severity"] == "warning" for d in self.diagnostics),
            },
        }

    # -- models.py ------------------------------------------------------------------

    def parse_models(self, tree):
        classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
        model_names = []
        for cls in classes:
            bases = [dotted(b) for b in cls.bases]
            if any(b in ("models.Model", "Model") or b in model_names for b in bases):
                model_names.append(cls.name)
        all_models = set(model_names)

        defined = set()
        for cls in classes:
            if cls.name not in all_models:
                continue
            m = {
                "name": cls.name, "line": cls.lineno, "end_line": cls.end_lineno,
                "table": f"{APP_LABEL}_{cls.name.lower()}", "fields": [], "methods": [], "properties": [],
                "has_str": False, "abstract": False, "reverse": [],
                "meta": {"constraints": [], "indexes": [], "ordering": None, "unique_together": []},
            }
            meta_node = None
            for stmt in cls.body:
                name = single_target(stmt)
                if name and isinstance(stmt.value, ast.Call):
                    f = self.parse_field(m, name, stmt, stmt.value, defined, all_models)
                    if f:
                        m["fields"].append(f)
                elif isinstance(stmt, ast.FunctionDef):
                    m["methods"].append(stmt.name)
                    if stmt.name == "__str__":
                        m["has_str"] = True
                        if not returns_value(stmt):
                            self.diag("models.py", stmt, "__str__ returned non-string (type NoneType)",
                                      hint="__str__ must return a string, e.g. return self.name")
                    if any(dotted(d) == "property" for d in stmt.decorator_list):
                        m["properties"].append(stmt.name)
                elif isinstance(stmt, ast.ClassDef) and stmt.name == "Meta":
                    meta_node = stmt
            if meta_node is not None:
                self.parse_model_meta(m, meta_node)
            if not any(f["primary_key"] for f in m["fields"]):
                m["fields"].insert(0, {
                    "name": "id", "type": "AutoField", "line": cls.lineno, "end_line": cls.lineno, "column": "id",
                    "db_type": "integer", "primary_key": True, "unique": True, "null": False, "implicit": True,
                    "options": {}, "values": {}, "relation": None, "constraints": ["PRIMARY KEY"],
                })
            if not m["has_str"] and not m["abstract"]:
                self.diag("models.py", cls.lineno, f"{cls.name} has no __str__ method — rows will display as "
                          f"'{cls.name} object (1)'.", severity="info",
                          hint="def __str__(self):\n    return self.name")
            defined.add(cls.name)
            self.models.append(m)
            self.annotate(explain.model(m))
            if meta_node is not None:
                self.annotate(explain.meta(m, meta_node.lineno, meta_node.end_lineno))

        self.link_reverse_relations()
        for m in self.models:
            for f in m["fields"]:
                if not f.get("implicit"):
                    junction = f"{m['table']}_{f['name']}" if f["type"] == "ManyToManyField" else None
                    self.annotate(explain.field(m, f, junction))

    def parse_field(self, m, name, stmt, call, defined, all_models):
        func = dotted(call.func)
        ftype = last(func)
        if not ftype or not (func.startswith("models.") or func == ftype):
            return None
        if not (ftype.endswith("Field") or ftype in RELATION_FIELDS or ftype.endswith("Key")):
            return None
        if ftype not in KNOWN_FIELDS:
            close = difflib.get_close_matches(ftype, KNOWN_FIELDS, n=1)
            self.diag("models.py", call.func, f"AttributeError: module 'django.db.models' has no attribute '{ftype}'",
                      hint=f"Did you mean models.{close[0]}?" if close else None)
            return None

        kw = kwargs_of(call)
        vals = {k: lit(v) for k, v in kw.items()}
        f = {
            "name": name, "type": ftype, "line": stmt.lineno, "end_line": stmt.end_lineno,
            "options": {k: src(v) for k, v in kw.items()}, "values": vals,
            "primary_key": vals.get("primary_key") is True,
            "unique": vals.get("unique") is True or ftype == "OneToOneField" or vals.get("primary_key") is True,
            "null": vals.get("null") is True, "relation": None, "implicit": False,
        }

        if ftype in RELATION_FIELDS:
            f["relation"] = self.parse_relation(m, f, call, kw, defined, all_models)

        if ftype == "CharField" and "max_length" not in kw:
            self.diag("models.py", call, f"{m['name']}.{name}: (fields.E120) CharFields must define a "
                      "'max_length' attribute.", hint="e.g. models.CharField(max_length=200)")
        if ftype == "DecimalField":
            for opt, code in (("max_digits", "E132"), ("decimal_places", "E130")):
                if opt not in kw:
                    self.diag("models.py", call, f"{m['name']}.{name}: (fields.{code}) DecimalFields must define a "
                              f"'{opt}' attribute.", hint="e.g. models.DecimalField(max_digits=10, decimal_places=2)")
            md, dp = vals.get("max_digits"), vals.get("decimal_places")
            if isinstance(md, int) and isinstance(dp, int) and dp > md:
                self.diag("models.py", call, f"{m['name']}.{name}: (fields.E134) 'max_digits' must be greater or "
                          "equal to 'decimal_places'.")
        if f["null"] and ftype in ("CharField", "TextField", "SlugField", "EmailField", "URLField"):
            self.diag("models.py", call, f"{m['name']}.{name}: avoid null=True on text fields — Django's convention "
                      "is to store empty strings instead of NULL.", severity="info", hint="Use blank=True alone.")
        if ftype == "ManyToManyField" and "null" in kw:
            self.diag("models.py", call, f"{m['name']}.{name}: (fields.W340) null has no effect on ManyToManyField.",
                      severity="warning")

        max_length = vals.get("max_length", DEFAULT_MAX_LENGTH.get(ftype))
        db_type = FIELD_DB_TYPES.get(ftype)
        if db_type and "{max_length}" in db_type:
            db_type = db_type.format(max_length=max_length if max_length is not None else "?")
        f["db_type"] = db_type
        if ftype in ("ForeignKey", "OneToOneField"):
            f["column"] = f"{name}_id"
        elif ftype == "ManyToManyField":
            f["column"] = None
        else:
            f["column"] = vals.get("db_column") or name

        cons = []
        if f["primary_key"]:
            cons.append("PRIMARY KEY")
        if f["unique"] and not f["primary_key"]:
            cons.append("UNIQUE")
        if f["column"]:
            cons.append("NULL" if f["null"] else "NOT NULL")
        if ftype.startswith("Positive"):
            cons.append("CHECK >= 0")
        if f["relation"] and f["column"]:
            cons.append(f"FK → {APP_LABEL}_{f['relation']['target'].lower()}.id")
        if vals.get("db_index") or ftype == "SlugField" or ftype == "ForeignKey":
            if not f["unique"]:
                cons.append("INDEX")
        if "default" in kw:
            cons.append(f"default {f['options']['default']}")
        f["constraints"] = cons
        return f

    def parse_relation(self, m, f, call, kw, defined, all_models):
        ftype = f["type"]
        target_node = call.args[0] if call.args else kw.get("to")
        target = None
        if target_node is None:
            self.diag("models.py", call, f"{ftype} needs the related model as its first argument.",
                      hint=f"models.{ftype}(Category, ...)")
        elif isinstance(target_node, ast.Constant) and isinstance(target_node.value, str):
            target = target_node.value.split(".")[-1]
            if target == "self":
                target = m["name"]
            elif target not in all_models:
                self.diag("models.py", target_node, f"{m['name']}.{f['name']}: (fields.E300) Field defines a relation "
                          f"with model '{target}', which is either not installed, or is abstract.")
        elif isinstance(target_node, ast.Name):
            target = target_node.id
            if target in all_models and target not in defined:
                where = "itself" if target == m["name"] else "further down the file"
                self.diag("models.py", target_node, f"NameError: name '{target}' is not defined",
                          hint=f"{target} is defined {where}. Python runs models.py top to bottom, so either move "
                               f"class {target} above {m['name']} or pass the string \"{target if target != m['name'] else 'self'}\".")
        else:
            target = src(target_node)

        rel = {"kind": {"ForeignKey": "many-to-one", "OneToOneField": "one-to-one",
                        "ManyToManyField": "many-to-many"}[ftype],
               "target": target, "on_delete": None, "related_name": f["values"].get("related_name"),
               "through": f["values"].get("through") or (src(kw["through"]) if "through" in kw else None)}

        if ftype != "ManyToManyField":
            od = call.args[1] if len(call.args) > 1 else kw.get("on_delete")
            if od is None:
                self.diag("models.py", call, f"TypeError: {ftype}.__init__() missing 1 required positional "
                          "argument: 'on_delete'",
                          hint="Choose what happens when the related row is deleted, e.g. on_delete=models.PROTECT")
            else:
                name = last(dotted(od)) or src(od)
                if isinstance(od, ast.Call):
                    name = "SET"
                elif name not in ON_DELETE:
                    self.diag("models.py", od, f"AttributeError: module 'django.db.models' has no attribute '{name}'",
                              hint="Options: " + ", ".join(sorted(ON_DELETE)))
                rel["on_delete"] = name
                if name == "SET_NULL" and not f["null"]:
                    self.diag("models.py", od, f"{m['name']}.{f['name']}: (fields.E320) Field specifies "
                              "on_delete=SET_NULL, but cannot be null.", hint="Add null=True to the field.")
        return rel

    def parse_model_meta(self, m, meta_node):
        meta = m["meta"]
        for stmt in meta_node.body:
            name = single_target(stmt)
            if not name:
                continue
            value = stmt.value
            if name == "db_table" and isinstance(lit(value), str):
                meta["db_table"] = lit(value)
                m["table"] = lit(value)
            elif name == "abstract":
                m["abstract"] = lit(value) is True
            elif name in ("ordering", "verbose_name", "verbose_name_plural"):
                meta[name] = lit(value, src(value))
            elif name == "unique_together":
                ut = lit(value) or []
                if ut and isinstance(ut[0], str):
                    ut = [ut]
                meta["unique_together"] = [list(x) for x in ut]
            elif name in ("constraints", "indexes") and isinstance(value, (ast.List, ast.Tuple)):
                for el in value.elts:
                    if not isinstance(el, ast.Call):
                        continue
                    ckw = kwargs_of(el)
                    item = {"kind": last(dotted(el.func)), "name": lit(ckw.get("name")),
                            "fields": lit(ckw.get("fields")), "line": el.lineno, "src": src(el)}
                    if name == "constraints" and not item["name"]:
                        self.diag("models.py", el, f"ValueError: A {item['kind']} must be named.",
                                  hint='Add name="unique_product_per_cart" (any unique name).')
                    meta[name].append(item)
        field_names = {f["name"] for f in m["fields"]}
        groups = [(c["fields"], c["line"]) for c in meta["constraints"] + meta["indexes"] if c.get("fields")]
        for fields, line in groups:
            for fname in fields:
                if fname.lstrip("-") not in field_names:
                    self.diag("models.py", line, f"{m['name']}: (models.E012) constraint/index refers to the "
                              f"nonexistent field '{fname}'.")

    def link_reverse_relations(self):
        by_name = {m["name"]: m for m in self.models}
        seen = {}
        for m in self.models:
            for f in m["fields"]:
                rel = f.get("relation")
                if not rel or rel["target"] not in by_name:
                    continue
                accessor = rel["related_name"]
                if accessor is None:
                    accessor = m["name"].lower() + ("" if f["type"] == "OneToOneField" else "_set")
                if accessor.endswith("+"):
                    continue
                target = by_name[rel["target"]]
                key = (target["name"], accessor)
                if key in seen:
                    self.diag("models.py", f["line"], f"{m['name']}.{f['name']}: (fields.E304) Reverse accessor "
                              f"'{target['name']}.{accessor}' clashes with reverse accessor for '{seen[key]}'.",
                              hint="Give one of them a different related_name.")
                seen[key] = f"{m['name']}.{f['name']}"
                target["reverse"].append({"name": accessor, "model": m["name"], "field": f["name"],
                                          "kind": f["type"]})

    def build_tables(self):
        by_name = {m["name"]: m for m in self.models}

        def pk_col(model):
            return next((f["column"] for f in model["fields"] if f["primary_key"]), "id")

        for m in self.models:
            if m["abstract"]:
                continue
            cols = []
            for f in m["fields"]:
                if f["type"] == "ManyToManyField":
                    continue
                col = {"name": f["column"], "type": f["db_type"], "pk": f["primary_key"], "unique": f["unique"],
                       "null": f["null"], "field": f["name"], "field_type": f["type"], "line": f["line"],
                       "implicit": f.get("implicit", False), "fk": None, "constraints": f["constraints"]}
                rel = f.get("relation")
                target = by_name.get(rel["target"]) if rel else None
                if target:
                    col["fk"] = {"table": target["table"], "column": pk_col(target)}
                    self.edges.append({
                        "id": f"{m['table']}.{f['column']}", "source": m["table"], "source_column": f["column"],
                        "target": target["table"], "target_column": pk_col(target), "kind": rel["kind"],
                        "on_delete": rel["on_delete"], "field": f"{m['name']}.{f['name']}",
                        "label": ("N : 1" if rel["kind"] == "many-to-one" else "1 : 1"),
                    })
                cols.append(col)
            self.tables.append({"name": m["table"], "model": m["name"], "kind": "model", "line": m["line"],
                                "columns": cols})

            for f in m["fields"]:
                rel = f.get("relation")
                if f["type"] != "ManyToManyField" or rel["through"] or rel["target"] not in by_name:
                    continue
                target = by_name[rel["target"]]
                table = f"{m['table']}_{f['name']}"
                if target["name"] == m["name"]:
                    src_col, dst_col = f"from_{m['name'].lower()}_id", f"to_{m['name'].lower()}_id"
                else:
                    src_col, dst_col = f"{m['name'].lower()}_id", f"{target['name'].lower()}_id"
                self.tables.append({
                    "name": table, "model": None, "kind": "junction", "via": f"{m['name']}.{f['name']}",
                    "line": f["line"],
                    "columns": [
                        {"name": "id", "type": "integer", "pk": True, "unique": True, "null": False, "field": None,
                         "line": f["line"], "implicit": True, "fk": None, "constraints": ["PRIMARY KEY"]},
                        {"name": src_col, "type": "integer", "pk": False, "unique": False, "null": False,
                         "field": None, "line": f["line"], "implicit": True,
                         "fk": {"table": m["table"], "column": pk_col(m)}, "constraints": ["NOT NULL"]},
                        {"name": dst_col, "type": "integer", "pk": False, "unique": False, "null": False,
                         "field": None, "line": f["line"], "implicit": True,
                         "fk": {"table": target["table"], "column": pk_col(target)}, "constraints": ["NOT NULL"]},
                    ],
                })
                for col, tgt in ((src_col, m), (dst_col, target)):
                    self.edges.append({
                        "id": f"{table}.{col}", "source": table, "source_column": col, "target": tgt["table"],
                        "target_column": pk_col(tgt), "kind": "many-to-many", "on_delete": "CASCADE",
                        "field": f"{m['name']}.{f['name']}", "label": "N : M",
                    })

    # -- serializers.py ---------------------------------------------------------------

    def parse_serializers(self, tree):
        models_by_name = {m["name"]: m for m in self.models}
        classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
        all_names = set()
        for cls in classes:
            if any(last(dotted(b)) in SERIALIZER_BASES or last(dotted(b)) in all_names for b in cls.bases):
                all_names.add(cls.name)
        defined = set()
        for cls in classes:
            if cls.name not in all_names:
                continue
            bases = [last(dotted(b)) for b in cls.bases]
            base = next((b for b in bases if b in SERIALIZER_BASES), None) or next(b for b in bases if b in all_names)
            s = {"name": cls.name, "line": cls.lineno, "end_line": cls.end_lineno, "base": base, "model": None,
                 "fields": None, "exclude": None, "read_only_fields": [], "declared": [], "methods": [],
                 "validators": []}
            meta_node = None
            for stmt in cls.body:
                name = single_target(stmt)
                if name and isinstance(stmt.value, ast.Call):
                    call = stmt.value
                    ftype = last(dotted(call.func))
                    ckw = kwargs_of(call)
                    if ftype in all_names:
                        if ftype not in defined:
                            self.diag("serializers.py", call.func, f"NameError: name '{ftype}' is not defined",
                                      hint=f"Move class {ftype} above {cls.name}: Python needs it to exist first.")
                        s["declared"].append({"name": name, "kind": "nested", "serializer": ftype,
                                              "many": lit(ckw.get("many")) is True,
                                              "read_only": lit(ckw.get("read_only")) is True,
                                              "line": stmt.lineno, "end_line": stmt.end_lineno})
                    elif ftype and (ftype.endswith("Field") or ftype.endswith("RelatedField")):
                        s["declared"].append({"name": name, "kind": ftype, "source": lit(ckw.get("source")),
                                              "method_name": lit(ckw.get("method_name")),
                                              "read_only": lit(ckw.get("read_only")) is True
                                              or ftype in ("SerializerMethodField", "ReadOnlyField"),
                                              "line": stmt.lineno, "end_line": stmt.end_lineno})
                elif isinstance(stmt, ast.FunctionDef):
                    s["methods"].append(stmt.name)
                    if stmt.name == "validate" or stmt.name.startswith("validate_"):
                        s["validators"].append(stmt.name)
                        self.annotate(explain.validator(s, stmt.name, stmt.lineno, stmt.end_lineno))
                        if not returns_value(stmt):
                            self.diag("serializers.py", stmt, f"{stmt.name}() never returns a value — DRF will use "
                                      "None as the validated value.", severity="warning",
                                      hint="End with `return value` (or `return attrs` in validate).")
                elif isinstance(stmt, ast.ClassDef) and stmt.name == "Meta":
                    meta_node = stmt
            if meta_node is not None:
                for stmt in meta_node.body:
                    name = single_target(stmt)
                    if name == "model":
                        s["model"] = last(dotted(stmt.value))
                        if s["model"] and s["model"] not in models_by_name and self.models:
                            self.diag("serializers.py", stmt.value, f"{s['model']} is not a model in models.py.",
                                      severity="warning")
                    elif name in ("fields", "exclude", "read_only_fields"):
                        value = lit(stmt.value, None)
                        s[name] = list(value) if isinstance(value, (list, tuple)) else value
                        s[f"{name}_line"] = stmt.lineno
            self.validate_serializer(s, cls, meta_node, models_by_name.get(s["model"]))
            defined.add(cls.name)
            self.serializers.append(s)
            self.annotate(explain.serializer(s))
            if meta_node is not None:
                self.annotate(explain.serializer_meta(s, meta_node.lineno, meta_node.end_lineno))
            for d in s["declared"]:
                self.annotate(explain.declared_field(s, d))

    def validate_serializer(self, s, cls, meta_node, model):
        declared = {d["name"]: d for d in s["declared"]}
        is_model_ser = s["base"] in MODEL_SERIALIZER_BASES
        if is_model_ser:
            if meta_node is None:
                self.diag("serializers.py", cls, f'AssertionError: Class {s["name"]} missing "Meta" attribute',
                          hint="class Meta:\n    model = Product\n    fields = [...]")
            elif not s["model"]:
                self.diag("serializers.py", meta_node, f'AssertionError: Class {s["name"]} missing "Meta.model" '
                          "attribute")
            if meta_node is not None and s["fields"] is None and s["exclude"] is None:
                self.diag("serializers.py", meta_node, f"AssertionError: Creating a ModelSerializer without either "
                          f"the 'fields' attribute or the 'exclude' attribute is disallowed ({s['name']}).",
                          hint='fields = ["id", "name"]  # or "__all__"')

        effective = []
        if model:
            model_fields = {f["name"]: f for f in model["fields"]}
            reverse = {r["name"]: r for r in model["reverse"]}
            extra = set(model["methods"]) | set(model["properties"]) | {"pk"}
            if s["fields"] == "__all__":
                names = list(model_fields) + [n for n in declared if n not in model_fields]
            elif isinstance(s["fields"], list):
                names = s["fields"]
            else:
                names = [n for n in list(model_fields) + list(declared) if n not in (s["exclude"] or [])]
            ro = set(s["read_only_fields"] or [])
            for n in names:
                if n in declared:
                    d = declared[n]
                    kind = d["kind"]
                    describe = (f"nested {d['serializer']}{' list' if d['many'] else ''}" if kind == "nested"
                                else f"{kind}" + (f" reading {d['source']}" if d.get("source") else ""))
                    effective.append({"name": n, "source": "declared", "read_only": d["read_only"], "kind": kind,
                                      "describe": describe})
                elif n in model_fields:
                    mf = model_fields[n]
                    auto = mf["primary_key"] or mf["values"].get("auto_now_add") is True or \
                        mf["values"].get("auto_now") is True or mf["values"].get("editable") is False
                    if mf.get("relation"):
                        describe = (f"PrimaryKeyRelatedField: accepts a {mf['relation']['target']} id and rejects "
                                    "ids that don't exist")
                        if mf["type"] == "ManyToManyField":
                            describe = f"list of {mf['relation']['target']} ids"
                    else:
                        describe = f"from model field {mf['type']}"
                    effective.append({"name": n, "source": "model", "read_only": auto or n in ro,
                                      "kind": mf["type"], "describe": describe})
                elif n in reverse:
                    effective.append({"name": n, "source": "reverse", "read_only": True, "kind": "reverse",
                                      "describe": f"reverse relation from {reverse[n]['model']} (list of ids)"})
                elif n in extra:
                    effective.append({"name": n, "source": "method", "read_only": True, "kind": "ReadOnlyField",
                                      "describe": f"value of {model['name']}.{n}"})
                else:
                    self.diag("serializers.py", s.get("fields_line", s["line"]),
                              f"ImproperlyConfigured: Field name `{n}` is not valid for model `{model['name']}` "
                              f"in `{s['name']}`.",
                              hint=difflib.get_close_matches(n, list(model_fields) + list(reverse), n=1)
                              and f"Did you mean `{difflib.get_close_matches(n, list(model_fields) + list(reverse), n=1)[0]}`?")
        if isinstance(s["fields"], list):
            for d in s["declared"]:
                if d["name"] not in s["fields"]:
                    self.diag("serializers.py", d["line"], f"AssertionError: The field '{d['name']}' was declared on "
                              f"serializer {s['name']}, but has not been included in the 'fields' option.",
                              hint=f'Add "{d["name"]}" to Meta.fields.')
        for d in s["declared"]:
            if d["kind"] == "SerializerMethodField":
                method = d.get("method_name") or f"get_{d['name']}"
                if method not in s["methods"]:
                    self.diag("serializers.py", d["line"], f"AttributeError: '{s['name']}' object has no attribute "
                              f"'{method}'", hint=f"def {method}(self, obj):\n    return ...")
        field_names = {e["name"] for e in effective} | set(declared)
        for v in s["validators"]:
            if v.startswith("validate_") and field_names and v[len("validate_"):] not in field_names:
                self.diag("serializers.py", s["line"], f"{v}() will never run: `{v[len('validate_'):]}` is not a "
                          f"field of {s['name']}.", severity="warning")
        s["effective_fields"] = effective

    # -- views.py ------------------------------------------------------------------------

    def parse_views(self, tree):
        model_map = {m["name"]: m for m in self.models}
        ser_names = {s["name"] for s in self.serializers}
        list_globals = set()
        for stmt in tree.body:
            name = single_target(stmt)
            if name and isinstance(stmt.value, (ast.List, ast.ListComp, ast.Tuple)):
                list_globals.add(name)

        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                v = self.parse_function_view(node, list_globals, ser_names)
            elif isinstance(node, ast.ClassDef):
                v = self.parse_class_view(node, ser_names)
            else:
                continue
            if v is None:
                continue
            if not v.get("model") and v.get("serializer"):
                ser = next((s for s in self.serializers if s["name"] == v["serializer"]), None)
                v["model"] = ser and ser["model"]
            self.scan_orm(node, model_map)
            self.views.append(v)
            self.annotate(explain.view(v))

    def parse_function_view(self, node, list_globals, ser_names):
        methods, kind = ["GET", "POST", "PUT", "PATCH", "DELETE"], "function"
        for deco in node.decorator_list:
            if isinstance(deco, ast.Call) and last(dotted(deco.func)) == "api_view":
                kind = "api_function"
                methods = [str(m).upper() for m in (lit(deco.args[0]) if deco.args else ["GET"]) or ["GET"]]
            elif last(dotted(deco)) == "api_view":
                kind, methods = "api_function", ["GET"]
        params = [a.arg for a in node.args.args]
        local_lists = set(list_globals)
        responses, statuses, models_used, sers_used = [], [], set(), set()
        for sub in ast.walk(node):
            name = single_target(sub) if isinstance(sub, (ast.Assign, ast.AnnAssign)) else None
            if name and isinstance(sub.value, (ast.List, ast.ListComp)):
                local_lists.add(name)
            if isinstance(sub, ast.Call):
                fname = last(dotted(sub.func))
                if fname in ("JsonResponse", "Response", "HttpResponse"):
                    responses.append(fname)
                    st = kwargs_of(sub).get("status")
                    if st is not None:
                        statuses.append(lit(st) or last(dotted(st)) or src(st))
                    if fname == "JsonResponse" and sub.args and "safe" not in kwargs_of(sub):
                        arg = sub.args[0]
                        if isinstance(arg, (ast.List, ast.ListComp)) or (isinstance(arg, ast.Name)
                                                                         and arg.id in local_lists):
                            self.diag("views.py", sub, "TypeError: In order to allow non-dict objects to be "
                                      "serialized set the safe parameter to False.",
                                      hint="JsonResponse(data, safe=False) — JSON arrays at the top level need "
                                           "an explicit opt-in.")
            if isinstance(sub, ast.Name) and sub.id in ser_names:
                sers_used.add(sub.id)
            if isinstance(sub, ast.Attribute) and sub.attr == "objects" and isinstance(sub.value, ast.Name):
                models_used.add(sub.value.id)
        return {
            "name": node.name, "kind": kind, "base": None, "methods": methods, "line": node.lineno,
            "end_line": node.end_lineno, "params": params, "has_kwargs": node.args.kwarg is not None,
            "required_params": params[: len(params) - len(node.args.defaults)],
            "returns": returns_value(node), "responses": responses, "statuses": statuses,
            "serializer": next(iter(sorted(sers_used)), None), "model": next(iter(sorted(models_used)), None),
            "queryset": None, "detail": None,
        }

    def parse_class_view(self, node, ser_names):
        bases = [last(dotted(b)) for b in node.bases]
        base = next((b for b in bases if b in CLASS_VIEW_BASES), None)
        if not base:
            return None
        attrs = {}
        for stmt in node.body:
            name = single_target(stmt)
            if name:
                attrs[name] = stmt.value
        methods_defined = [s.name for s in node.body if isinstance(s, ast.FunctionDef)]
        v = {"name": node.name, "kind": "viewset" if base.endswith("ViewSet") else
             ("generic" if base in QUERYSET_VIEWS else "apiview"), "base": base, "line": node.lineno,
             "end_line": node.end_lineno, "queryset": None, "serializer": None, "model": None,
             "lookup": lit(attrs.get("lookup_url_kwarg")) or lit(attrs.get("lookup_field")) or "pk",
             "detail": base in DETAIL_VIEWS, "methods_defined": methods_defined}
        if "queryset" in attrs:
            v["queryset"] = src(attrs["queryset"])
            chain = orm_chain(attrs["queryset"])
            v["model"] = chain and chain["model"]
        if "serializer_class" in attrs:
            v["serializer"] = last(dotted(attrs["serializer_class"]))
        if base in GENERIC_VIEWS:
            v["methods"] = GENERIC_VIEWS[base]
        elif base in VIEWSETS:
            v["methods"] = sorted(set(VIEWSETS[base][0]) | set(VIEWSETS[base][1]))
        else:
            v["methods"] = [m.upper() for m in HTTP_METHODS if m in methods_defined]
        if base in QUERYSET_VIEWS:
            if "queryset" not in attrs and "get_queryset" not in methods_defined:
                self.diag("views.py", node, f"AssertionError: '{node.name}' should either include a `queryset` "
                          "attribute, or override the `get_queryset()` method.",
                          hint="queryset = Product.objects.all()")
            if "serializer_class" not in attrs and "get_serializer_class" not in methods_defined:
                self.diag("views.py", node, f"AssertionError: '{node.name}' should either include a "
                          "`serializer_class` attribute, or override the `get_serializer_class()` method.")
        return v

    def scan_orm(self, scope, model_map):
        """Annotate ORM queries and flag loops that would trigger N+1 queries."""
        chains, assigned = [], {}
        for sub in ast.walk(scope):
            if isinstance(sub, ast.Call):
                chain = orm_chain(sub)
                if chain and chain["model"] in model_map:
                    chains.append((sub, chain))
            name = single_target(sub) if isinstance(sub, (ast.Assign, ast.AnnAssign)) else None
            if name:
                chain = orm_chain(sub.value)
                if chain:
                    assigned[name] = chain
        texts = [c["text"] for _, c in chains]
        for node, chain in chains:
            if not any(t != chain["text"] and chain["text"] in t for t in texts):
                self.annotate(explain.orm(chain, "views.py", node.lineno, node.end_lineno))

        loops = []
        for sub in ast.walk(scope):
            if isinstance(sub, ast.For):
                loops.append((sub.iter, sub.target, sub.body))
            elif isinstance(sub, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
                body = [sub.key, sub.value] if isinstance(sub, ast.DictComp) else [sub.elt]
                for gen in sub.generators:
                    loops.append((gen.iter, gen.target, body))
        for it, target, body in loops:
            chain = orm_chain(it) or (assigned.get(it.id) if isinstance(it, ast.Name) else None)
            if not chain or not isinstance(target, ast.Name) or chain["model"] not in model_map:
                continue
            model = model_map[chain["model"]]
            selected, prefetched, select_all = set(), set(), False
            for call in chain["calls"]:
                if call["method"] == "select_related":
                    select_all = select_all or not call["args"]
                    selected.update(str(a).split("__")[0] for a in call["args"])
                elif call["method"] == "prefetch_related":
                    prefetched.update(str(a).split("__")[0] for a in call["args"])
            fks = {f["name"] for f in model["fields"] if f["type"] in ("ForeignKey", "OneToOneField")}
            many = {f["name"] for f in model["fields"] if f["type"] == "ManyToManyField"} | \
                   {r["name"] for r in model["reverse"]}
            flagged = set()
            for stmt in body:
                for sub in ast.walk(stmt):
                    if not (isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name)
                            and sub.value.id == target.id) or sub.attr in flagged:
                        continue
                    if sub.attr in fks and not select_all and sub.attr not in selected:
                        flagged.add(sub.attr)
                        self.diag("views.py", sub, f"N+1 queries: `{target.id}.{sub.attr}` runs one extra SELECT "
                                  f"for every {model['name']} in the loop.", severity="warning",
                                  hint=f'Add .select_related("{sub.attr}") to the queryset — one JOIN instead of N '
                                       "queries.")
                    elif sub.attr in many and sub.attr not in prefetched:
                        flagged.add(sub.attr)
                        self.diag("views.py", sub, f"N+1 queries: `{target.id}.{sub.attr}` queries the database "
                                  f"once per {model['name']}.", severity="warning",
                                  hint=f'Add .prefetch_related("{sub.attr}") to the queryset.')

    # -- urls.py -----------------------------------------------------------------------------

    def parse_urls(self, tree):
        views = {v["name"]: v for v in self.views}
        view_funcs = set(self.bindings.get("views.py", (set(), False))[0])
        direct_imports = set()
        routers = {}
        has_patterns = False
        for stmt in tree.body:
            if isinstance(stmt, ast.ImportFrom) and stmt.level == 1 and stmt.module == "views":
                direct_imports.update(a.asname or a.name for a in stmt.names)
            name = single_target(stmt)
            if name and isinstance(stmt.value, ast.Call) and last(dotted(stmt.value.func)) in ("DefaultRouter",
                                                                                             "SimpleRouter"):
                routers[name] = {"line": stmt.lineno, "end_line": stmt.end_lineno, "registrations": [],
                                 "included": None}
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                call = stmt.value
                if isinstance(call.func, ast.Attribute) and call.func.attr == "register" and \
                        isinstance(call.func.value, ast.Name) and call.func.value.id in routers and len(call.args) >= 2:
                    view_name = last(dotted(call.args[1]))
                    routers[call.func.value.id]["registrations"].append(
                        {"prefix": lit(call.args[0], "?"), "view": view_name, "line": stmt.lineno,
                         "end_line": stmt.end_lineno})
                    self.check_view_ref(call.args[1], view_name, views, view_funcs, direct_imports, require_viewset=True)

        for stmt in tree.body:
            targets = []
            if isinstance(stmt, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "urlpatterns"
                                                    for t in stmt.targets):
                targets = [stmt.value]
            elif isinstance(stmt, ast.AugAssign) and isinstance(stmt.target, ast.Name) and \
                    stmt.target.id == "urlpatterns":
                targets = [stmt.value]
            if not targets:
                continue
            has_patterns = True
            while targets:
                value = targets.pop()
                if isinstance(value, ast.BinOp):
                    targets.extend([value.left, value.right])
                elif isinstance(value, (ast.List, ast.Tuple)):
                    for el in value.elts:
                        self.parse_url_entry(el, views, view_funcs, direct_imports, routers)
                elif isinstance(value, ast.Attribute) and value.attr == "urls" and \
                        isinstance(value.value, ast.Name) and value.value.id in routers:
                    routers[value.value.id]["included"] = ""

        if not has_patterns and self.files["urls.py"].strip():
            self.diag("urls.py", 1, "ImproperlyConfigured: The included URLconf 'store.urls' does not appear to have "
                      "any patterns in it.", hint="urlpatterns = [\n    path(...),\n]")

        for var, r in routers.items():
            self.annotate(explain.router(var, r["line"], r["end_line"], r["registrations"]))
            if r["included"] is None:
                if r["registrations"]:
                    self.diag("urls.py", r["line"], f"{var} has registered ViewSets but {var}.urls is never added to "
                              "urlpatterns, so those routes don't exist.", severity="warning",
                              hint=f'path("api/", include({var}.urls))')
                continue
            for reg in r["registrations"]:
                v = views.get(reg["view"])
                list_methods, detail_methods = VIEWSETS.get(v["base"] if v else "", (["GET"], ["GET"]))
                base = f"{r['included']}{reg['prefix']}/"
                for pattern, methods, suffix in ((base, list_methods, "list"),
                                                 (f"{base}<pk>/", detail_methods, "detail")):
                    self.add_route(pattern, reg["view"], methods, reg["line"], reg["end_line"],
                                   f"{reg['prefix']}-{suffix}", class_view=True, router=var)

        seen = {}
        for r in self.routes:
            if r["pattern"] in seen:
                self.diag("urls.py", r["line"], f"'{r['pattern']}' is already routed on line {seen[r['pattern']]}; "
                          "this pattern can never be reached.", severity="warning")
            seen.setdefault(r["pattern"], r["line"])

    def parse_url_entry(self, el, views, view_funcs, direct_imports, routers):
        if not isinstance(el, ast.Call) or last(dotted(el.func)) not in ("path", "re_path"):
            return
        if len(el.args) < 2:
            self.diag("urls.py", el, "path() needs a route and a view: path(\"api/products/\", views.product_list)")
            return
        route = lit(el.args[0])
        if not isinstance(route, str):
            return
        view_node = el.args[1]
        url_name = lit(kwargs_of(el).get("name"))
        if route.startswith("/"):
            self.diag("urls.py", el.args[0], f"(urls.W002) Your URL pattern '{route}' has a route beginning with a "
                      "'/'. Remove this slash as it is unnecessary.", severity="warning")

        if isinstance(view_node, ast.Call) and last(dotted(view_node.func)) == "include":
            arg = view_node.args[0] if view_node.args else None
            if isinstance(arg, ast.Attribute) and arg.attr == "urls" and isinstance(arg.value, ast.Name) \
                    and arg.value.id in routers:
                routers[arg.value.id]["included"] = route
            return
        if isinstance(view_node, ast.Call) and isinstance(view_node.func, ast.Attribute) and \
                view_node.func.attr == "as_view":
            view_name = last(dotted(view_node.func.value))
            v = self.check_view_ref(view_node.func.value, view_name, views, view_funcs, direct_imports)
            if v and v["kind"] in ("function", "api_function"):
                self.diag("urls.py", view_node, f"AttributeError: 'function' object has no attribute 'as_view'",
                          hint=f"{view_name} is a function view — pass it without .as_view().")
            self.add_route(route, view_name, (v or {}).get("methods", []), el.lineno, el.end_lineno, url_name,
                           class_view=True)
            if v and v.get("detail") and f"<{v['lookup']}>" not in route and f":{v['lookup']}>" not in route:
                self.diag("urls.py", el, f'AssertionError: Expected view {view_name} to be called with a URL keyword '
                          f'argument named "{v["lookup"]}".', hint=f'Use a pattern like "api/products/<int:pk>/".')
            return

        view_name = last(dotted(view_node))
        v = self.check_view_ref(view_node, view_name, views, view_funcs, direct_imports)
        if v and v["kind"] not in ("function", "api_function"):
            self.diag("urls.py", view_node, f"TypeError: {view_name}.__init__() takes 1 positional argument but 2 "
                      "were given", hint=f"Class-based views need .as_view(): views.{view_name}.as_view()")
        self.add_route(route, view_name, (v or {}).get("methods", []), el.lineno, el.end_lineno, url_name)
        if v and v["kind"] in ("function", "api_function"):
            url_params = [n for _, n in CONVERTER_RE.findall(route)]
            for p in url_params:
                if p not in v["params"][1:] and not v["has_kwargs"]:
                    self.diag("urls.py", el, f"TypeError: {view_name}() got an unexpected keyword argument '{p}'",
                              hint=f"Add `{p}` as a parameter: def {view_name}(request, {p}):")
            for p in v["required_params"][1:]:
                if p not in url_params:
                    self.diag("urls.py", el, f"TypeError: {view_name}() missing 1 required positional argument: "
                              f"'{p}'", hint=f"Capture it in the route, e.g. \"{route}<int:{p}>/\"")
            if not v["params"]:
                self.diag("views.py", v["line"], f"TypeError: {view_name}() takes 0 positional arguments but 1 was "
                          "given", hint=f"Views receive the request first: def {view_name}(request):")
            if not v["returns"]:
                self.diag("views.py", v["line"], f"ValueError: The view store.views.{view_name} didn't return an "
                          "HttpResponse object. It returned None instead.", hint="return JsonResponse(...)")

    def check_view_ref(self, node, view_name, views, view_funcs, direct_imports, require_viewset=False):
        prefix = dotted(node).rsplit(".", 1)[0] if dotted(node) and "." in dotted(node) else None
        if prefix == "views" or (prefix is None and view_name in direct_imports):
            if "views.py" in self.trees and view_name not in view_funcs:
                self.diag("urls.py", node, f"AttributeError: module 'store.views' has no attribute '{view_name}'",
                          hint=difflib.get_close_matches(view_name or "", list(view_funcs), n=1)
                          and f"Did you mean views.{difflib.get_close_matches(view_name, list(view_funcs), n=1)[0]}?")
                return None
        v = views.get(view_name)
        if v and require_viewset and v["kind"] != "viewset":
            self.diag("urls.py", node, f"{view_name} is not a ViewSet — routers can only register ViewSets.",
                      hint="Inherit from viewsets.ModelViewSet, or use path() instead.")
        return v

    def add_route(self, pattern, view_name, methods, line, end_line, url_name, class_view=False, router=None):
        v = next((x for x in self.views if x["name"] == view_name), None) or {}
        ser = next((s for s in self.serializers if s["name"] == v.get("serializer")), None)
        model_name = v.get("model") or (ser and ser["model"])
        model = next((m for m in self.models if m["name"] == model_name), None)
        r = {
            "pattern": pattern, "path": "/" + pattern.lstrip("/"), "view": view_name, "view_kind": v.get("kind"),
            "methods": list(methods), "url_name": url_name, "line": line, "end_line": end_line,
            "serializer": v.get("serializer"), "model": model_name, "table": model and model["table"],
            "params": [(c, n) for c, n in CONVERTER_RE.findall(pattern)], "class_view": class_view, "router": router,
        }
        self.routes.append(r)
        if not router:
            self.annotate(explain.route(r))

    # -- cross-file checks ---------------------------------------------------------------------

    def check_names(self, file, tree):
        names, star = self.bindings[file]
        if star:
            return
        checker = NameChecker(names)
        checker.visit(tree)
        reported = set()
        for node in checker.missing:
            if (node.id, node.lineno) in reported:
                continue
            reported.add((node.id, node.lineno))
            hint = IMPORT_HINTS.get(node.id)
            if not hint and node.id in {m["name"] for m in self.models} and file != "models.py":
                hint = f"from .models import {node.id}"
            if not hint and node.id in {s["name"] for s in self.serializers} and file != "serializers.py":
                hint = f"from .serializers import {node.id}"
            if not hint:
                close = difflib.get_close_matches(node.id, list(names), n=1)
                hint = close and f"Did you mean `{close[0]}`?"
            if any(d["file"] == file and d["line"] == node.lineno and f"'{node.id}'" in d["message"]
                   for d in self.diagnostics):
                continue
            self.diag(file, node, f"NameError: name '{node.id}' is not defined", hint=hint or None)

    def check_imports(self, file, tree):
        for stmt in tree.body:
            if not isinstance(stmt, (ast.Import, ast.ImportFrom)):
                continue
            names = [a.name for a in stmt.names]
            if isinstance(stmt, ast.ImportFrom):
                module = "." * stmt.level + (stmt.module or "")
                target = f"{stmt.module}.py" if stmt.level == 1 and stmt.module else None
                if target in self.trees:
                    exported = self.bindings[target][0]
                    for alias in stmt.names:
                        if alias.name != "*" and alias.name not in exported:
                            self.diag(file, stmt, f"ImportError: cannot import name '{alias.name}' from "
                                      f"'store.{stmt.module}'",
                                      hint=f"{alias.name} isn't defined in {target} (yet).")
                if stmt.level == 1 and stmt.module is None:
                    for alias in stmt.names:
                        if f"{alias.name}.py" not in self.files:
                            self.diag(file, stmt, f"ImportError: cannot import name '{alias.name}' from 'store'")
                if file == "models.py" and stmt.level == 1 and stmt.module in ("serializers", "views"):
                    self.diag(file, stmt, f"models.py importing {stmt.module} creates a circular import "
                              f"({stmt.module} already imports models).", severity="warning")
            else:
                module = names[0]
            self.annotate(explain.import_line(file, stmt.lineno, stmt.end_lineno, module, names))


def syntax_hint(exc):
    msg = (exc.msg or "").lower()
    if "indent" in msg:
        return "Python groups code by indentation — make sure lines in the same block start in the same column " \
               "(4 spaces per level)."
    if "expected ':'" in msg:
        return "class, def, if, for and with lines must end with a colon."
    if "never closed" in msg or "unexpected eof" in msg or "was not closed" in msg:
        return "A bracket or quote is opened but never closed."
    if "invalid syntax" in msg:
        return "Look at the end of the previous line too — a missing comma or bracket often shows up one line later."
    return None


def analyze(files):
    return Analyzer(files).run()
