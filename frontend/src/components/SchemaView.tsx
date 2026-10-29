import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
  type ReactFlowInstance,
  useNodesState,
} from "@xyflow/react";
import { motion } from "framer-motion";
import { useEffect, useMemo, useRef } from "react";
import { mergeSchema, type MergedTable } from "../lib/schema";
import type { Analysis, Snapshot } from "../types";

interface Props {
  analysis: Analysis | null;
  snapshot: Snapshot | null;
  onJump: (line: number) => void;
  onMigrate: () => void;
  migrating: boolean;
}

type TableNodeData = { table: MergedTable; onJump: (line: number) => void };

const STATUS_LABEL = { applied: "applied", pending: "preview", changed: "changed", dropped: "dropped" };

function TableNode({ data }: NodeProps<Node<TableNodeData>>) {
  const { table, onJump } = data;
  return (
    <motion.div
      className={`er-table status-${table.status} ${table.kind === "junction" ? "junction" : ""}`}
      initial={{ opacity: 0, scale: 0.85, y: 8 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 260, damping: 22 }}
    >
      <div className="er-head" onClick={() => table.line && onJump(table.line)} title="Jump to code">
        <span className="er-name">{table.model ?? table.name}</span>
        <span className={`er-badge badge-${table.status}`}>{STATUS_LABEL[table.status]}</span>
      </div>
      <div className="er-sub">
        {table.kind === "junction" ? `junction for ${table.via}` : table.name}
        {table.rowCount !== undefined && <span className="er-rows">{table.rowCount} rows</span>}
      </div>
      {table.columns.map((c) => (
        <motion.div
          key={c.name}
          layout
          className={`er-col col-${c.status}`}
          initial={{ opacity: 0, x: -6 }}
          animate={{ opacity: 1, x: 0 }}
          onClick={() => c.line && onJump(c.line)}
          title={c.constraints?.join(" · ")}
        >
          <Handle type="target" position={Position.Left} id={`${c.name}-t`} className="er-handle" />
          <span className="er-key">{c.pk ? "PK" : c.fk ? "FK" : ""}</span>
          <span className="er-colname">{c.name}</span>
          <span className="er-type">
            {c.status === "changed" && c.appliedType && c.appliedType !== c.type ? (
              <>
                <s>{c.appliedType}</s> {c.type}
              </>
            ) : (
              c.type
            )}
          </span>
          <span className="er-flags">
            {c.unique && !c.pk && <i title="UNIQUE">U</i>}
            {c.null && <i title="NULL allowed">∅</i>}
          </span>
          <Handle type="source" position={Position.Right} id={`${c.name}-s`} className="er-handle" />
        </motion.div>
      ))}
    </motion.div>
  );
}

const nodeTypes = { table: TableNode };

function layout(tables: MergedTable[]) {
  const byName = new Map(tables.map((t) => [t.name, t]));
  const depth = new Map<string, number>();
  const visit = (name: string, stack: Set<string>): number => {
    if (depth.has(name)) return depth.get(name)!;
    if (stack.has(name)) return 0;
    stack.add(name);
    const t = byName.get(name);
    const targets = (t?.columns ?? []).map((c) => c.fk?.table).filter((x): x is string => !!x && x !== name);
    const d = targets.length ? 1 + Math.max(...targets.map((x) => (byName.has(x) ? visit(x, stack) : 0))) : 0;
    depth.set(name, d);
    return d;
  };
  tables.forEach((t) => visit(t.name, new Set()));
  const columnY = new Map<number, number>();
  const positions = new Map<string, { x: number; y: number }>();
  for (const t of tables) {
    const d = depth.get(t.name) ?? 0;
    const y = columnY.get(d) ?? 20;
    positions.set(t.name, { x: 20 + d * 330, y });
    columnY.set(d, y + 70 + t.columns.length * 27 + 40);
  }
  return positions;
}

export default function SchemaView({ analysis, snapshot, onJump, onMigrate, migrating }: Props) {
  const merged = useMemo(() => mergeSchema(analysis, snapshot), [analysis, snapshot]);
  const dragged = useRef(new Map<string, { x: number; y: number }>());
  const [nodes, setNodes, onNodesChange] = useNodesState<Node<TableNodeData>>([]);
  const flow = useRef<ReactFlowInstance<Node<TableNodeData>> | null>(null);
  const tableKey = merged.tables.map((t) => t.name).join(",");

  // Re-frame the diagram whenever a table appears or disappears.
  useEffect(() => {
    const t = setTimeout(() => flow.current?.fitView({ padding: 0.2, maxZoom: 1.1, duration: 400 }), 80);
    return () => clearTimeout(t);
  }, [tableKey]);

  useEffect(() => {
    const auto = layout(merged.tables);
    setNodes(
      merged.tables.map((t) => ({
        id: t.name,
        type: "table",
        position: dragged.current.get(t.name) ?? auto.get(t.name)!,
        data: { table: t, onJump },
      })),
    );
  }, [merged, onJump, setNodes]);

  const edges: Edge[] = useMemo(
    () =>
      merged.edges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        sourceHandle: `${e.sourceColumn}-s`,
        targetHandle: `${e.targetColumn}-t`,
        label: e.label,
        type: "smoothstep",
        animated: e.status !== "applied",
        className: `er-edge edge-${e.status} ${e.onDelete === "CASCADE" ? "edge-cascade" : ""}`,
        markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
        labelBgPadding: [6, 3] as [number, number],
        labelBgBorderRadius: 4,
      })),
    [merged.edges],
  );

  if (!merged.tables.length) {
    return (
      <div className="empty">
        <div className="empty-icon">▦</div>
        <h3>No models yet</h3>
        <p>
          Write <code>class Category(models.Model):</code> in <b>models.py</b> and watch its table appear here as you
          type.
        </p>
      </div>
    );
  }

  return (
    <div className="schema">
      <div className="schema-bar">
        <div className="legend">
          <span className="lg lg-pending">preview (code only)</span>
          <span className="lg lg-applied">applied (in database)</span>
          <span className="lg lg-changed">changed</span>
          <span className="lg lg-dropped">dropped on migrate</span>
        </div>
        {merged.pending > 0 ? (
          <button className="btn btn-accent btn-sm" onClick={onMigrate} disabled={migrating}>
            {migrating ? "Migrating…" : `Apply ${merged.pending} pending change${merged.pending > 1 ? "s" : ""}`}
          </button>
        ) : (
          <span className="in-sync">✓ Code and database in sync</span>
        )}
      </div>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onNodeDragStop={(_, node) => dragged.current.set(node.id, node.position)}
        onInit={(instance) => { flow.current = instance; }}
        fitView
        fitViewOptions={{ padding: 0.2, maxZoom: 1.1 }}
        minZoom={0.3}
        proOptions={{ hideAttribution: true }}
        colorMode="dark"
      >
        <Background gap={22} size={1} color="#1f2733" />
        <Controls showInteractive={false} />
      </ReactFlow>
      <p className="caveat">
        Column types are what Django declares on SQLite (the sandbox database). PostgreSQL types differ, e.g.
        <code> numeric(10, 2)</code> for DecimalField.
      </p>
    </div>
  );
}
