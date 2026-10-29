"""Mentor knowledge base: turns analysed code constructs into line-level explanations.

Every function returns an *annotation* dict the editor can show when the learner's
cursor is inside ``line``..``end_line``:

    {file, line, end_line, kind, title, summary, points: [{code, text}],
     why, breaks, quiz: {question, options: [{text, correct, why}]} | None}

The text is written from the facts the analyzer extracted, so it never claims
more than static analysis can know.
"""

FIELD_DOCS = {
    "AutoField": "An auto-incrementing integer primary key.",
    "BigAutoField": "An auto-incrementing 64-bit integer primary key.",
    "CharField": "Short text, stored as `{db_type}`. max_length is checked by validation and sized into the column "
    "(PostgreSQL enforces it; SQLite, used in the sandbox, does not).",
    "SlugField": "A CharField limited to letters, numbers, hyphens and underscores — made for URLs like "
    "/products/trail-runner/. Django indexes it automatically.",
    "TextField": "Unlimited text for long content such as descriptions. Stored as `text`; no max_length needed.",
    "EmailField": "A CharField that validates the value looks like an email address.",
    "URLField": "A CharField that validates the value is a URL.",
    "IntegerField": "A whole number, stored as `integer`.",
    "BigIntegerField": "A 64-bit whole number.",
    "SmallIntegerField": "A small whole number.",
    "PositiveIntegerField": "A whole number that must be >= 0. Django adds a CHECK constraint, so the database "
    "itself refuses negatives — ideal for stock counts.",
    "PositiveSmallIntegerField": "A small whole number that must be >= 0 (CHECK constraint).",
    "PositiveBigIntegerField": "A 64-bit whole number that must be >= 0.",
    "FloatField": "A floating-point number. Fine for ratings, never for money: 0.1 + 0.2 != 0.3 in floating point.",
    "DecimalField": "An exact decimal (Python `Decimal`). This is the field for money because it never rounds "
    "0.10 into 0.1000000001.",
    "BooleanField": "True / False, stored as `bool`.",
    "DateField": "A calendar date (Python `date`).",
    "DateTimeField": "A timestamp (Python `datetime`). With USE_TZ it is stored in UTC.",
    "TimeField": "A time of day.",
    "DurationField": "A length of time (Python `timedelta`).",
    "UUIDField": "A universally unique identifier.",
    "JSONField": "Arbitrary JSON. Flexible, but you lose column-level types and constraints.",
    "FileField": "Stores a file *path*; the file itself lives in storage (disk, S3, ...).",
    "ImageField": "A FileField that validates the upload is an image (needs Pillow).",
    "ForeignKey": "A many-to-one relationship. Each {model} row stores the id of one {target} in the column "
    "`{column}`; one {target} can have many {model} rows.",
    "OneToOneField": "A one-to-one relationship: a ForeignKey whose column is UNIQUE, so each {target} links to "
    "at most one {model}.",
    "ManyToManyField": "A many-to-many relationship. Neither table gets a new column — Django creates the junction "
    "table `{junction}` holding one row per link.",
}

OPTION_DOCS = {
    "max_length": "Maximum number of characters: {value}.",
    "unique": "unique={value} — the database rejects a second row with the same value (IntegrityError), and "
    "serializers check it before saving.",
    "null": "null={value} — controls whether the *database column* may hold NULL.",
    "blank": "blank={value} — controls whether *validation* accepts an empty value. It's separate from null.",
    "default": "default={value} — used when no value is given, and lets a migration fill rows that already exist.",
    "db_index": "db_index={value} — builds a database index so filtering by this column stays fast.",
    "max_digits": "max_digits={value} — total digits allowed on both sides of the decimal point.",
    "decimal_places": "decimal_places={value} — digits stored after the decimal point.",
    "auto_now_add": "auto_now_add={value} — filled with the current time when the row is created, then never changed.",
    "auto_now": "auto_now={value} — refreshed with the current time on every save().",
    "choices": "choices — limits valid values to a fixed list. This is validation only; the column type is unchanged.",
    "primary_key": "primary_key={value} — this field replaces the automatic id as the row's identity.",
    "help_text": "help_text — documentation shown in forms and API docs.",
    "verbose_name": "verbose_name — a human-friendly label.",
    "editable": "editable={value} — False hides the field from forms and makes it read-only in serializers.",
    "through": "through={value} — uses your own model as the junction table, so each link can carry extra data.",
    "db_column": "db_column={value} — overrides the column name.",
    "validators": "validators — extra checks run during validation.",
}

