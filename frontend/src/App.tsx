import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import CodeEditor from "./components/CodeEditor";
import DatabaseView from "./components/DatabaseView";
import FlowView, { routeForPath } from "./components/FlowView";
import MentorPanel from "./components/MentorPanel";
import MissionPanel from "./components/MissionPanel";
import SchemaView from "./components/SchemaView";
import StorePreview from "./components/StorePreview";
import { diffAnalyses, hasSyntaxError } from "./lib/changes";
import { mergeSchema } from "./lib/schema";
import { load, save, sessionId } from "./lib/storage";
import type {
  Analysis,
  Annotation,
  ChangeEvent,
  CheckRun,
  Curriculum,
  FileName,
  Files,
  Highlight,
  MissionRequest,
  RequestResult,
  SandboxState,
  TraceEvent,
} from "./types";
import { FILE_NAMES } from "./types";

type Tab = "schema" | "flow" | "store" | "db";
type Toast = { tone: "ok" | "bad" | "info"; text: string; detail?: string };

const DEFAULT_REQUEST: MissionRequest = { label: "List products", method: "GET", path: "/api/products/" };

function pickAnnotation(annotations: Annotation[], file: string, line: number) {
  const hits = annotations.filter((a) => a.file === file && line >= a.line && line <= a.end_line);
  hits.sort((a, b) => a.end_line - a.line - (b.end_line - b.line));
  return hits[0] ?? null;
}

