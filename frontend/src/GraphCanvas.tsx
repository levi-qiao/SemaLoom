import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  BackgroundVariant,
  BaseEdge,
  ConnectionMode,
  Controls,
  EdgeLabelRenderer,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  ReactFlowProvider,
  applyNodeChanges,
  getSmoothStepPath,
  ConnectionLineType,
  useInternalNode,
  useNodesInitialized,
  useReactFlow,
  type Connection,
  type Edge as FlowEdge,
  type EdgeProps,
  type FinalConnectionState,
  type Node as FlowNode,
  type NodeChange,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { namespaceLabel } from "./labels";
import type { Edge, Node } from "./types";

type Props = {
  nodes: Node[];
  edges: Edge[];
  selected: string | null;
  selectedEdge: string | null;
  onSelect: (id: string) => void;
  onSelectEdge: (id: string) => void;
  onCreate: () => void;
  canEdit: boolean;
  onLink: (source: string, target: string) => void;
  onOpenFull?: (id: string) => void;
  namespaces: string[];
  relations: { id: string; label: string }[];
  namespaceFilter: string;
  relationFilter: string;
  onNamespaceFilter: (value: string) => void;
  onRelationFilter: (value: string) => void;
};

import { entitySize, layoutGraph, relationLabel, type Route } from "./graphLayout";

type EntityData = { label: string };
type Placed = FlowNode<EntityData>;

const nodeTypes = { entity: EntityNode };
const edgeTypes = { entity: RoutedEdge };

