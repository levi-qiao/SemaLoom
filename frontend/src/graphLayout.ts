import type { ElkPoint, ElkNode } from "elkjs/lib/elk-api";
import { cardinalityMark } from "./labels";
import type { Edge, Node } from "./types";

export type Route = { points: ElkPoint[]; label: ElkPoint; width: number; height: number };
// Match the fixed UI font and padding; reserve space for both labels and nodes in ELK.
const textWidth = (text: string) => [...text].reduce((width, char) => width + (/[^\x00-\xff]/.test(char) ? 12 : 7), 0);
export const entitySize = (label: string) => ({ width: 200, height: Math.max(64, Math.ceil(textWidth(label) * 4 / 3 / 168) * 22 + 24) });
export const relationLabel = (edge: Edge) => `${edge.label} · ${cardinalityMark(edge.cardinality)}`;

export async function layoutGraph(nodes: Node[], edges: Edge[], direction: "RIGHT" | "DOWN" = "RIGHT") {
  const { default: ELK } = await import("elkjs/lib/elk.bundled.js");
  const elk = new ELK();
  const ids = new Set(nodes.map(node => node.id));
  const result = await elk.layout<ElkNode>({
    id: "root",
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": direction,
      "elk.edgeRouting": "ORTHOGONAL",
      "elk.spacing.nodeNode": "64",
      "elk.layered.spacing.nodeNodeBetweenLayers": "100",
      "elk.spacing.edgeNode": "28",
      "elk.spacing.edgeEdge": "24",
      "elk.layered.spacing.edgeNodeBetweenLayers": "28",
      "elk.layered.spacing.edgeEdgeBetweenLayers": "24",
      "elk.edgeLabels.inline": "true",
      "elk.padding": "[top=40,left=40,bottom=40,right=40]",
    },
    children: nodes.map(node => ({ id: node.id, ...entitySize(node.label) })),
    edges: edges.filter(edge => ids.has(edge.source) && ids.has(edge.target)).map(edge => ({
      id: edge.id, sources: [edge.source], targets: [edge.target],
      labels: [{ text: relationLabel(edge), width: textWidth(relationLabel(edge)) + 24, height: 30 }],
    })),
  });
  const positions = new Map((result.children ?? []).map(node => [node.id, { x: node.x ?? 0, y: node.y ?? 0 }]));
  const routes = new Map<string, Route>();
  for (const edge of result.edges ?? []) {
    const section = edge.sections?.[0], label = edge.labels?.[0];
    if (!section || !label || label.x === undefined || label.y === undefined) throw new Error("Incomplete graph layout");
    routes.set(edge.id, {
      points: [section.startPoint, ...(section.bendPoints ?? []), section.endPoint],
      label: { x: label.x, y: label.y }, width: label.width!, height: label.height!,
    });
  }
  return { positions, routes };
}
