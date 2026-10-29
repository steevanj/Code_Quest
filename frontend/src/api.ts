import type {
  Analysis,
  CheckRun,
  Curriculum,
  Files,
  MigrateResult,
  RequestResult,
  SandboxState,
  SeedResult,
} from "./types";

async function call<T>(url: string, body?: unknown): Promise<T> {
  const res = await fetch(url, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const data = await res.json();
      detail = data.detail ?? JSON.stringify(data);
    } catch {
      /* keep the status text */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  curriculum: () => call<Curriculum>("/api/missions/"),
  analyze: (files: Files, missionId: string | null) =>
    call<Analysis>("/api/analyze/", { files, mission_id: missionId }),
  state: (session: string) => call<SandboxState>(`/api/sandbox/state/?session=${encodeURIComponent(session)}`),
  migrate: (session: string, files: Files) => call<MigrateResult>("/api/sandbox/migrate/", { session, files }),
  request: (session: string, files: Files, method: string, path: string, body: unknown) =>
    call<RequestResult>("/api/sandbox/request/", { session, files, method, path, body }),
  seed: (session: string, files: Files) => call<SeedResult>("/api/sandbox/seed/", { session, files }),
  reset: (session: string) => call<SandboxState>("/api/sandbox/reset/", { session }),
  check: (missionId: string, session: string, files: Files) =>
    call<CheckRun>(`/api/missions/${missionId}/check/`, { session, files }),
};