export default function App() {
  const session = useMemo(sessionId, []);
  const [curriculum, setCurriculum] = useState<Curriculum | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [missionId, setMissionId] = useState<string | null>(() => load("mission", null));
  const [files, setFiles] = useState<Files | null>(() => load("files", null));
  const [completed, setCompleted] = useState<string[]>(() => load("completed", []));
  const [activeFile, setActiveFile] = useState<string>("models.py");
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [good, setGood] = useState<Analysis | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [changes, setChanges] = useState<ChangeEvent[]>([]);
  const [sandbox, setSandbox] = useState<SandboxState | null>(null);
  const [sql, setSql] = useState<Record<string, string>>(() => load("sql", {}));
  const [result, setResult] = useState<RequestResult | null>(null);
  const [verified, setVerified] = useState<CheckRun | null>(null);
  const [busy, setBusy] = useState<null | "migrate" | "request" | "check" | "seed" | "reset">(null);
  const [tab, setTab] = useState<Tab>("schema");
  const [cursor, setCursor] = useState<{ file: string; line: number }>({ file: "models.py", line: 1 });
  const [highlight, setHighlight] = useState<Highlight | null>(null);
  const [draft, setDraft] = useState<MissionRequest>(DEFAULT_REQUEST);
  const [toast, setToast] = useState<Toast | null>(null);
  const [celebrate, setCelebrate] = useState(false);
  const [apiProducts, setApiProducts] = useState<Record<string, unknown>[] | null>(null);
  const cartId = useRef<number | null>(null);

  const missions = useMemo(() => curriculum?.phases.flatMap((p) => p.missions) ?? [], [curriculum]);
  const mission = missions.find((m) => m.id === missionId) ?? missions[0] ?? null;

  // ---- boot ---------------------------------------------------------------------
  useEffect(() => {
    api.curriculum().then((c) => {
      setCurriculum(c);
      setFiles((f) => f ?? { ...c.initial });
      const first = c.phases[0].missions[0];
      setMissionId((id) => id ?? first.id);
    }).catch((e) => setLoadError(String(e.message ?? e)));
    api.state(session).then(setSandbox).catch(() => undefined);
  }, [session]);

  useEffect(() => { if (files) save("files", files); }, [files]);
  useEffect(() => save("mission", missionId), [missionId]);
  useEffect(() => save("completed", completed), [completed]);
  useEffect(() => save("sql", sql), [sql]);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), toast.tone === "bad" ? 9000 : 5000);
    return () => clearTimeout(t);
  }, [toast]);

  // ---- live analysis while typing -------------------------------------------------
  const goodRef = useRef<Analysis | null>(null);
  useEffect(() => {
    if (!files) return;
    setAnalyzing(true);
    const timer = setTimeout(() => {
      api.analyze(files, mission?.id ?? null).then((a) => {
        setAnalysis(a);
        if (!hasSyntaxError(a)) {
          if (goodRef.current) {
            const diff = diffAnalyses(goodRef.current, a);
            if (diff.length) setChanges((c) => [...diff.reverse(), ...c].slice(0, 14));
          }
          goodRef.current = a;
          setGood(a);
        }
      }).catch(() => undefined).finally(() => setAnalyzing(false));
    }, 350);
    return () => clearTimeout(timer);
  }, [files, mission?.id]);

  // ---- helpers ------------------------------------------------------------------
  const applySandbox = (s: SandboxState) => setSandbox({ schema: s.schema, migrations: s.migrations });

  const jump = useCallback((file: string, line: number) => {
    setActiveFile(file);
    setHighlight({ file: file as FileName, line, tone: "flow" });
    setCursor({ file, line });
  }, []);
  const jumpModels = useCallback((line: number) => jump("models.py", line), [jump]);

  const showError = (prefix: string, err: { type: string; message: string; location: { file: string; line: number } | null }) => {
    setToast({ tone: "bad", text: `${prefix}: ${err.type}`, detail: err.message });
    if (err.location) {
      setActiveFile(err.location.file);
      setHighlight({ file: err.location.file as FileName, line: err.location.line, tone: "error" });
      setCursor({ file: err.location.file, line: err.location.line });
    }
  };

  const failNetwork = (e: unknown) =>
    setToast({ tone: "bad", text: "Couldn't reach the Backend Forge API", detail: String((e as Error).message ?? e) });

  // ---- actions --------------------------------------------------------------------
  const migrate = async (source: Files | null = files) => {
    if (!source) return;
    setBusy("migrate");
    try {
      const r = await api.migrate(session, source);
      applySandbox(r);
      if (r.sql) setSql((s) => ({ ...s, ...r.sql }));
      if (!r.ok && r.error) showError(r.stage === "makemigrations" ? "makemigrations failed" : "migrate failed", r.error);
      else if (r.created?.length) {
        setToast({ tone: "ok", text: `Created ${r.created.join(", ")} and applied it`, detail: "The preview tables are now real. See the SQL in the Database tab." });
        setTab("schema");
      } else setToast({ tone: "info", text: "No changes detected", detail: "Your database already matches your models." });
    } catch (e) { failNetwork(e); } finally { setBusy(null); }
  };

  const send = async (r: MissionRequest) => {
    if (!files) return null;
    setDraft(r);
    setBusy("request");
    setTab("flow");
    try {
      const res = await api.request(session, files, r.method, r.path, r.body ?? null);
      setResult(res);
      applySandbox(res);
      const response = res.trace.find((e) => e.stage === "response");
      if (r.method === "GET" && /^\/api\/products\/?$/.test(r.path) && Array.isArray(response?.body)) setApiProducts(response!.body);
      return res;
    } catch (e) { failNetwork(e); return null; } finally { setBusy(null); }
  };

  const runChecks = async () => {
    if (!files || !mission) return;
    setBusy("check");
    try {
      const r = await api.check(mission.id, session, files);
      setVerified(r);
      if (r.passed) {
        if (!completed.includes(mission.id)) setCompleted((c) => [...c, mission.id]);
        setCelebrate(true);
      } else if (r.error) showError("Checks couldn't run", r.error);
    } catch (e) { failNetwork(e); } finally { setBusy(null); }
  };

  const seed = async () => {
    if (!files) return;
    setBusy("seed");
    try {
      const r = await api.seed(session, files);
      applySandbox(r);
      if (!r.ok && r.error) setToast({ tone: "bad", text: "Couldn't insert sample data", detail: r.error.message });
      else setToast({ tone: r.created.length ? "ok" : "info", text: r.created.length ? `Inserted ${r.created.length} rows` : "Nothing new to insert",
        detail: r.skipped.length ? `Skipped: ${r.skipped.join(", ")}` : r.created.slice(0, 6).join(", ") });
    } catch (e) { failNetwork(e); } finally { setBusy(null); }
  };

  const reset = async (ask = true) => {
    if (ask && !window.confirm("Delete your sandbox database and migrations?")) return;
    setBusy("reset");
    try {
      applySandbox(await api.reset(session));
      setResult(null);
      setSql({});
      setApiProducts(null);
      cartId.current = null;
    } catch (e) { failNetwork(e); } finally { setBusy(null); }
  };

  const loadCode = async (kind: "start" | "solution") => {
    if (!mission) return;
    const msg = kind === "start"
      ? "Replace your code with this mission's starting code? Your database will be rebuilt to match."
      : "Replace your code with the reference solution? Your database will be rebuilt to match.";
    if (!window.confirm(msg)) return;
    const next = { ...(kind === "start" ? mission.start : mission.solution) };
    setFiles(next);
    setVerified(null);
    await reset(false);
    if (/class \w+\(models\.Model\)/.test(next["models.py"])) await migrate(next);
  };

  const selectMission = (id: string) => {
    const m = missions.find((x) => x.id === id);
    if (!m) return;
    setMissionId(id);
    setVerified(null);
    setActiveFile(m.focus);
    setDraft(m.requests[0] ? { ...m.requests[0] } : DEFAULT_REQUEST);
  };

  const addToCart = async (productId: number) => {
    if (!cartId.current) {
      const created = await send({ label: "Create cart", method: "POST", path: "/api/carts/", body: {} });
      const body = created?.trace.find((e) => e.stage === "response")?.body;
      if (!body?.id) { setToast({ tone: "bad", text: "POST /api/carts/ didn't return a cart id" }); return; }
      cartId.current = body.id;
    }
    const res = await send({ label: "Add item", method: "POST", path: "/api/cart-items/", body: { cart: cartId.current, product: productId, quantity: 1 } });
    const response = res?.trace.find((e) => e.stage === "response");
    if (response?.status === 201) setToast({ tone: "ok", text: "Added to cart", detail: `Your API answered 201 for cart #${cartId.current}.` });
    else if (response) setToast({ tone: "bad", text: `Your API answered ${response.status}`, detail: JSON.stringify(response.body) });
    setTab("store");
  };

  // Map the traced stage being animated to the code that ran it.
  const focusTrace = useCallback((e: TraceEvent | null) => {
    const a = goodRef.current;
    if (!e) {
      const loc = result?.error?.location;
      if (loc) setHighlight({ file: loc.file as FileName, line: loc.line, tone: "error" });
      if (loc) setActiveFile(loc.file);
      return;
    }
    let h: Highlight | null = null;
    if (e.error?.location) h = { file: e.error.location.file, line: e.error.location.line, tone: "error" };
    else if (e.stage === "view" && e.location) h = { file: e.location.file, line: e.location.line, endLine: e.location.end_line, tone: "flow" };
    else if (e.stage === "url" && e.matched && a) {
      const r = a.routes.find((x) => (e.url_name && x.url_name === e.url_name) || x.pattern === e.route);
      if (r) h = { file: "urls.py", line: r.line, tone: "flow" };
    } else if (e.stage === "serializer" && a) {
      const s = a.serializers.find((x) => x.name === String(e.serializer).replace("(many=True)", ""));
      if (s) h = { file: "serializers.py", line: s.line, tone: "flow" };
    }
    if (h) { setHighlight(h); setActiveFile(h.file); }
  }, [result]);

  // ---- derived ------------------------------------------------------------------------
  const visual = good ?? analysis;
  const pending = useMemo(() => mergeSchema(visual, sandbox?.schema ?? null).pending, [visual, sandbox]);
  const annotation = analysis ? pickAnnotation(analysis.annotations, cursor.file, cursor.line) : null;
  const migrationFiles = Object.fromEntries((sandbox?.migrations ?? []).map((m) => [`migrations/${m.name}`, m.content]));
  const errorsByFile = (f: FileName) => analysis?.diagnostics.filter((d) => d.file === f && d.severity === "error").length ?? 0;
  const errorCount = analysis?.summary.errors ?? 0;
  const routes = visual?.routes ?? [];
  const canFetch = !!routeForPath(routes, "/api/products/");
  const canAddToCart = !!routeForPath(routes, "/api/cart-items/") && !!routeForPath(routes, "/api/carts/");
  const nextMission = mission ? missions[missions.findIndex((m) => m.id === mission.id) + 1] : undefined;

  if (loadError) {
    return (
      <div className="boot">
        <h1>◆ Backend Forge</h1>
        <p>Couldn't load the curriculum from the Django API.</p>
        <pre>{loadError}</pre>
        <p className="muted">Start the backend: <code>cd backend && .venv\Scripts\python manage.py runserver</code></p>
      </div>
    );
  }
  if (!curriculum || !files || !mission) return <div className="boot"><h1>◆ Backend Forge</h1><p className="muted">Loading…</p></div>;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand"><span className="logo">◆</span> Backend Forge</div>
        <div className="top-mission">
          <span className="muted">Phase {mission.phase}</span>
          <span className="sep">/</span>
          <span>{mission.title}</span>
        </div>
        <div className="progress" title={`${completed.length} of ${missions.length} missions complete`}>
          <div className="progress-fill" style={{ width: `${(completed.length / missions.length) * 100}%` }} />
        </div>
        <div className="spacer" />
        <button className="btn btn-ghost" onClick={() => migrate()} disabled={!!busy}>
          {busy === "migrate" ? "Migrating…" : "⛁ Make migrations"}{pending > 0 && busy !== "migrate" && <span className="count">{pending}</span>}
        </button>
        <button className="btn btn-accent" onClick={runChecks} disabled={!!busy}>
          {busy === "check" ? "Checking…" : "▶ Run checks"}
        </button>
      </header>

      <main className="main">
        <MissionPanel curriculum={curriculum} mission={mission} completed={completed} preview={analysis?.checks ?? []}
          verified={verified} checking={busy === "check"} onRunChecks={runChecks} onSelect={selectMission}
          onLoad={loadCode} onJump={jump} />

        <section className="center">
          <div className="file-tabs">
            {FILE_NAMES.map((f) => (
              <button key={f} className={`file-tab ${activeFile === f ? "on" : ""}`} onClick={() => setActiveFile(f)}>
                {f}{errorsByFile(f) > 0 && <span className="err-dot">{errorsByFile(f)}</span>}
                {mission.focus === f && <span className="focus-dot" title="This mission's main file" />}
              </button>
            ))}
            {Object.keys(migrationFiles).map((f) => (
              <button key={f} className={`file-tab mig ${activeFile === f ? "on" : ""}`} onClick={() => setActiveFile(f)}>
                {f.replace("migrations/", "")}
              </button>
            ))}
          </div>
          <CodeEditor files={files} active={activeFile} readOnlyFiles={migrationFiles}
            diagnostics={analysis?.diagnostics ?? []} annotations={analysis?.annotations ?? []} highlight={highlight}
            onChange={(f, text) => { setFiles((cur) => ({ ...cur!, [f]: text })); setVerified(null); if (highlight?.tone === "error") setHighlight(null); }}
            onCursor={(file, line) => setCursor({ file, line })} />
          <MentorPanel file={cursor.file} line={cursor.line} annotation={annotation}
            diagnostics={analysis?.diagnostics ?? []} changes={changes} onJump={jump} />
        </section>

        <section className="viz">
          <nav className="viz-tabs">
            {([["schema", "Schema", pending], ["flow", "Request flow", 0], ["store", "Store", 0], ["db", "Database", 0]] as const).map(([id, label, badge]) => (
              <button key={id} className={`viz-tab ${tab === id ? "on" : ""}`} onClick={() => setTab(id)}>
                {label}{badge > 0 && <span className="count">{badge}</span>}
              </button>
            ))}
          </nav>
          <div className="viz-body">
            {tab === "schema" && <SchemaView analysis={visual} snapshot={sandbox?.schema ?? null} onJump={jumpModels}
              onMigrate={() => migrate()} migrating={busy === "migrate"} />}
            {tab === "flow" && <FlowView analysis={visual} presets={mission.requests} result={result} sending={busy === "request"}
              draft={draft} onDraft={setDraft} onSend={send} onFocus={focusTrace} />}
            {tab === "store" && <StorePreview snapshot={sandbox?.schema ?? null} apiProducts={apiProducts} canFetch={canFetch}
              canAddToCart={canAddToCart} busy={!!busy} onSeed={seed} onAddToCart={addToCart}
              onFetch={async () => { await send({ label: "List products", method: "GET", path: "/api/products/" }); setTab("store"); }} />}
            {tab === "db" && <DatabaseView state={sandbox} sql={sql} busy={!!busy} onSeed={seed} onReset={() => reset()}
              onOpenMigration={(name) => setActiveFile(`migrations/${name}`)} />}
          </div>
        </section>
      </main>

      <footer className="statusbar">
        <span className={errorCount ? "bad" : "ok"}>
          {analyzing ? "◌ analyzing…" : errorCount ? `● ${errorCount} error${errorCount > 1 ? "s" : ""}` : "● code analyzed"}
        </span>
        <span>{visual?.summary.models ?? 0} models · {visual?.summary.relations ?? 0} relations · {visual?.summary.routes ?? 0} routes</span>
        <span>{sandbox?.schema.applied_migrations.length ?? 0} migrations applied</span>
        <div className="spacer" />
        <span className="muted">Preview = inferred from code · Verified = executed in the sandbox</span>
      </footer>

      <AnimatePresence>
        {toast && (
          <motion.div key="toast" className={`toast toast-${toast.tone}`} initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 20 }} onClick={() => setToast(null)}>
            <b>{toast.text}</b>
            {toast.detail && <div className="toast-detail">{toast.detail}</div>}
          </motion.div>
        )}
        {celebrate && (
          <motion.div key="celebrate" className="overlay" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <motion.div className="celebrate" initial={{ scale: 0.8, y: 20 }} animate={{ scale: 1, y: 0 }}
              transition={{ type: "spring", stiffness: 220, damping: 16 }}>
              <div className="celebrate-icon">✦</div>
              <h2>Mission complete</h2>
              <p><b>{mission.title}</b>: every check passed, verified by running your code.</p>
              <div className="celebrate-checks">
                {verified?.results.map((r) => <div key={r.index}>✓ {r.label}</div>)}
              </div>
              <div className="help-row">
                <button className="btn btn-ghost" onClick={() => setCelebrate(false)}>Keep exploring</button>
                {nextMission && (
                  <button className="btn btn-accent" onClick={() => { setCelebrate(false); selectMission(nextMission.id); }}>
                    Next: {nextMission.title} →
                  </button>
                )}
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
