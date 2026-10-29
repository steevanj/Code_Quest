import { useEffect, useState } from "react";
import type { CheckRun, Curriculum, Mission, PreviewCheck } from "../types";
import { Rich } from "./MentorPanel";

interface Props {
  curriculum: Curriculum;
  mission: Mission;
  completed: string[];
  preview: PreviewCheck[];
  verified: CheckRun | null;
  checking: boolean;
  onRunChecks: () => void;
  onSelect: (id: string) => void;
  onLoad: (kind: "start" | "solution") => void;
  onJump: (file: string, line: number) => void;
}

export default function MissionPanel(props: Props) {
  const { curriculum, mission, completed, preview, verified, checking, onRunChecks, onSelect, onLoad, onJump } = props;
  const [hints, setHints] = useState(0);
  const [journey, setJourney] = useState(false);
  useEffect(() => setHints(0), [mission.id]);

  const phase = curriculum.phases.find((p) => p.id === mission.phase)!;
  const all = curriculum.phases.flatMap((p) => p.missions);
  const index = all.findIndex((m) => m.id === mission.id);

  return (
    <aside className="mission">
      <button className="journey-toggle" onClick={() => setJourney(!journey)}>
        <span>Phase {phase.id} · {phase.title}</span>
        <span className="muted">{journey ? "▴" : "▾"} {completed.length}/{all.length}</span>
      </button>
      {journey && (
        <div className="journey">
          {curriculum.phases.map((p) => (
            <div key={p.id} className={`journey-phase ${p.locked ? "locked" : ""}`}>
              <div className="journey-phase-title">
                <span>{p.id}. {p.title}</span>
                <span className="level">{p.level}</span>
              </div>
              {p.locked ? (
                <div className="muted small">{p.topics?.join(" · ")}</div>
              ) : (
                p.missions.map((m) => (
                  <button key={m.id} className={`journey-mission ${m.id === mission.id ? "current" : ""}`}
                    onClick={() => { onSelect(m.id); setJourney(false); }}>
                    <span className={`dot ${completed.includes(m.id) ? "done" : ""}`}>{completed.includes(m.id) ? "✓" : ""}</span>
                    {m.title}
                  </button>
                ))
              )}
            </div>
          ))}
        </div>
      )}

      <div className="mission-scroll">
        <div className="mission-kicker">Mission {index + 1} of {all.length}{completed.includes(mission.id) && <span className="done-tag">completed</span>}</div>
        <h2>{mission.title}</h2>
        <p className="goal"><Rich text={mission.goal} /></p>
        <p className="story">{mission.story}</p>
        <div className="concepts">{mission.concepts.map((c) => <span key={c}>{c}</span>)}</div>

        <ol className="steps">
          {mission.steps.map((s, i) => (
            <li key={i}>
              <Rich text={s.text} />
              {s.code && (
                <div className="snippet">
                  <pre>{s.code}</pre>
                  <button className="btn btn-ghost btn-xs" onClick={() => navigator.clipboard?.writeText(s.code!)}>copy</button>
                </div>
              )}
            </li>
          ))}
        </ol>

        <div className="checks">
          <div className="checks-head">
            <span className="lbl">Checks</span>
            <span className="muted small">○ preview from code · ● verified by running it</span>
          </div>
          {mission.checks.map((c, i) => {
            const v = verified?.results.find((r) => r.index === i);
            const p = preview.find((r) => r.index === i);
            const state = v ? (v.passed ? "verified-pass" : "verified-fail") : p ? `preview-${p.status}` : "preview-pending";
            const message = v?.message ?? p?.message;
            return (
              <div key={i} className={`check ${state}`}>
                <span className="check-icon" />
                <div>
                  <div>{c.label}</div>
                  {message && <div className="check-msg">{message}</div>}
                  {v?.error?.location && (
                    <button className="link" onClick={() => onJump(v.error!.location!.file, v.error!.location!.line)}>
                      {v.error.location.file}:{v.error.location.line}
                    </button>
                  )}
                </div>
              </div>
            );
          })}
          {verified?.error && <div className="issue issue-error">{verified.error.type}: {verified.error.message}</div>}
          <button className="btn btn-accent btn-block" onClick={onRunChecks} disabled={checking}>
            {checking ? "Running in sandbox…" : "Run checks"}
          </button>
        </div>

        <div className="help">
          {mission.hints.slice(0, hints).map((h, i) => <div key={i} className="hint-item">💡 <Rich text={h} /></div>)}
          <div className="help-row">
            {hints < mission.hints.length && <button className="btn btn-ghost btn-sm" onClick={() => setHints(hints + 1)}>Hint</button>}
            <button className="btn btn-ghost btn-sm" onClick={() => onLoad("start")}>Reset to mission start</button>
            <button className="btn btn-ghost btn-sm" onClick={() => onLoad("solution")}>Show solution</button>
          </div>
        </div>

        <div className="phase-card">
          <div className="lbl">Phase milestone</div>
          <div>{phase.milestone}</div>
          <div className="muted small">Live visual: {phase.visual}</div>
        </div>
      </div>
    </aside>
  );
}