ON_DELETE_DOCS = {
    "CASCADE": "Deleting the {target} also deletes every {model} that points at it.",
    "PROTECT": "Deleting a {target} that still has {model} rows raises ProtectedError — the delete is blocked.",
    "RESTRICT": "Like PROTECT, but the delete is allowed when it happens as part of a CASCADE from elsewhere.",
    "SET_NULL": "Deleting the {target} sets `{column}` to NULL on its {model} rows (needs null=True).",
    "SET_DEFAULT": "Deleting the {target} resets `{column}` to the field's default.",
    "DO_NOTHING": "Django does nothing and leaves it to the database — usually an IntegrityError. Rarely what you want.",
}

ORM_DOCS = {
    "all": "`.all()` — a QuerySet of every row. Lazy: no SQL runs until you iterate it.",
    "filter": "`.filter(...)` — adds a WHERE clause. Still lazy.",
    "exclude": "`.exclude(...)` — adds a negated WHERE clause.",
    "get": "`.get(...)` — runs SQL immediately and returns exactly one object, or raises DoesNotExist / "
    "MultipleObjectsReturned.",
    "create": "`.create(...)` — builds the object and INSERTs it in one step.",
    "select_related": "`.select_related(...)` — follows ForeignKeys with a SQL JOIN, so related objects arrive in "
    "the same query (fixes N+1 for FK access).",
    "prefetch_related": "`.prefetch_related(...)` — loads reverse/many-to-many relations with one extra query per "
    "relation, then joins them in Python.",
    "order_by": "`.order_by(...)` — adds ORDER BY. A leading '-' means descending.",
    "annotate": "`.annotate(...)` — adds a computed value per row (e.g. Count, Sum).",
    "aggregate": "`.aggregate(...)` — computes one summary over the whole QuerySet and returns a dict.",
    "values": "`.values(...)` — returns dicts instead of model instances.",
    "count": "`.count()` — runs SELECT COUNT(*) instead of loading rows.",
    "exists": "`.exists()` — the cheapest way to ask 'is there at least one row?'.",
    "first": "`.first()` — the first row, or None.",
    "update": "`.update(...)` — one UPDATE statement for every matching row; skips save() and signals.",
    "delete": "`.delete()` — deletes the matching rows, applying on_delete rules.",
    "distinct": "`.distinct()` — removes duplicate rows (common after filtering across joins).",
}

GENERIC_DOCS = {
    "ListAPIView": "GET → serializes the queryset with many=True.",
    "CreateAPIView": "POST → validates the body with the serializer, calls save(), returns 201.",
    "ListCreateAPIView": "GET → lists the queryset; POST → validates the body, calls serializer.save() and returns 201.",
    "RetrieveAPIView": "GET /<pk>/ → fetches one object (404 if missing) and serializes it.",
    "UpdateAPIView": "PUT/PATCH /<pk>/ → validates the body against the existing object and saves it.",
    "DestroyAPIView": "DELETE /<pk>/ → deletes the object and returns 204.",
    "RetrieveUpdateAPIView": "GET, PUT and PATCH on one object.",
    "RetrieveDestroyAPIView": "GET and DELETE on one object.",
    "RetrieveUpdateDestroyAPIView": "GET, PUT, PATCH and DELETE on one object, found by the pk in the URL.",
    "ModelViewSet": "Full CRUD in one class: list, create, retrieve, update, partial_update and destroy. "
    "A router turns it into URLs.",
    "ReadOnlyModelViewSet": "list and retrieve only.",
    "GenericAPIView": "The base for generic views: provides get_queryset(), get_serializer() and get_object().",
    "APIView": "DRF's base class view: you write get()/post()/... yourself. Adds parsing, auth, permissions and "
    "exception → response handling.",
}