export function GraphCanvas(props: Props) {
  return (
    <div className="graph-canvas">
      <div className="graph-toolbar">
        <label className="graph-filter">
          <span className="sr-only">领域</span>
          <select aria-label="领域" value={props.namespaceFilter} onChange={(event) => props.onNamespaceFilter(event.target.value)}>
            <option value="">全部领域</option>
            {props.namespaces.map((item) => <option key={item} value={item}>{namespaceLabel(item)}</option>)}
          </select>
        </label>
        <label className="graph-filter">
          <span className="sr-only">关系</span>
          <select aria-label="关系" value={props.relationFilter} onChange={(event) => props.onRelationFilter(event.target.value)}>
            <option value="">全部关系</option>
            {props.relations.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
          </select>
        </label>

        <span>{props.nodes.length} 个实体 · {props.edges.length} 条关系 · 从连接点拖到另一实体连线</span>
      </div>
      <div className="graph-flow">
        <ReactFlowProvider>
          <FlowBoard {...props} />
        </ReactFlowProvider>
      </div>
    </div>
  );
}

function FlowBoard({
  nodes,
  edges,
  selected,
  selectedEdge,
  onSelect,
  onSelectEdge,
  onLink,
  onOpenFull,
  onCreate,
  canEdit,
}: Props) {
  const { screenToFlowPosition, fitView } = useReactFlow();
  const canvasRef = useRef<HTMLDivElement>(null);
  const initialized = useNodesInitialized();
  const [direction, setDirection] = useState<"RIGHT" | "DOWN">("DOWN");
  useEffect(() => {
    if (!initialized || !canvasRef.current) return;
    let frame = 0;
    const fit = () => {
      setDirection((canvasRef.current?.clientWidth ?? 0) >= 1100 ? "RIGHT" : "DOWN");
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => void fitView({ padding: .25, maxZoom: 1.25 }));
    };
    const observer = new ResizeObserver(fit);
    observer.observe(canvasRef.current);
    fit();
    return () => { observer.disconnect(); cancelAnimationFrame(frame); };
  }, [initialized, fitView]);
  const [linkMode, setLinkMode] = useState(false);
  const [linkSource, setLinkSource] = useState<string | null>(null);
  const [layoutVersion, setLayoutVersion] = useState(0);
  const [layoutError, setLayoutError] = useState(false);
  const [layingOut, setLayingOut] = useState(true);
  const [manuallyMoved, setManuallyMoved] = useState(false);
  const [layout, setLayout] = useState<Awaited<ReturnType<typeof layoutGraph>> | null>(null);
  const [flowNodes, setFlowNodes] = useState<Placed[]>([]);
  // Selection does not invalidate layout or discard manual positions.
  const topology = JSON.stringify({ nodes, edges });
  useEffect(() => {
    let stale = false;
    const graph: { nodes: Node[]; edges: Edge[] } = JSON.parse(topology);
    setLayingOut(true);
    setLayoutError(false);
    void layoutGraph(graph.nodes, graph.edges, direction).then(result => {
      if (stale) return;
      setLayout(result);
      setFlowNodes(graph.nodes.map(node => ({
        id: node.id, type: "entity", position: result.positions.get(node.id)!,
        data: { label: node.label }, ...entitySize(node.label), style: entitySize(node.label),
      })));
      setManuallyMoved(false);
      setLayingOut(false);
      requestAnimationFrame(() => void fitView({ padding: .2, maxZoom: 1.25 }));
    }).catch(() => { if (!stale) { setLayoutError(true); setLayingOut(false); } });
    return () => { stale = true; };
  }, [topology, layoutVersion, fitView, direction]);

  const displayedNodes = useMemo(() => flowNodes.map(node => ({ ...node, selected: node.id === selected })), [flowNodes, selected]);
  const flowEdges: FlowEdge[] = useMemo(() => edges.filter(edge => layout?.routes.has(edge.id)).map(edge => {
    const active = edge.id === selectedEdge;
    const color = active ? "#285f7d" : "#768692";
    return {
      id: edge.id, source: edge.source, target: edge.target,
      sourceHandle: "right", targetHandle: "left", type: "entity", selected: active,
      label: relationLabel(edge),
      data: { route: layout!.routes.get(edge.id), sourcePosition: layout!.positions.get(edge.source), targetPosition: layout!.positions.get(edge.target), onSelect: () => onSelectEdge(edge.id) },
      markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color },
      style: { stroke: color, strokeWidth: active ? 2.4 : 1.5 },
    };
  }), [edges, selectedEdge, layout, onSelectEdge]);

  const onNodesChange = useCallback((changes: NodeChange<Placed>[]) => {
    setFlowNodes(current => applyNodeChanges(changes, current));
    if (changes.some(change => change.type === "position" && change.dragging)) setManuallyMoved(true);
  }, []);

  const connect = useCallback(
    (source: string, target: string) => {
      if (!canEdit || !source || !target || source === target) return;
      onLink(source, target);
    },
    [onLink, canEdit],
  );

  const onConnect = useCallback(
    (connection: Connection) => {
      if (connection.source && connection.target) connect(connection.source, connection.target);
    },
    [connect],
  );

  const onConnectEnd = useCallback(
    (event: MouseEvent | TouchEvent, state: FinalConnectionState) => {
      if (state.isValid || !state.fromNode) return;
      const point = eventPoint(event);
      if (!point) return;
      const flowPoint = screenToFlowPosition(point);
      const target = flowNodes.find((node) => node.id !== state.fromNode?.id && containsPoint(node, flowPoint));
      if (target) connect(state.fromNode.id, target.id);
    },
    [connect, flowNodes, screenToFlowPosition],
  );

  return (<>
      <div role="toolbar" className="canvas-tools" aria-label="图谱建模工具栏">
        <button onClick={onCreate} disabled={!canEdit}>＋ 新建实体</button>
        <button aria-pressed={linkMode} disabled={!canEdit || nodes.length < 2} onClick={() => { setLinkMode(!linkMode); setLinkSource(null); }}>连接实体</button>
        <button disabled={layingOut} onClick={() => setLayoutVersion(value => value + 1)}>自动整理</button>
        <button onClick={() => void fitView({padding:.25})}>适应画布</button>
        {linkMode && <span role="status"><span>{linkSource ? "请选择终点实体" : "请选择起点实体"}</span><button onClick={() => { setLinkMode(false); setLinkSource(null); }}>取消</button></span>}
      </div>
    {layingOut && <p role="status" className="graph-layout-status">正在整理图谱…</p>}
    {layoutError && <p role="alert">图谱布局失败，请点击“自动整理”重试。</p>}
    {manuallyMoved && <p role="status" className="graph-layout-status">位置已手动调整；可用“自动整理”重新避让连线与标签。</p>}
    <ReactFlow
      ref={canvasRef}
      style={{ flex: 1, height: "auto" }}
      fitView
      fitViewOptions={{ padding: .25, maxZoom: 1.25 }}
      nodes={displayedNodes}
      edges={flowEdges}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      onNodesChange={onNodesChange}
      onConnect={onConnect}
      onConnectEnd={onConnectEnd}
      onNodeClick={(_, node) => {
        onSelect(node.id);
        if (linkMode && canEdit) {
          if (linkSource && linkSource !== node.id) { connect(linkSource, node.id); setLinkMode(false); setLinkSource(null); }
          else setLinkSource(node.id);
        }
      }}
      onNodeDoubleClick={(_, node) => onOpenFull?.(node.id)}
      onEdgeClick={(_, edge) => onSelectEdge(edge.id)}
      isValidConnection={(connection) => Boolean(connection.source && connection.target && connection.source !== connection.target)}
      connectionMode={ConnectionMode.Loose}
      connectionLineType={ConnectionLineType.Step}
      connectionLineStyle={{ stroke: "#285f7d", strokeWidth: 2 }}
      connectionRadius={80}
      defaultEdgeOptions={{ type: "entity" }}
      defaultViewport={{ x: 40, y: 20, zoom: 1 }}
      deleteKeyCode={null}
      minZoom={0.1}
      maxZoom={1.8}
      nodesDraggable
      nodesConnectable={canEdit}
      elementsSelectable
      panOnDrag
      zoomOnScroll
      zoomOnDoubleClick={false}
      elevateEdgesOnSelect
      proOptions={{ hideAttribution: false }}
    >
      <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="#c9d1d8" />
      <Controls showInteractive={false} />

    </ReactFlow>
    </>
  );
}

