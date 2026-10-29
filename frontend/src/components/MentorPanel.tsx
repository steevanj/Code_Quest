import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import type { Annotation, ChangeEvent, Diagnostic, FileName } from "../types";

interface Props {
  file: string;
  line: number;
  annotation: Annotation | null;
  diagnostics: Diagnostic[];
  changes: ChangeEvent[];
  onJump: (file: FileName, line: number) => void;
}

/** Inline `code` spans in mentor text. */
export function Rich({ text }: { text: string }) {
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g);
  return (
    <>
      {parts.map((p, i) =>
        p.startsWith("`") ? <code key={i}>{p.slice(1, -1)}</code> : p.startsWith("**") ? <b key={i}>{p.slice(2, -2)}</b> : p,
      )}
    </>
  );
}

function Quiz({ quiz }: { quiz: NonNullable<Annotation["quiz"]> }) {
  const [picked, setPicked] = useState<number | null>(null);
  useEffect(() => setPicked(null), [quiz.question]);
  return (
    <div className="quiz">
      <div className="quiz-q">Try it: {quiz.question}</div>
      {quiz.options.map((o, i) => {
        const state = picked === null ? "" : o.correct ? "right" : picked === i ? "wrong" : "dim";
        return (
          <button key={i} className={`quiz-opt ${state}`} onClick={() => setPicked(i)} disabled={picked !== null}>
            {o.text}
            {picked !== null && (picked === i || o.correct) && <span className="quiz-why">{o.why}</span>}
          </button>
        );
      })}
    </div>
  );
}

const ICON = { add: "+", remove: "−", change: "~", link: "↔" };

export default function MentorPanel({ file, line, annotation, diagnostics, changes, onJump }: Props) {
  const issues = diagnostics.filter((d) => d.file === file && line >= d.line && line <= Math.max(d.line, d.end_line));
  const main = useRef<HTMLDivElement>(null);
  const key = annotation ? `${annotation.file}:${annotation.line}:${annotation.title}` : "";
  useEffect(() => { main.current?.scrollTo({ top: 0 }); }, [key]);
  return (
    <div className="mentor">
      <div className="mentor-main" ref={main}>
        <div className="mentor-head">
          <span className="mentor-badge">Mentor</span>
          <span className="muted">{file} · line {line}</span>
        </div>
        {issues.map((d, i) => (
          <div key={i} className={`issue issue-${d.severity}`}>
            <div>{d.message}</div>
            {d.hint && <pre className="hint">{d.hint}</pre>}
          </div>
        ))}
        <AnimatePresence mode="wait">
          {annotation ? (
            <motion.div key={`${annotation.file}:${annotation.line}:${annotation.title}`} initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.15 }}>
              <h3 className="mentor-title"><code>{annotation.title}</code></h3>
              <p className="mentor-summary"><Rich text={annotation.summary} /></p>
              {annotation.points.length > 0 && (
                <div className="points">
                  <div className="lbl">What this does</div>
                  {annotation.points.map((p, i) => (
                    <div key={i} className="point"><code>{p.code}</code><span><Rich text={p.text} /></span></div>
                  ))}
                </div>
              )}
              {annotation.why && <div className="why"><div className="lbl">Why it's needed</div><Rich text={annotation.why} /></div>}
              {annotation.breaks && <div className="breaks"><div className="lbl">If you removed it</div><Rich text={annotation.breaks} /></div>}
              {annotation.quiz && <Quiz quiz={annotation.quiz} />}
            </motion.div>
          ) : (
            !issues.length && (
              <motion.p key="idle" className="muted mentor-idle" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
                Click any line marked with an amber bar in the gutter: the Mentor explains what it does, why it's
                there and what would break without it.
              </motion.p>
            )
          )}
        </AnimatePresence>
      </div>
      <div className="mentor-feed">
        <div className="lbl">What changed</div>
        {!changes.length && <p className="muted">Structural changes show up here as you type: new tables, columns, relationships and routes.</p>}
        <AnimatePresence initial={false}>
          {changes.map((c) => (
            <motion.button key={c.id} className={`change change-${c.kind}`} layout initial={{ opacity: 0, x: 12 }}
              animate={{ opacity: 1, x: 0 }} onClick={() => c.line && onJump(c.file, c.line)}>
              <span className="change-icon">{ICON[c.kind]}</span>
              <span><b>{c.text}</b>{c.detail && <span className="change-detail">{c.detail}</span>}</span>
            </motion.button>
          ))}
        </AnimatePresence>
      </div>
    </div>
  );
}
