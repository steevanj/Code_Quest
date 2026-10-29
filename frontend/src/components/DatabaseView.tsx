import type { SandboxState } from "../types";

interface Props {
  state: SandboxState | null;
  sql: Record<string, string>;
  busy: boolean;
  onSeed: () => void;
  onReset: () => void;
  onOpenMigration: (name: string) => void;
}

const cell = (v: unknown) => (v === null ? <span className="null">NULL</span> : String(v));

export default function DatabaseView({ state, sql, busy, onSeed, onReset, onOpenMigration }: Props) {
  const schema = state?.schema;
  const migrations = state?.migrations ?? [];
  const applied = new Set(schema?.applied_migrations ?? []);
  return (
    <div className="db">
      <div className="db-bar">
        <span className="muted">sandbox · SQLite · {schema?.tables.length ?? 0} store tables</span>
        <div className="spacer" />
        <button className="btn btn-ghost btn-sm" onClick={onSeed} disabled={busy}>Insert sample data</button>
        <button className="btn btn-danger btn-sm" onClick={onReset} disabled={busy}>Reset database</button>
      </div>

      <section>
        <h4>Migrations</h4>
        {!migrations.length && <p className="muted">None yet. When your models change, click <b>Make migrations</b>.</p>}
        {migrations.map((m) => (
          <details key={m.name} className="migration">
            <summary>
              <span className={applied.has(m.name.replace(/\.py$/, "")) ? "ok" : "warn"}>
                {applied.has(m.name.replace(/\.py$/, "")) ? "✓ applied" : "○ not applied"}
              </span>
              <code>{m.name}</code>
              <button className="btn btn-ghost btn-xs" onClick={(e) => { e.preventDefault(); onOpenMigration(m.name); }}>
                open in editor
              </button>
            </summary>
            {sql[m.name] && (
              <>
                <div className="lbl">SQL Django ran (sqlmigrate)</div>
                <pre className="sql">{sql[m.name]}</pre>
              </>
            )}
            <div className="lbl">Python migration file</div>
            <pre className="sql">{m.content}</pre>
          </details>
        ))}
      </section>

      <section>
        <h4>Tables</h4>
        {!schema?.exists && <p className="muted">No database yet. It's created the first time you migrate.</p>}
        {schema?.tables.map((t) => (
          <div key={t.name} className="db-table">
            <div className="db-table-head">
              <code>{t.name}</code>
              <span className="muted">{t.count} row{t.count === 1 ? "" : "s"}</span>
            </div>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    {t.columns.map((c) => (
                      <th key={c.name} title={`${c.type}${c.null ? " NULL" : " NOT NULL"}${c.fk ? ` → ${c.fk.table}.${c.fk.column}` : ""}`}>
                        {c.pk ? "🔑 " : c.fk ? "↗ " : ""}{c.name}<div className="th-type">{c.type}</div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {t.rows.map((r, i) => (
                    <tr key={i}>{t.columns.map((c) => <td key={c.name}>{cell(r[c.name])}</td>)}</tr>
                  ))}
                  {!t.rows.length && (
                    <tr><td colSpan={t.columns.length} className="muted">empty table</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        ))}
      </section>
    </div>
  );
}