IMPORT_DOCS = {
    "django.db.models": "Django's ORM toolkit: Model, every Field type, relationship fields and on_delete behaviors.",
    "rest_framework.serializers": "DRF serializers: classes that turn model instances into JSON and validate "
    "incoming JSON.",
    "rest_framework.generics": "Ready-made class views (ListCreateAPIView, ...) that wire a queryset to a serializer.",
    "rest_framework.viewsets": "ViewSets: one class handles every action for a resource; a router builds its URLs.",
    "rest_framework.routers": "Routers generate URL patterns for ViewSets automatically.",
    "rest_framework.response": "`Response` — DRF's response class. It renders data as JSON (or HTML in the browsable API).",
    "rest_framework.decorators": "`@api_view` turns a function into a DRF view that parses JSON and handles errors.",
    "rest_framework.status": "Named HTTP status codes, e.g. status.HTTP_201_CREATED, so code reads clearly.",
    "django.http": "Django's request/response classes. JsonResponse serializes a dict (or list) to JSON.",
    "django.urls": "`path()` maps a URL pattern to a view; `include()` mounts another URL list.",
    "django.shortcuts": "Helpers such as get_object_or_404, which turns DoesNotExist into a 404 response.",
    "django.db": "Database utilities, e.g. `transaction.atomic()` for all-or-nothing changes.",
}


def _ann(file, line, end_line, kind, title, summary, points=None, why=None, breaks=None, quiz=None):
    return {
        "file": file,
        "line": line,
        "end_line": end_line or line,
        "kind": kind,
        "title": title,
        "summary": summary,
        "points": points or [],
        "why": why,
        "breaks": breaks,
        "quiz": quiz,
    }


def _quiz(question, options):
    return {"question": question, "options": [{"text": t, "correct": c, "why": w} for t, c, w in options]}


# --------------------------------------------------------------------------- models


def model(m):
    table = m["table"]
    points = [
        {"code": "models.Model", "text": f"Gives {m['name']} a manager (`{m['name']}.objects`), save()/delete(), "
         f"and a table named `{table}`."},
        {"code": "id", "text": "Django adds an auto-incrementing integer primary key called id unless you declare one."},
    ]
    if m["has_str"]:
        points.append({"code": "__str__", "text": "Controls how a row prints in the admin, the shell and error messages."})
    else:
        points.append({"code": "__str__", "text": f"Tip: add __str__ so rows print as something readable instead "
                       f"of '{m['name']} object (1)'."})
    rels = [f for f in m["fields"] if f.get("relation")]
    if rels:
        points.append({"code": ", ".join(f["name"] for f in rels),
                       "text": "Relationship fields connect this table to others — see the arrows in the ER diagram."})
    return _ann(
        "models.py", m["line"], m["end_line"], "model", f"class {m['name']}(models.Model)",
        f"{m['name']} is a database-backed entity: Django maps the class to the table `{table}`, each attribute that "
        f"is a Field to a column, and each instance to one row.",
        points,
        why="Your store needs durable data that survives restarts and can be queried — models describe that data once, "
            "and Django derives the schema, the ORM and admin forms from them.",
        breaks=f"Deleting the class drops `{table}` — and every row in it — on the next migration.",
    )


def field(m, f, junction=None):
    ftype = f["type"]
    rel = f.get("relation") or {}
    target = rel.get("target", "")
    fmt = {
        "db_type": f.get("db_type"), "model": m["name"], "target": target, "column": f.get("column"),
        "junction": junction or "",
    }
    summary = FIELD_DOCS.get(ftype, f"A {ftype} column.").format(**fmt)
    points = [{"code": f"models.{ftype}", "text": summary}]
    for key, src in f["options"].items():
        if key in ("on_delete", "to"):
            continue
        doc = OPTION_DOCS.get(key)
        if not doc:
            continue
        text = doc.format(value=src)
        if key == "related_name" and target:
            text += f" From a {target} you can write `{target.lower()}.{f['values'].get('related_name')}.all()`."
        points.append({"code": f"{key}={src}", "text": text})
    if rel:
        points.insert(1, {"code": target, "text": f"The related model. Django stores its primary key, not a copy "
                          f"of the {target} data."})
        if rel.get("on_delete"):
            doc = ON_DELETE_DOCS.get(rel["on_delete"], "Custom on_delete behavior.")
            points.append({"code": f"on_delete=models.{rel['on_delete']}", "text": doc.format(**fmt)})
            points.append({"code": "on_delete", "text": "Django enforces on_delete in Python before it runs DELETE — "
                           "the database column itself has no ON DELETE rule."})
        if ftype in ("ForeignKey", "OneToOneField") and not rel.get("related_name"):
            default = m["name"].lower() + ("" if ftype == "OneToOneField" else "_set")
            points.append({"code": "related_name", "text": f"Not set, so the reverse accessor defaults to "
                           f"`{target.lower()}.{default}`."})

    if ftype in ("ForeignKey", "OneToOneField"):
        why = (f"Storing `{f['column']}` instead of copying {target} details keeps one source of truth: rename a "
               f"{target} once and every {m['name']} sees it. The database refuses an id that doesn't exist "
               f"(foreign key constraint), so a {m['name']} can never point at a missing {target}.")
    elif ftype == "ManyToManyField":
        why = f"A {m['name']} can have many {target}s and a {target} many {m['name']}s — a single column can't hold that."
    elif ftype == "DecimalField":
        why = "Prices must add up exactly. Decimal arithmetic matches what an accountant expects."
    else:
        why = None

    if ftype == "ManyToManyField":
        breaks = f"Deleting this line drops the junction table `{junction}` and every link in it."
    elif f.get("column"):
        breaks = f"Deleting this line removes the `{f['column']}` column (and its data) on the next migration."
    else:
        breaks = None

    title = f"{f['name']} = models.{ftype}(...)"
    return _ann("models.py", f["line"], f["end_line"], "field", title, summary, points, why, breaks, _field_quiz(m, f))


