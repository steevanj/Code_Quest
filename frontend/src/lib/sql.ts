import type { TraceEvent } from "../types";

/** Group SELECTs that differ only in literal values; 3+ of the same shape is an N+1 smell. */
export function detectNPlusOne(trace: TraceEvent[]) {
  const shapes = new Map<string, number>();
  for (const e of trace) {
    if (e.stage !== "sql" || e.verb !== "SELECT") continue;
    const shape = String(e.sql).replace(/'[^']*'/g, "?").replace(/\b\d+\b/g, "?");
    shapes.set(shape, (shapes.get(shape) ?? 0) + 1);
  }
  let worst = 0;
  for (const n of shapes.values()) worst = Math.max(worst, n);
  return worst >= 3 ? worst : 0;
}
