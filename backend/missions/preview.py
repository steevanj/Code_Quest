"""Evaluate mission checks against static analysis — instant, but only a preview.

Each result is {"status": "pass" | "fail" | "pending", "message"}. Behavior checks
(HTTP requests, migrations) can only be *pending* here; the sandbox verifies them.
"""
from analyzer.engine import match_route

FIELD_KEYS = {
    "type": lambda f: f["type"],
    "to": lambda f: (f.get("relation") or {}).get("target"),
    "on_delete": lambda f: (f.get("relation") or {}).get("on_delete"),
    "related_name": lambda f: (f.get("relation") or {}).get("related_name"),
}


def _model(check, analysis):
    model = next((m for m in analysis["models"] if m["name"] == check["model"]), None)
    if not model:
        return "fail", f"No model named {check['model']} yet."
    fields = {f["name"]: f for f in model["fields"]}
    for name, spec in check.get("fields", {}).items():
        f = fields.get(name)
        if not f:
            return "fail", f"{check['model']}.{name} is missing."
        for key, want in spec.items():
            got = FIELD_KEYS[key](f) if key in FIELD_KEYS else f["values"].get(key)
            if got != want:
                return "fail", f"{check['model']}.{name}: expected {key}={want!r}, found {got!r}."
    return "pass", "Matches in your code — verify by running checks."


def _unique_together(check, analysis):
    model = next((m for m in analysis["models"] if m["name"] == check["model"]), None)
    if not model:
        return "fail", f"No model named {check['model']} yet."
    groups = [set(c.get("fields") or []) for c in model["meta"]["constraints"] if c["kind"] == "UniqueConstraint"]
    groups += [set(u) for u in model["meta"]["unique_together"]]
    if set(check["fields"]) in groups:
        return "pass", "Constraint found in Meta."
    return "fail", f"No unique constraint on ({', '.join(check['fields'])}) yet."


def _serializer(check, analysis):
    ser = next((s for s in analysis["serializers"] if s["name"] == check["serializer"]), None)
    if not ser:
        return "fail", f"No serializer named {check['serializer']} yet."
    if check.get("model") and ser["model"] != check["model"]:
        return "fail", f"{ser['name']}.Meta.model should be {check['model']}."
    names = {f["name"] for f in ser.get("effective_fields", [])}
    missing = [f for f in check.get("fields", []) if f not in names]
    if missing:
        return "fail", f"Missing fields: {', '.join(missing)}."
    return "pass", "Serializer looks right — verify by running checks."


def _request(check, analysis):
    path = check["path"].replace("@", "")
    path = "/".join("1" if part and not part.isalpha() and part[0].isalpha() and part[1:].isdigit() else part
                    for part in path.split("/"))
    route = match_route(analysis["routes"], check["method"], path)
    if not route:
        if check["expect"].get("status") == 404:
            return "pending", "No route matches — that's a 404, but run checks to confirm."
        return "fail", f"No URL pattern matches {check['method']} {check['path']}."
    if route.get("method_not_allowed"):
        return "fail", f"{route['path']} exists but {route['view']} doesn't accept {check['method']}."
    return "pending", f"Route found → {route['view']}. Run checks to verify the response."


HANDLERS = {"model": _model, "unique_together": _unique_together, "serializer": _serializer, "request": _request}


def preview_checks(checks, analysis):
    results = []
    for i, check in enumerate(checks):
        handler = HANDLERS.get(check["type"])
        if analysis["summary"]["errors"] and check["type"] != "model":
            status, message = "pending", "Fix the errors in the editor first."
        elif handler:
            status, message = handler(check, analysis)
        else:
            status, message = "pending", "Verified by the sandbox when you run checks."
        results.append({"index": i, "label": check["label"], "status": status, "message": message})
    return results
