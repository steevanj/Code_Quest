import type { Analysis, ChangeEvent, ModelField } from "../types";

let counter = 0;
const ev = (e: Omit<ChangeEvent, "id" | "at">): ChangeEvent => ({ ...e, id: `c${++counter}`, at: Date.now() });

const columnText = (f: ModelField) =>
  f.column ? `${f.column} ${f.db_type ?? ""} ${f.constraints.filter((c) => c !== "NOT NULL").join(" ")}`.trim() : "";

function relationText(model: string, table: string, f: ModelField) {
  const rel = f.relation!;
  if (rel.kind === "many-to-many") return `Many-to-many: junction table ${table}_${f.name} will hold the links.`;
  const kind = rel.kind === "one-to-one" ? "One-to-one" : "Many-to-one";
  const onDelete = rel.on_delete ? `; on delete: ${rel.on_delete}` : "";
  return `${kind}: ${model}.${f.column} stores the ${rel.target} id${onDelete}.`;
}

/** What changed structurally between two successful analyses, phrased for the learner. */
export function diffAnalyses(prev: Analysis, next: Analysis): ChangeEvent[] {
  const out: ChangeEvent[] = [];
  const prevModels = new Map(prev.models.map((m) => [m.name, m]));
  const nextNames = new Set(next.models.map((m) => m.name));

  for (const m of next.models) {
    const old = prevModels.get(m.name);
    if (!old) {
      out.push(ev({ kind: "add", file: "models.py", line: m.line, text: `New model ${m.name}`,
        detail: `Previews table ${m.table}. It becomes real when you run Make migrations.` }));
      continue;
    }
    const oldFields = new Map(old.fields.map((f) => [f.name, f]));
    for (const f of m.fields) {
      const o = oldFields.get(f.name);
      if (!o) {
        out.push(f.relation
          ? ev({ kind: "link", file: "models.py", line: f.line, text: `${m.name}.${f.name} links ${m.name} → ${f.relation.target}`,
              detail: relationText(m.name, m.table, f) })
          : ev({ kind: "add", file: "models.py", line: f.line, text: `Field ${m.name}.${f.name} added`,
              detail: `New column: ${columnText(f)}` }));
      } else if (o.db_type !== f.db_type || o.constraints.join() !== f.constraints.join()) {
        out.push(ev({ kind: "change", file: "models.py", line: f.line, text: `${m.name}.${f.name} changed`,
          detail: `${columnText(o)}  →  ${columnText(f)}` }));
      }
    }
    for (const o of old.fields) {
      if (!m.fields.some((f) => f.name === o.name)) {
        out.push(ev({ kind: "remove", file: "models.py", line: m.line, text: `Field ${m.name}.${o.name} removed`,
          detail: o.column ? `Migrating will drop column ${o.column} and its data.` : undefined }));
      }
    }
  }
  for (const m of prev.models) {
    if (!nextNames.has(m.name)) {
      out.push(ev({ kind: "remove", file: "models.py", text: `Model ${m.name} removed`,
        detail: `Migrating will drop table ${m.table} and every row in it.` }));
    }
  }

  const prevSer = new Set(prev.serializers.map((s) => s.name));
  for (const s of next.serializers) {
    if (!prevSer.has(s.name)) {
      out.push(ev({ kind: "add", file: "serializers.py", line: s.line, text: `Serializer ${s.name}`,
        detail: s.model ? `Converts ${s.model} to and from JSON, and validates input.` : undefined }));
    }
  }
  const prevViews = new Set(prev.views.map((v) => v.name));
  for (const v of next.views) {
    if (!prevViews.has(v.name)) {
      out.push(ev({ kind: "add", file: "views.py", line: v.line, text: `View ${v.name}`,
        detail: v.base ? `${v.base} · ${v.methods.join(", ")}` : "Function view" }));
    }
  }
  const prevRoutes = new Set(prev.routes.map((r) => r.pattern));
  for (const r of next.routes) {
    if (!prevRoutes.has(r.pattern)) {
      const chain = [r.view ?? "?", r.serializer, r.table].filter(Boolean).join(" → ");
      out.push(ev({ kind: "link", file: "urls.py", line: r.line, text: `Route ${r.path}`, detail: `→ ${chain}` }));
    }
  }
  return out;
}

export const hasSyntaxError = (a: Analysis) =>
  a.diagnostics.some((d) => /^(SyntaxError|IndentationError|TabError)/.test(d.message));
