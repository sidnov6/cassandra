"use client";
import { ReactFlow, Background, Handle, Position, type Node, type Edge, type NodeProps } from "@xyflow/react";
import { useMemo } from "react";

export type NodeStatus = "idle" | "running" | "done" | "flagged";

const LABEL: Record<string, string> = {
  router: "Router", revenue: "Revenue", accruals: "Accruals", cashflow: "Cash-Flow",
  benford: "Benford", governance: "Governance", language: "Language", collector: "Collector",
  challenger: "Challenger", analogue: "Analogue", synthesis: "Synthesis",
};
const POS: Record<string, { x: number; y: number }> = {
  router: { x: 270, y: 0 },
  revenue: { x: 0, y: 92 }, accruals: { x: 110, y: 92 }, cashflow: { x: 220, y: 92 },
  benford: { x: 330, y: 92 }, governance: { x: 440, y: 92 }, language: { x: 550, y: 92 },
  collector: { x: 270, y: 190 }, challenger: { x: 270, y: 280 },
  analogue: { x: 270, y: 368 }, synthesis: { x: 270, y: 456 },
};
const SPECIALISTS = ["revenue", "accruals", "cashflow", "benford", "governance", "language"];

function StageNode({ data }: NodeProps) {
  const d = data as { label: string; status: NodeStatus; sub?: string };
  return (
    <div className={`rf-node ${d.status}`}>
      <Handle type="target" position={Position.Top} />
      <div className="text-[11px] font-medium">{d.label}</div>
      <div className="text-[9px] mt-0.5" style={{ color: "var(--muted)" }}>{d.sub ?? d.status}</div>
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}

const nodeTypes = { stage: StageNode };

export function AgentGraph({ states }: { states: Record<string, NodeStatus> }) {
  const nodes: Node[] = useMemo(
    () =>
      Object.keys(POS).map((id) => ({
        id, type: "stage", position: POS[id], draggable: false,
        data: { label: LABEL[id], status: states[id] ?? "idle" },
      })),
    [states]
  );
  const edges: Edge[] = useMemo(() => {
    const e: Edge[] = [];
    SPECIALISTS.forEach((s) => {
      e.push({ id: `r-${s}`, source: "router", target: s });
      e.push({ id: `${s}-c`, source: s, target: "collector" });
    });
    e.push({ id: "c-ch", source: "collector", target: "challenger" });
    e.push({ id: "ch-an", source: "challenger", target: "analogue" });
    e.push({ id: "an-sy", source: "analogue", target: "synthesis" });
    return e;
  }, []);

  return (
    <div style={{ height: 540 }}>
      <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView
        nodesDraggable={false} nodesConnectable={false} elementsSelectable={false}
        panOnDrag={false} zoomOnScroll={false} proOptions={{ hideAttribution: true }}>
        <Background color="#1c1a14" gap={22} size={1} />
      </ReactFlow>
    </div>
  );
}