def _field_quiz(m, f):
    rel = f.get("relation") or {}
    vals = f.get("values", {})
    target, model_name = rel.get("target", ""), m["name"]
    on_delete = rel.get("on_delete")
    if on_delete == "PROTECT":
        return _quiz(f"What happens if you replace PROTECT with CASCADE?", [
            (f"The {target} can no longer be deleted.", False, "That's what PROTECT already does."),
            (f"Deleting a {target} also deletes its {model_name} rows.", True,
             "CASCADE propagates the delete to every row that references it."),
            (f"The {target} is converted to a string.", False, "on_delete only controls what happens on delete."),
        ])
    if on_delete == "CASCADE":
        return _quiz(f"What would PROTECT do instead of CASCADE here?", [
            (f"Block deleting a {target} while {model_name} rows reference it.", True,
             "PROTECT raises ProtectedError, so nothing is deleted."),
            (f"Delete the {target} and keep orphaned {model_name} rows.", False,
             "The foreign key constraint would reject orphaned rows."),
            ("Nothing — they are aliases.", False, "They are opposite policies."),
        ])
    if f["type"] == "ManyToManyField":
        return _quiz(f"Where is the link between a {model_name} and a {target} stored?", [
            (f"In a `{f['name']}_id` column on the {model_name} table.", False, "One column can only hold one id."),
            ("In a separate junction table with two foreign keys.", True,
             "One row per (model, target) pair — so any number of links."),
            ("In a JSON list on both tables.", False, "Django never denormalizes M2M links."),
        ])
    if vals.get("related_name") and f["type"] == "ForeignKey":
        rn = vals["related_name"]
        return _quiz(f"With related_name=\"{rn}\", how do you list a {target}'s {model_name.lower()}s?", [
            (f"{target.lower()}.{rn}.all()", True, "related_name names the reverse accessor."),
            (f"{target.lower()}.{model_name.lower()}_set.all()", False,
             "That's the default only when related_name isn't set."),
            (f"{model_name}.{f['name']}.all()", False, "That's the forward side, accessed on an instance."),
        ])
    if vals.get("unique") is True:
        return _quiz(f"Two {model_name} rows are saved with the same {f['name']}. What happens?", [
            ("The second save raises IntegrityError.", True, "The UNIQUE constraint lives in the database."),
            ("The second row silently overwrites the first.", False, "Databases never merge rows on their own."),
            ("Django appends '-2' to the value.", False, "Nothing renames values automatically."),
        ])
    if f["type"] == "DecimalField":
        return _quiz("Why DecimalField instead of FloatField for a price?", [
            ("Decimals are exact, floats round (0.1 + 0.2 = 0.30000000000000004).", True,
             "Money needs exact arithmetic."),
            ("FloatField can't store numbers above 1000.", False, "Floats store huge numbers — just inexactly."),
            ("DecimalField is faster.", False, "It's usually slower; correctness is the point."),
        ])
    if f["type"].startswith("Positive"):
        return _quiz(f"What happens if code saves {f['name']}=-1?", [
            ("The database rejects it (CHECK constraint).", True, "Django adds CHECK (column >= 0)."),
            ("It's stored as 1.", False, "Values are never silently changed."),
            ("It's stored as -1; Positive is just a label.", False, "The constraint is real."),
        ])
    if vals.get("auto_now_add") is True:
        return _quiz("When is this timestamp set?", [
            ("Once, when the row is first created.", True, "auto_now_add never updates afterwards."),
            ("On every save().", False, "That's auto_now."),
            ("Only if the client sends it.", False, "The field becomes read-only for clients."),
        ])
    return None