function EntityNode({ data, selected }: NodeProps<Placed>) {
  return (
    <div className={selected ? "flow-node selected" : "flow-node"} role="button" aria-pressed={selected} aria-label={`选择实体 ${data.label}`}>
      <Handle id="top" className="nodrag" type="source" position={Position.Top} />
      <Handle id="right" className="nodrag" type="source" position={Position.Right} />
      <Handle id="bottom" className="nodrag" type="source" position={Position.Bottom} />
      <Handle id="left" className="nodrag" type="source" position={Position.Left} />
      <span>{data.label}</span>
    </div>
  );
}

function RoutedEdge({ id, source, target, markerEnd, style, label, data }: EdgeProps) {
  const sourceNode = useInternalNode(source), targetNode = useInternalNode(target);
  if (!sourceNode || !targetNode || !data?.route) return null;
  const route = data.route as Route;
  const originA = data.sourcePosition as { x: number; y: number }, originB = data.targetPosition as { x: number; y: number };
  const a = sourceNode.internals.positionAbsolute, b = targetNode.internals.positionAbsolute;
  const moved = a.x !== originA.x || a.y !== originA.y || b.x !== originB.x || b.y !== originB.y;
  let path = route.points.map((point, index) => `${index ? "L" : "M"} ${point.x},${point.y}`).join(" ");
  let x = route.label.x + route.width / 2, y = route.label.y + route.height / 2;
  if (moved) {
    // React Flow previews manual moves; ELK remains the sole automatic layout owner.
    [path, x, y] = getSmoothStepPath({ sourceX: a.x + (sourceNode.measured.width ?? 200), sourceY: a.y + (sourceNode.measured.height ?? 64) / 2,
      targetX: b.x, targetY: b.y + (targetNode.measured.height ?? 64) / 2, sourcePosition: Position.Right, targetPosition: Position.Left, borderRadius: 0 });
  }
  return <>
    <BaseEdge id={id} path={path} markerEnd={markerEnd} style={style}/>
    <EdgeLabelRenderer><button className="edge-label nodrag nopan" style={{width:route.width, height:route.height, transform:`translate(-50%, -50%) translate(${x}px, ${y}px)`}}
      title={String(label)} onClick={() => { if (typeof data.onSelect === "function") data.onSelect(); }}>{label}</button></EdgeLabelRenderer>
  </>;
}

function containsPoint(node: Placed, point: { x: number; y: number }) {
  return point.x >= node.position.x && point.x <= node.position.x + (node.width ?? 200)
    && point.y >= node.position.y && point.y <= node.position.y + (node.height ?? 64);
}

function eventPoint(event: MouseEvent | TouchEvent) {
  if ("changedTouches" in event) {
    const touch = event.changedTouches[0];
    return touch ? { x: touch.clientX, y: touch.clientY } : null;
  }
  return { x: event.clientX, y: event.clientY };
}

