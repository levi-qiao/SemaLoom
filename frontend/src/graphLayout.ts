import type { ElkPoint, ElkNode } from "elkjs/lib/elk-api";
import { cardinalityMark } from "./labels";
import type { Edge, Node } from "./types";

export type Route = { points: ElkPoint[]; label: ElkPoint; width: number; height: number };
const textWidth = (text: string) => [...text].reduce((width, char) => width + (/[^\x00-\xff]/.test(char) ? 12 : 7), 0);
export const NODE_WIDTH = 240;
export const NODE_HEIGHT = 68;
export const entitySize = (label: string) => ({
  width: NODE_WIDTH,
  height: Math.max(NODE_HEIGHT, Math.ceil(textWidth(label) * 4 / 3 / (NODE_WIDTH - 36)) * 22 + 24),
});
export const relationLabel = (edge: Edge) => `${edge.label} · ${cardinalityMark(edge.cardinality)}`;

export function ensureOrthogonal(points: ElkPoint[]): ElkPoint[] {
  if (points.length < 2) return points;
  const result: ElkPoint[] = [{ x: Math.round(points[0].x), y: Math.round(points[0].y) }];
  for (let i = 1; i < points.length; i++) {
    const prev = result[result.length - 1];
    let currX = Math.round(points[i].x);
    let currY = Math.round(points[i].y);
    if (Math.abs(currX - prev.x) <= 2) {
      currX = prev.x;
    } else if (Math.abs(currY - prev.y) <= 2) {
      currY = prev.y;
    }
    if (prev.x !== currX && prev.y !== currY) {
      const midX = Math.round((prev.x + currX) / 2);
      result.push({ x: midX, y: prev.y });
      result.push({ x: midX, y: currY });
    }
    result.push({ x: currX, y: currY });
  }
  return result;
}

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
      "elk.spacing.nodeNode": "56",
      "elk.layered.spacing.nodeNodeBetweenLayers": "110",
      "elk.spacing.edgeNode": "32",
      "elk.spacing.edgeEdge": "24",
      "elk.layered.spacing.edgeNodeBetweenLayers": "32",
      "elk.layered.spacing.edgeEdgeBetweenLayers": "24",
      "elk.edgeLabels.inline": "true",
      "elk.padding": "[top=48,left=48,bottom=48,right=48]",
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
    const section = edge.sections?.[0];
    const sourcePos = positions.get(edge.sources[0]) ?? { x: 0, y: 0 };
    const targetPos = positions.get(edge.targets[0]) ?? { x: NODE_WIDTH, y: 0 };
    const rawPoints = section
      ? [section.startPoint, ...(section.bendPoints ?? []), section.endPoint]
      : [
          { x: sourcePos.x + NODE_WIDTH, y: sourcePos.y + NODE_HEIGHT / 2 },
          { x: targetPos.x, y: targetPos.y + NODE_HEIGHT / 2 },
        ];
    const points = ensureOrthogonal(rawPoints);
    const label = edge.labels?.[0];
    const labelX = (label?.x !== undefined) ? label.x : (points[0].x + points[points.length - 1].x) / 2 - 30;
    const labelY = (label?.y !== undefined) ? label.y : (points[0].y + points[points.length - 1].y) / 2 - 15;
    const width = label?.width ?? 60;
    const height = label?.height ?? 24;
    routes.set(edge.id, {
      points,
      label: { x: labelX, y: labelY },
      width,
      height,
    });
  }
  return { positions, routes };
}