def meta(m, line, end_line):
    meta_ = m["meta"]
    points = []
    if meta_.get("ordering"):
        points.append({"code": f"ordering = {meta_['ordering']}", "text": "Default ORDER BY for every query on this model."})
    for c in meta_.get("constraints", []):
        points.append({"code": f"{c['kind']}({', '.join(c.get('fields') or [])})",
                       "text": "A database constraint: the combination of these columns must be unique." if
                       c["kind"] == "UniqueConstraint" else "A database-level rule every row must satisfy."})
    for idx in meta_.get("indexes", []):
        points.append({"code": f"Index({', '.join(idx.get('fields') or [])})",
                       "text": "Speeds up queries that filter or sort by these columns, at a small write cost."})
    if meta_.get("verbose_name_plural"):
        points.append({"code": "verbose_name_plural", "text": "The plural label used by the admin."})
    if meta_.get("db_table"):
        points.append({"code": "db_table", "text": f"Overrides the table name to `{m['table']}`."})
    return _ann("models.py", line, end_line, "meta", f"class Meta (for {m['name']})",
                "Meta holds model-level options: things that describe the table as a whole, not one column.",
                points, breaks="Constraints and indexes listed here are removed on the next migration if you delete them.")


# ---------------------------------------------------------------------- serializers


def serializer(s):
    model_name = s.get("model") or "a model"
    points = []
    if s["base"] == "ModelSerializer":
        points.append({"code": "ModelSerializer", "text": f"Builds serializer fields from {model_name}'s model fields "
                       "and provides create()/update() for you."})
    else:
        points.append({"code": s["base"], "text": "You declare every field yourself."})
    for f in s.get("effective_fields", []):
        mode = "read-only" if f["read_only"] else "read & write"
        points.append({"code": f["name"], "text": f"{f['describe']} ({mode})."})
    return _ann(
        "serializers.py", s["line"], s["end_line"], "serializer", f"class {s['name']}({s['base']})",
        f"{s['name']} converts {model_name} instances into plain data for JSON responses, and validates incoming "
        "JSON before it becomes a model instance.",
        points,
        why="Never trust client input: the serializer is the gate between raw JSON and your database.",
        breaks="Views that use it fail with NameError/ImportError, and the endpoint can no longer render or validate data.",
        quiz=_quiz(f"Does defining {s['name']} write anything to the database?", [
            ("Yes, as soon as the class exists.", False, "A class definition runs no queries."),
            ("No — code must call serializer.is_valid() and then serializer.save().", True,
             "Generic views do this for you in create(); function views must do it themselves."),
            ("Only for GET requests.", False, "GET only reads; writing happens on save()."),
        ]),
    )


def serializer_meta(s, line, end_line):
    fields = s.get("fields")
    shown = "every model field ('__all__')" if fields == "__all__" else ", ".join(fields or [])
    return _ann("serializers.py", line, end_line, "serializer-meta", f"class Meta (for {s['name']})",
                f"Tells ModelSerializer which model to read ({s.get('model')}) and which fields to expose: {shown}.",
                [
                    {"code": "model", "text": "The model whose fields, validators and create()/update() are generated."},
                    {"code": "fields", "text": "An explicit list is safer than '__all__': new model fields don't leak "
                     "into your API by accident."},
                ],
                breaks="ModelSerializer raises AssertionError without Meta.model and Meta.fields/exclude.")


