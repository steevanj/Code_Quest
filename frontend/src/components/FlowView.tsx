import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useMemo, useRef, useState } from "react";
import { detectNPlusOne } from "../lib/sql";
import type { Analysis, MissionRequest, RequestResult, RouteInfo, TraceEvent } from "../types";

interface Props {
  analysis: Analysis | null;
  presets: MissionRequest[];
  result: RequestResult | null;
  sending: boolean;
  draft: MissionRequest;
  onDraft: (r: MissionRequest) => void;
  onSend: (r: MissionRequest) => void;
  onFocus: (event: TraceEvent | null) => void;
}

const NODES = [
  { id: "client", label: "Client", icon: "◉" },
  { id: "url", label: "URL resolver", icon: "⌥" },
  { id: "view", label: "View", icon: "ƒ" },
  { id: "serializer", label: "Serializer", icon: "⇄" },
  { id: "orm", label: "ORM → SQL", icon: "⛁" },
  { id: "response", label: "Response", icon: "↩" },
] as const;
type NodeId = (typeof NODES)[number]["id"];

const nodeFor = (e: TraceEvent): NodeId =>
  e.stage === "request" ? "client" : e.stage === "sql" ? "orm" : (e.stage as NodeId);

const METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"];

export function routeForPath(routes: RouteInfo[], path: string) {
  const clean = path.split("?")[0];
  return routes.find((r) => {
    const rx = r.pattern
      .replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
      .replace(/<(?:(\w+):)?(\w+)>/g, (_m, conv) => (conv === "int" ? "\\d+" : "[^/]+"));
    return new RegExp(`^/${rx}$`).test(clean);
  });
}

const examplePath = (r: RouteInfo) => r.path.replace(/<(?:\w+:)?\w+>/g, "1");

function statusTone(status?: number) {
  if (!status) return "muted";
  if (status < 300) return "ok";
  if (status < 400) return "warn";
  return "bad";
}

function Json({ value }: { value: unknown }) {
  const text = JSON.stringify(value, null, 2) ?? "null";
  return <pre className="json">{text.length > 2400 ? `${text.slice(0, 2400)}\n…` : text}</pre>;
}

function EventCard({ e, onFocus }: { e: TraceEvent; onFocus: () => void }) {
  let title: React.ReactNode = e.stage;
  let body: React.ReactNode = null;
  let note = "";
  let tone = "";
  switch (e.stage) {
    case "request":
      title = <><b>{e.method}</b> {e.path}</>;
      body = e.body !== null && e.body !== undefined && e.method !== "GET" ? <Json value={e.body} /> : null;
      note = "The test client builds an HttpRequest, exactly like a browser or mobile app would send.";
      break;
    case "url":
      if (e.matched) {
        title = <>Matched <code>{e.route || "(router)"}</code>{e.url_name && <span className="muted"> · name="{e.url_name}"</span>}</>;
        body = Object.keys(e.kwargs ?? {}).length ? <div className="kv">kwargs: <code>{JSON.stringify(e.kwargs)}</code></div> : null;
        note = "Django compared the path with urlpatterns top to bottom and stopped at the first match.";
      } else {
        tone = "bad";
        title = <>No URL pattern matched</>;
        body = <div className="kv">Tried: {(e.tried ?? []).map((t: string) => <code key={t}>{t}</code>)}</div>;
        note = "No view runs at all — Django answers 404 by itself.";
      }
      break;
    case "view":
      title = <>{e.name} <span className="muted">{e.kind === "function" ? "function view" : e.bases?.[0] ?? e.kind}</span></>;
      body = (
        <div className="kv">
          {e.actions && <>actions: <code>{JSON.stringify(e.actions)}</code> </>}
          {e.serializer && <>serializer: <code>{e.serializer}</code> </>}
          {e.model && <>model: <code>{e.model}</code></>}
        </div>
      );
      note = "The view decides what this request means and which data to read or write.";
      break;
    case "serializer":
      if (e.action === "validate") {
        tone = e.valid ? "ok" : "bad";
        title = <>{e.serializer}.is_valid() → {e.valid ? "valid ✓" : "invalid ✗"}</>;
        body = <div className="two-col"><div><div className="lbl">input</div><Json value={e.input} /></div>
          <div><div className="lbl">{e.valid ? "validated_data" : "errors"}</div><Json value={e.valid ? e.validated_data : e.errors} /></div></div>;
        note = e.valid ? "Every field passed type checks and your validators." : "Validation failed, so nothing is written — the view answers 400.";
      } else if (e.action === "save") {
        title = <>{e.serializer}.save() → {e.operation} {e.model ?? ""} {e.pk !== undefined && e.pk !== null ? `#${e.pk}` : ""}</>;
        note = "save() calls create()/update(), which runs the INSERT/UPDATE below.";
      } else {
        title = <>{e.serializer} → JSON{e.items !== null && e.items !== undefined ? ` (${e.items} item${e.items === 1 ? "" : "s"})` : ""}</>;
        body = <Json value={e.output} />;
        note = "Model instances become plain dicts and lists, ready to render as JSON.";
      }
      break;
    case "sql":
      tone = e.error ? "bad" : "";
      title = <><span className={`verb verb-${e.verb}`}>{e.verb}</span> <span className="muted">{e.ms} ms</span></>;
      body = <><pre className="sql">{e.sql}</pre>{e.error && <div className="err-line">{e.error}</div>}</>;
      break;
    case "response":
      tone = statusTone(e.status);
      title = <><span className={`status-pill tone-${tone}`}>{e.status} {e.reason}</span>{e.location && <span className="muted"> → {e.location}</span>}</>;
      body = e.body_kind === "json" ? <Json value={e.body} /> : e.body ? <pre className="json">{String(e.body)}</pre> : null;
      break;
  }
  return (
    <motion.div className={`event ev-${e.stage} tone-${tone}`} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
      onClick={onFocus}>
      <div className="event-title">{title}</div>
      {body}
      {note && <div className="event-note">{note}</div>}
    </motion.div>
  );
}

