import type { Analysis, Snapshot, TableColumn } from "../types";

/** applied: in code and database · pending: code only · changed: differs · dropped: database only */
export type Status = "applied" | "pending" | "changed" | "dropped";

export interface MergedColumn extends TableColumn {
  status: Status;
  appliedType?: string;
}

export interface MergedTable {
  name: string;
  model: string | null;
  kind: "model" | "junction";
  via?: string;
  line?: number;
  status: Status;
  columns: MergedColumn[];
  rowCount?: number;
}

export interface MergedEdge {
  id: string;
  source: string;
  sourceColumn: string;
  target: string;
  targetColumn: string;
  label: string;
  onDelete: string | null;
  kind: string;
  status: Status;
}

/** Combine the code preview (analysis) with the schema the database actually has (snapshot). */
export function mergeSchema(analysis: Analysis | null, snapshot: Snapshot | null) {
  const applied = new Map((snapshot?.tables ?? []).map((t) => [t.name, t]));
  const tables: MergedTable[] = [];
  const edges: MergedEdge[] = [];
  const seen = new Set<string>();

  for (const t of analysis?.tables ?? []) {
    seen.add(t.name);
    const db = applied.get(t.name);
    const dbCols = new Map((db?.columns ?? []).map((c) => [c.name, c]));
    const columns: MergedColumn[] = t.columns.map((c) => {
      const real = dbCols.get(c.name);
      let status: Status = "pending";
      if (real) {
        const same = (real.type ?? "") === (c.type ?? "") && (c.pk || (real.null === c.null && real.unique === c.unique));
        status = same ? "applied" : "changed";
      }
      return { ...c, status, appliedType: real?.type ?? undefined };
    });
    for (const real of db?.columns ?? []) {
      if (!t.columns.some((c) => c.name === real.name)) columns.push({ ...real, status: "dropped" });
    }
    const status: Status = !db ? "pending" : columns.some((c) => c.status !== "applied") ? "changed" : "applied";
    tables.push({ name: t.name, model: t.model, kind: t.kind, via: t.via, line: t.line, columns, status,
      rowCount: db?.count });
  }
  for (const db of snapshot?.tables ?? []) {
    if (seen.has(db.name)) continue;
    tables.push({ name: db.name, model: null, kind: "model", status: "dropped", rowCount: db.count,
      columns: db.columns.map((c) => ({ ...c, status: "dropped" as Status })) });
  }

  for (const e of analysis?.edges ?? []) {
    const real = applied.get(e.source)?.columns.find((c) => c.name === e.source_column);
    edges.push({
      id: e.id, source: e.source, sourceColumn: e.source_column, target: e.target, targetColumn: e.target_column,
      label: e.on_delete && e.kind !== "many-to-many" ? `${e.label} · ${e.on_delete}` : e.label,
      onDelete: e.on_delete, kind: e.kind, status: real?.fk ? "applied" : "pending",
    });
  }
  const pending = tables.reduce(
    (n, t) => n + (t.status === "pending" ? 1 : t.columns.filter((c) => c.status !== "applied").length), 0);
  return { tables, edges, pending };
}