def declared_field(s, f):
    if f["kind"] == "nested":
        many = " many=True means a list of them." if f["many"] else ""
        summary = f"Nests {f['serializer']} output inside {s['name']}.{many}"
        if f["read_only"]:
            summary += " read_only=True: shown in responses, ignored on input."
    elif f["kind"] == "SerializerMethodField":
        summary = f"A read-only value computed by `get_{f['name']}(self, obj)` each time an object is serialized."
    else:
        summary = f"An explicitly declared {f['kind']}."
        if f.get("source"):
            summary += f" source=\"{f['source']}\" reads the value from obj.{f['source'].replace('.', '.')} — "\
                       "following a relation if it contains a dot."
        if f["read_only"]:
            summary += " read_only=True: output only."
    return _ann("serializers.py", f["line"], f["end_line"], "serializer-field", f"{f['name']} = ...", summary,
                breaks="The key disappears from responses (and the Meta.fields entry raises ImproperlyConfigured).")


def validator(s, name, line, end_line):
    if name == "validate":
        return _ann("serializers.py", line, end_line, "validator", "def validate(self, attrs)",
                    "Object-level validation: runs after every field passed its own checks, with all values in attrs. "
                    "Use it for rules that involve several fields, like quantity <= product.stock.",
                    [{"code": "raise serializers.ValidationError", "text": "Aborts validation; the view responds 400 "
                      "with your message."},
                     {"code": "return attrs", "text": "Must return the (possibly modified) attrs — they become "
                      "validated_data."}],
                    breaks="The rule stops being enforced: invalid combinations reach the database.")
    fname = name[len("validate_"):]
    return _ann("serializers.py", line, end_line, "validator", f"def {name}(self, value)",
                f"Field-level validation for `{fname}`. DRF calls it automatically after `{fname}` passes its type "
                f"checks (e.g. '12.50' was parsed into Decimal).",
                [{"code": "raise serializers.ValidationError(...)", "text": f"Produces a 400 response like "
                  f"{{\"{fname}\": [\"your message\"]}}."},
                 {"code": "return value", "text": "Whatever you return is what gets saved."}],
                why="Business rules (prices are positive) belong at the API boundary, before data is stored.",
                breaks=f"Clients could store invalid `{fname}` values.")


# ---------------------------------------------------------------------------- views


def view(v):
    if v["kind"] in ("function", "api_function"):
        points = [{"code": "request", "text": "Django passes the HttpRequest first; URL parameters arrive as "
                   "keyword arguments."}]
        if v["kind"] == "api_function":
            points.append({"code": "@api_view", "text": f"Makes this a DRF view accepting {', '.join(v['methods'])} — "
                           "it parses JSON into request.data and turns exceptions into JSON errors."})
        if "JsonResponse" in v.get("responses", []):
            points.append({"code": "JsonResponse", "text": "Serializes Python data to JSON and sets "
                           "Content-Type: application/json."})
        if v.get("statuses"):
            points.append({"code": "status=", "text": f"Explicit HTTP status codes: {', '.join(map(str, v['statuses']))}. "
                           "200 is the default."})
        return _ann("views.py", v["line"], v["end_line"], "view", f"def {v['name']}(request, ...)",
                    "A function view: Django calls it for every matching request and expects an HttpResponse back.",
                    points,
                    why="Views hold the 'what should happen for this request' logic between the URL and the data.",
                    breaks="urls.py raises AttributeError: module 'store.views' has no attribute "
                           f"'{v['name']}' — the whole URLconf fails to load.",
                    quiz=_quiz("What happens if the view forgets to return a response?", [
                        ("Django returns an empty 200.", False, "Django never guesses a response."),
                        ("ValueError: the view didn't return an HttpResponse object.", True,
                         "The request fails with a 500 error."),
                        ("The request is retried.", False, "Nothing retries automatically."),
                    ]))
    base = v.get("base") or "APIView"
    points = [{"code": base, "text": GENERIC_DOCS.get(base, "A class-based view.")}]
    if v.get("queryset"):
        points.append({"code": "queryset", "text": f"`{v['queryset']}` — evaluated fresh on every request, never "
                       "cached between requests."})
    if v.get("serializer"):
        points.append({"code": "serializer_class", "text": f"{v['serializer']} renders responses and validates input."})
    quiz = None
    if base in ("ListCreateAPIView", "ModelViewSet"):
        quiz = _quiz(f"A client POSTs invalid JSON to {v['name']}. What does the client receive?", [
            ("400 Bad Request with the serializer's errors.", True, "is_valid(raise_exception=True) inside create()."),
            ("500 Internal Server Error.", False, "Validation errors are expected, not crashes."),
            ("201 Created with null fields.", False, "Nothing is saved when validation fails."),
        ])
    return _ann("views.py", v["line"], v["end_line"], "view", f"class {v['name']}({base})",
                f"{v['name']} handles {', '.join(v['methods']) or 'no'} requests"
                + (f" for {v['model']}." if v.get("model") else "."),
                points,
                why="Generic views remove boilerplate: the same list/create/retrieve logic would otherwise be "
                    "rewritten for every model.",
                breaks="Its URL pattern fails with AttributeError when urls.py is imported.", quiz=quiz)


