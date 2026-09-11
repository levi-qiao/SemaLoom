import { useEffect, useMemo, useState } from "react";

type Node = { id: string; label: string; properties: string[] };
type Edge = { id: string; source: string; target: string; cardinality: string };
type Inspector = {
  id: string;
  label: string;
  identityKeys: string[];
  metrics: string[];
  mappings: string[];
  rules: string[];
};

const TOKEN = "tenant-a-analyst";
const headers = { Authorization: `Bearer ${TOKEN}`, "Content-Type": "application/json" };

export default function App() {
  const [view, setView] = useState<"graph" | "list" | "mappings">("graph");
  const [nodes, setNodes] = useState<Node[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [inspector, setInspector] = useState<Inspector | null>(null);
  const [mappings, setMappings] = useState<{ id: string; target: string; sourceId: string }[]>([]);
  const [revision, setRevision] = useState(0);
  const [status, setStatus] = useState("未保存");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/v0.1/studio/graph", { headers })
      .then((response) => {
        if (!response.ok) throw new Error(`graph ${response.status}`);
        return response.json();
      })
      .then((payload) => {
        setNodes(payload.nodes);
        setEdges(payload.edges);
        if (payload.nodes[0]) setSelected(payload.nodes[0].id);
      })
      .catch((err: Error) => setError(err.message));
    fetch("/v0.1/studio/mappings", { headers })
      .then((response) => response.json())
      .then((payload) => setMappings(payload.mappings ?? []))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!selected) return;
    fetch(`/v0.1/studio/inspector?objectId=${encodeURIComponent(selected)}`, { headers })
      .then((response) => response.json())
      .then(setInspector)
      .catch(() => setInspector(null));
  }, [selected]);

  const positions = useMemo(() => {
    return Object.fromEntries(
      nodes.map((node, index) => [
        node.id,
        { x: 40 + (index % 3) * 260, y: 40 + Math.floor(index / 3) * 140 },
      ]),
    );
  }, [nodes]);

  async function saveDraft() {
    const response = await fetch("/v0.1/studio/drafts/default", {
      method: "PUT",
      headers,
      body: JSON.stringify({
        expectedRevision: revision,
        payload: { selected, view },
      }),
    });
    if (response.status === 409) {
      setStatus("修订冲突");
      return;
    }
    const payload = await response.json();
    setRevision(payload.revision);
    setStatus(`已保存 r${payload.revision}`);
  }

  return (
    <div className="shell">
      <nav>
        <strong>SemaLoom</strong>
        <button className={view === "graph" ? "active" : ""} onClick={() => setView("graph")}>
          实体模型
        </button>
        <button className={view === "list" ? "active" : ""} onClick={() => setView("list")}>
          实体列表
        </button>
        <button className={view === "mappings" ? "active" : ""} onClick={() => setView("mappings")}>
          来源映射
        </button>
      </nav>
      <main>
        <header>
          <span>草稿 / 本地开发</span>
          <span>{status}</span>
          <button onClick={() => void saveDraft()}>保存草稿</button>
        </header>
        {error ? <p className="error">{error}</p> : null}
        <section className="workspace">
          <div className="canvas">
            {view === "graph" ? (
              <svg width="100%" height="100%" role="img" aria-label="实体图谱">
                {edges.map((edge) => {
                  const from = positions[edge.source];
                  const to = positions[edge.target];
                  if (!from || !to) return null;
                  return (
                    <g key={edge.id}>
                      <line x1={from.x + 110} y1={from.y + 28} x2={to.x + 110} y2={to.y + 28} />
                      <text x={(from.x + to.x) / 2 + 110} y={(from.y + to.y) / 2 + 20}>
                        {edge.cardinality}
                      </text>
                    </g>
                  );
                })}
                {nodes.map((node) => {
                  const pos = positions[node.id];
                  return (
                    <g key={node.id} onClick={() => setSelected(node.id)} style={{ cursor: "pointer" }}>
                      <rect
                        x={pos.x}
                        y={pos.y}
                        width="220"
                        height="72"
                        rx="6"
                        className={selected === node.id ? "node selected" : "node"}
                      />
                      <text x={pos.x + 12} y={pos.y + 28}>
                        {node.label}
                      </text>
                      <text x={pos.x + 12} y={pos.y + 50} className="muted">
                        {node.id}
                      </text>
                    </g>
                  );
                })}
              </svg>
            ) : null}
            {view === "list" ? (
              <ul>
                {nodes.map((node) => (
                  <li key={node.id}>
                    <button onClick={() => setSelected(node.id)}>{node.label}</button>
                    <code>{node.id}</code>
                  </li>
                ))}
              </ul>
            ) : null}
            {view === "mappings" ? (
              <table>
                <thead>
                  <tr>
                    <th>Mapping</th>
                    <th>目标</th>
                    <th>来源</th>
                  </tr>
                </thead>
                <tbody>
                  {mappings.map((item) => (
                    <tr key={item.id}>
                      <td>{item.id}</td>
                      <td>{item.target}</td>
                      <td>{item.sourceId}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : null}
          </div>
          <aside>
            <h2>检查器</h2>
            {inspector ? (
              <>
                <p>{inspector.label}</p>
                <code>{inspector.id}</code>
                <h3>指标</h3>
                <ul>
                  {inspector.metrics.map((metric) => (
                    <li key={metric}>{metric}</li>
                  ))}
                </ul>
                <h3>映射</h3>
                <ul>
                  {inspector.mappings.map((mapping) => (
                    <li key={mapping}>{mapping}</li>
                  ))}
                </ul>
              </>
            ) : (
              <p>选择一个实体</p>
            )}
          </aside>
        </section>
      </main>
    </div>
  );
}
