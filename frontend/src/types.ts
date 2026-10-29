// Shapes returned by the Django API (backend/analyzer, backend/missions, backend/runner).

export type FileName = "models.py" | "serializers.py" | "views.py" | "urls.py";
export type Files = Record<FileName, string>;
export const FILE_NAMES: FileName[] = ["models.py", "serializers.py", "views.py", "urls.py"];

export interface Diagnostic {
  file: FileName;
  line: number;
  col: number;
  end_line: number;
  end_col: number | null;
  severity: "error" | "warning" | "info";
  message: string;
  hint: string | null;
}

export interface QuizOption {
  text: string;
  correct: boolean;
  why: string;
}

export interface Annotation {
  file: FileName;
  line: number;
  end_line: number;
  kind: string;
  title: string;
  summary: string;
  points: { code: string; text: string }[];
  why: string | null;
  breaks: string | null;
  quiz: { question: string; options: QuizOption[] } | null;
}

export interface Relation {
  kind: "many-to-one" | "one-to-one" | "many-to-many";
  target: string;
  on_delete: string | null;
  related_name: string | null;
}

export interface ModelField {
  name: string;
  type: string;
  line: number;
  column: string | null;
  db_type: string | null;
  primary_key: boolean;
  unique: boolean;
  null: boolean;
  implicit: boolean;
  relation: Relation | null;
  constraints: string[];
  values: Record<string, unknown>;
}

export interface ModelInfo {
  name: string;
  table: string;
  line: number;
  end_line: number;
  fields: ModelField[];
}

export interface TableColumn {
  name: string;
  type: string | null;
  pk: boolean;
  unique: boolean;
  null: boolean;
  field?: string | null;
  field_type?: string;
  line?: number;
  implicit?: boolean;
  fk: { table: string; column: string } | null;
  constraints?: string[];
  index?: boolean;
}

export interface TableInfo {
  name: string;
  model: string | null;
  kind: "model" | "junction";
  via?: string;
  line: number;
  columns: TableColumn[];
}

export interface EdgeInfo {
  id: string;
  source: string;
  source_column: string;
  target: string;
  target_column: string;
  kind: string;
  on_delete: string | null;
  field: string;
  label: string;
}

export interface SerializerInfo {
  name: string;
  line: number;
  base: string;
  model: string | null;
  effective_fields?: { name: string; read_only: boolean; describe: string }[];
}

export interface ViewInfo {
  name: string;
  kind: "function" | "api_function" | "apiview" | "generic" | "viewset";
  base: string | null;
  methods: string[];
  line: number;
  serializer: string | null;
  model: string | null;
  queryset: string | null;
}

export interface RouteInfo {
  pattern: string;
  path: string;
  view: string | null;
  view_kind: string | null;
  methods: string[];
  url_name: string | null;
  line: number;
  serializer: string | null;
  model: string | null;
  table: string | null;
  router: string | null;
}

export interface PreviewCheck {
  index: number;
  label: string;
  status: "pass" | "fail" | "pending";
  message: string;
}

export interface Analysis {
  ok: boolean;
  diagnostics: Diagnostic[];
  models: ModelInfo[];
  tables: TableInfo[];
  edges: EdgeInfo[];
  serializers: SerializerInfo[];
  views: ViewInfo[];
  routes: RouteInfo[];
  annotations: Annotation[];
  summary: Record<string, number>;
  checks?: PreviewCheck[];
}

export interface MissionRequest {
  label: string;
  method: string;
  path: string;
  body?: unknown;
}

export interface Mission {
  id: string;
  phase: number;
  title: string;
  goal: string;
  story: string;
  concepts: string[];
  focus: FileName;
  steps: { text: string; code?: string }[];
  hints: string[];
  requests: MissionRequest[];
  checks: { type: string; label: string }[];
  solution: Files;
  start: Files;
}

export interface Phase {
  id: number;
  title: string;
  level: string;
  build: string;
  visual: string;
  milestone: string;
  locked?: boolean;
  topics?: string[];
  missions: Mission[];
}

export interface Curriculum {
  initial: Files;
  phases: Phase[];
}

export interface SnapshotTable {
  name: string;
  columns: TableColumn[];
  rows: Record<string, unknown>[];
  count: number;
}

export interface Snapshot {
  exists: boolean;
  tables: SnapshotTable[];
  applied_migrations: string[];
}

export interface SandboxState {
  schema: Snapshot;
  migrations: { name: string; content: string }[];
}

export interface RunError {
  type: string;
  message: string;
  location: { file: string; line: number; code?: string } | null;
  traceback?: string;
}

export interface TraceEvent {
  stage: "request" | "url" | "view" | "serializer" | "sql" | "response";
  [key: string]: any; // eslint-disable-line @typescript-eslint/no-explicit-any
}

export interface RequestResult extends SandboxState {
  ok: boolean;
  trace: TraceEvent[];
  error: RunError | null;
  duration_ms?: number;
  query_count?: number;
  logs?: string;
  failed_stage?: string;
}

export interface MigrateResult extends SandboxState {
  ok: boolean;
  stage: string;
  created?: string[];
  sql?: Record<string, string>;
  output?: string;
  error?: RunError;
}

export interface CheckResult {
  index: number;
  label: string;
  passed: boolean;
  message: string;
  error: RunError | null;
}

export interface CheckRun {
  ok: boolean;
  passed: boolean;
  results: CheckResult[];
  error?: RunError;
  stage?: string;
}

export interface SeedResult extends SandboxState {
  ok: boolean;
  created: string[];
  skipped: string[];
  error?: RunError;
}

export interface Highlight {
  file: string;
  line: number;
  endLine?: number;
  tone: "flow" | "error";
}

export interface ChangeEvent {
  id: string;
  kind: "add" | "remove" | "change" | "link";
  text: string;
  detail?: string;
  file: FileName;
  line?: number;
  at: number;
}