def orm(chain, file, line, end_line):
    points = [{"code": f"{chain['model']}.objects", "text": f"The manager: your entry point for querying "
               f"{chain['model']} rows."}]
    for call in chain["calls"]:
        doc = ORM_DOCS.get(call["method"])
        if doc:
            points.append({"code": f".{call['method']}()", "text": doc})
    return _ann(file, line, end_line, "orm", chain["text"],
                "A Django ORM query. Python method calls are translated into SQL — watch the Request flow tab to see "
                "the exact SQL when you send a request.", points,
                quiz=_quiz("When does this line actually hit the database?", [
                    ("Immediately, when the line runs.", False, "Only for .get(), .count(), .create() and similar."),
                    ("When the QuerySet is evaluated (iterated, sliced, serialized, len()).", True,
                     "QuerySets are lazy — you can keep chaining filters for free."),
                    ("At the end of the request.", False, "Evaluation happens wherever the data is first needed."),
                ]) if not any(c["method"] in ("get", "create", "count", "exists", "first") for c in chain["calls"]) else None)


# ----------------------------------------------------------------------------- urls


def route(r):
    points = [{"code": f"\"{r['pattern']}\"", "text": "Django compares incoming paths to patterns top to bottom; "
               "the first match wins. No leading slash."}]
    for conv, name in r.get("params", []):
        points.append({"code": f"<{conv}:{name}>" if conv else f"<{name}>",
                       "text": f"Captures part of the URL and passes `{name}=` to the view"
                       + (" as an int (non-digits simply don't match → 404)." if conv == "int" else ".")})
    if r.get("class_view"):
        points.append({"code": ".as_view()", "text": "Class views must be turned into a callable with as_view()."})
    if r.get("url_name"):
        points.append({"code": f"name=\"{r['url_name']}\"", "text": f"Lets code build this URL with "
                       f"reverse(\"{r['url_name']}\") instead of hard-coding it."})
    return _ann("urls.py", r["line"], r["end_line"], "route", f"{', '.join(r['methods'])} {r['path']}",
                f"Routes {r['path']} to {r['view'] or 'a view'}.", points,
                breaks=f"Requests to {r['path']} return 404 — the URL resolver no longer knows it.",
                quiz=_quiz(f"A client requests {r['path'].replace('<int:pk>', 'abc')}. What happens?", [
                    ("404 — no pattern matches.", True, "<int:...> only matches digits, so the resolver keeps looking."),
                    ("The view receives pk='abc'.", False, "The converter rejects it before the view runs."),
                    ("500 error.", False, "No code runs at all."),
                ]) if any(c == "int" for c, _ in r.get("params", [])) else None)


def router(var, line, end_line, registrations):
    points = [{"code": f"{var}.register(\"{reg['prefix']}\", ...)",
               "text": f"Generates /{reg['prefix']}/ (list, create) and /{reg['prefix']}/<pk>/ "
                       "(retrieve, update, destroy)."} for reg in registrations]
    return _ann("urls.py", line, end_line, "router", f"{var} = DefaultRouter()",
                "A router writes URL patterns for ViewSets so you don't have to.", points,
                breaks="Without include(router.urls) the registered routes never reach urlpatterns.")


def import_line(file, node_line, end_line, module, names):
    doc = (IMPORT_DOCS.get(f"{module}.{names[0]}") if names else None) or IMPORT_DOCS.get(module)
    if module.startswith("."):
        doc = f"Imports {', '.join(names)} from your own app's {module.lstrip('.') or 'package'} module."
    if not doc:
        return None
    return _ann(file, node_line, end_line, "import", f"from {module} import {', '.join(names)}", doc,
                breaks="Code that uses these names fails with NameError.")