export default function FlowView({ analysis, presets, result, sending, draft, onDraft, onSend, onFocus }: Props) {
  const [step, setStep] = useState(0);
  const [bodyText, setBodyText] = useState(() => (draft.body !== undefined ? JSON.stringify(draft.body, null, 2) : ""));
  const [bodyError, setBodyError] = useState<string | null>(null);
  const trace = useMemo(() => result?.trace ?? [], [result]);
  const routes = analysis?.routes ?? [];
  const route = routeForPath(routes, draft.path);

  useEffect(() => setBodyText(draft.body !== undefined ? JSON.stringify(draft.body, null, 2) : ""), [draft.body]);

  // Replay the traced lifecycle one stage at a time, moving the editor highlight along.
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const stop = () => {
    if (timer.current) clearInterval(timer.current);
    timer.current = null;
  };
  const play = () => {
    stop();
    setStep(0);
    let i = 0;
    timer.current = setInterval(() => {
      i += 1;
      setStep(i);
      if (i >= trace.length) stop();
    }, trace.length > 12 ? 160 : 380);
  };
  useEffect(() => {
    if (trace.length) play();
    return stop;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trace]);

  useEffect(() => {
    if (!trace.length) return;
    onFocus(step < trace.length ? trace[step] : null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, trace]);

  const visible = trace.slice(0, step + 1);
  const visited = new Set(visible.map(nodeFor));
  const active = step < trace.length ? nodeFor(trace[step]) : null;
  const sqlCount = visible.filter((e) => e.stage === "sql").length;
  const response = trace.find((e) => e.stage === "response");
  const nPlusOne = step >= trace.length ? detectNPlusOne(trace) : 0;
  const errorNode: NodeId | null = result?.error ? nodeFor(trace.filter((e) => e.stage !== "response").slice(-1)[0] ?? trace[0]) : null;

  const subtitle = (id: NodeId): string => {
    const ev = [...visible].reverse().find((e) => nodeFor(e) === id);
    if (trace.length && ev) {
      if (id === "client") return `${ev.method} ${ev.path}`;
      if (id === "url") return ev.matched ? ev.route || "router" : "no match";
      if (id === "view") return ev.name;
      if (id === "serializer") return ev.serializer;
      if (id === "orm") return `${sqlCount} quer${sqlCount === 1 ? "y" : "ies"}`;
      if (id === "response") return `${ev.status}`;
    }
    if (trace.length) return id === "serializer" ? "not used" : "";
    if (id === "client") return `${draft.method} ${draft.path}`;
    if (id === "url") return route ? route.pattern : "no match yet";
    if (id === "view") return route?.view ?? "—";
    if (id === "serializer") return route?.serializer ?? "not used";
    if (id === "orm") return route?.table ?? (route?.model ? route.model : "—");
    return "";
  };
  const unused = (id: NodeId) => (trace.length ? step >= trace.length && !visited.has(id) : id === "serializer" ? !route?.serializer : !route && id !== "client");

  const send = () => {
    let body: unknown = undefined;
    if (draft.method !== "GET" && draft.method !== "DELETE" && bodyText.trim()) {
      try {
        body = JSON.parse(bodyText);
      } catch {
        setBodyError("Body isn't valid JSON.");
        return;
      }
    }
    setBodyError(null);
    onSend({ ...draft, body });
  };

  return (
    <div className="flow">
      <div className="composer">
        <select value={draft.method} onChange={(e) => onDraft({ ...draft, method: e.target.value })}>
          {METHODS.map((m) => <option key={m}>{m}</option>)}
        </select>
        <input value={draft.path} spellCheck={false} onChange={(e) => onDraft({ ...draft, path: e.target.value })}
          onKeyDown={(e) => e.key === "Enter" && send()} />
        <button className="btn btn-accent" onClick={send} disabled={sending}>{sending ? "Running…" : "Send ▸"}</button>
      </div>
      {draft.method !== "GET" && draft.method !== "DELETE" && (
        <textarea className="body-input" rows={3} spellCheck={false} placeholder='{"name": "Shoes", "slug": "shoes"}'
          value={bodyText} onChange={(e) => setBodyText(e.target.value)} />
      )}
      {bodyError && <div className="err-line">{bodyError}</div>}
      <div className="presets">
        {presets.map((p) => (
          <button key={p.label} className="chip" onClick={() => onDraft({ ...p })}>{p.method} · {p.label}</button>
        ))}
        {routes.filter((r) => !presets.some((p) => routeForPath([r], p.path))).slice(0, 6).map((r) => (
          <button key={r.pattern} className="chip chip-ghost" onClick={() => onDraft({ label: r.path, method: "GET", path: examplePath(r) })}>
            {examplePath(r)}
          </button>
        ))}
      </div>

      <div className="pipeline">
        {NODES.map((n, i) => (
          <div key={n.id} className="pipe-wrap">
            <motion.div
              className={`pipe-node ${visited.has(n.id) && trace.length ? "lit" : ""} ${active === n.id ? "active" : ""} ${unused(n.id) ? "unused" : ""} ${errorNode === n.id && step >= trace.length ? "errored" : ""}`}
              animate={active === n.id ? { scale: [1, 1.07, 1] } : { scale: 1 }}
              transition={{ duration: 0.45 }}
            >
              <div className="pipe-icon">{n.icon}</div>
              <div className="pipe-label">{n.label}</div>
              <div className="pipe-sub">{subtitle(n.id)}</div>
            </motion.div>
            {i < NODES.length - 1 && <div className={`pipe-link ${visited.has(NODES[i + 1].id) && trace.length ? "lit" : ""}`} />}
          </div>
        ))}
      </div>
      {!trace.length && (
        <p className="flow-hint">
          {route
            ? <>Static preview: <code>{draft.path}</code> should reach <b>{route.view}</b>{route.serializer ? <> via <b>{route.serializer}</b></> : null}. Send it to see what really happens.</>
            : <>No route in urls.py matches <code>{draft.path}</code> yet — sending it will show Django's 404.</>}
        </p>
      )}

      {trace.length > 0 && (
        <div className="trace-stats">
          {response && <span className={`status-pill tone-${statusTone(response.status)}`}>{response.status}</span>}
          <span>{result?.duration_ms ?? "–"} ms</span>
          <span>{result?.query_count ?? 0} SQL quer{result?.query_count === 1 ? "y" : "ies"}</span>
          <span className="verified">● verified in sandbox</span>
          <button className="btn btn-ghost btn-sm" onClick={() => { stop(); setStep(trace.length); }}>Skip</button>
          <button className="btn btn-ghost btn-sm" onClick={play}>Replay</button>
        </div>
      )}
      {nPlusOne > 0 && (
        <div className="callout callout-warn">
          <b>N+1 detected:</b> the same SELECT ran {nPlusOne} times with different ids — one per row. Use{" "}
          <code>select_related()</code> (ForeignKey) or <code>prefetch_related()</code> (many) to load them together.
        </div>
      )}
      <div className="timeline">
        <AnimatePresence>
          {visible.map((e, i) => <EventCard key={i} e={e} onFocus={() => onFocus(e)} />)}
        </AnimatePresence>
        {result?.error && step >= trace.length && (
          <motion.div className="event tone-bad ev-error" initial={{ opacity: 0 }} animate={{ opacity: 1 }}
            onClick={() => onFocus({ stage: "response", error: result.error })}>
            <div className="event-title">💥 {result.error.type}: {result.error.message}</div>
            {result.error.location && (
              <div className="kv">at <code>{result.error.location.file}:{result.error.location.line}</code>{" "}
                {result.error.location.code && <code>{result.error.location.code}</code>}</div>
            )}
            <div className="event-note">An unhandled exception becomes a 500 Internal Server Error. Click to jump to the line.</div>
            {result.error.traceback && <details><summary>Traceback</summary><pre className="sql">{result.error.traceback}</pre></details>}
          </motion.div>
        )}
        {result?.logs && step >= trace.length && (
          <details className="logs"><summary>print() output</summary><pre className="sql">{result.logs}</pre></details>
        )}
      </div>
    </div>
  );
}
