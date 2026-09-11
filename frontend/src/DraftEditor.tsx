import { useEffect, useMemo, useRef, useState } from "react";

export type DraftDocument = Record<string, unknown> & {
  apiVersion: string;
  kind: string;
  id: string;
  version: string;
  label?: string;
};

const editableKinds = ["ObjectType", "Link", "Rule", "Mapping", "IntegrationBinding"];

type Props = {
  documents: DraftDocument[];
  search: string;
  onChange: (documents: DraftDocument[]) => void;
  onImport: (documents: DraftDocument[]) => void;
  onError: (message: string | null) => void;
  onCheckDelete: (semanticId: string) => Promise<{ id: string; kind: string }[]>;
};

export function DraftEditor({
  documents,
  search,
  onChange,
  onImport,
  onError,
  onCheckDelete,
}: Props) {
  const definitions = useMemo(
    () =>
      documents.filter(
        (item) =>
          editableKinds.includes(item.kind) &&
          `${item.kind} ${item.id} ${item.label ?? ""}`.toLowerCase().includes(search.toLowerCase()),
      ),
    [documents, search],
  );
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [newKind, setNewKind] = useState("ObjectType");
  const [newId, setNewId] = useState("");
  const importRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!definitions.some((item) => item.id === selectedId)) {
      setSelectedId(definitions[0]?.id ?? null);
    }
  }, [definitions, selectedId]);

  const selected = documents.find((item) => item.id === selectedId) ?? null;

  function replace(next: DraftDocument) {
    onError(null);
    onChange(documents.map((item) => (item.id === next.id ? next : item)));
  }

  function createDefinition() {
    const id = newId.trim();
    if (!/^[A-Za-z][A-Za-z0-9_-]*\.[A-Za-z][A-Za-z0-9_-]*$/.test(id)) {
      onError("Semantic ID 应为 namespace.Name");
      return;
    }
    if (documents.some((item) => item.id === id)) {
      onError("Semantic ID 已存在");
      return;
    }
    const document = makeDocument(newKind, id, documents);
    onChange([...documents, document]);
    setSelectedId(id);
    setNewId("");
    onError(null);
  }

  async function removeDefinition() {
    if (!selected) return;
    const impacts = await onCheckDelete(selected.id);
    if (impacts.length) {
      onError(`仍被 ${impacts.slice(0, 3).map((item) => item.id).join("、")} 引用，不能删除`);
      return;
    }
    onChange(documents.filter((item) => item.id !== selected.id));
    setSelectedId(null);
    onError(null);
  }

  function exportDraft() {
    const blob = new Blob([JSON.stringify(documents, null, 2)], { type: "application/json" });
    const href = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = href;
    anchor.download = "semaloom-draft.json";
    anchor.click();
    URL.revokeObjectURL(href);
  }

  async function importDraft(file: File | undefined) {
    if (!file) return;
    try {
      const parsed: unknown = JSON.parse(await file.text());
      if (!Array.isArray(parsed) || !parsed.every(isDraftDocument)) throw new Error();
      onImport(parsed);
      onError(null);
    } catch {
      onError("导入文件必须是 SemaLoom 定义数组");
    } finally {
      if (importRef.current) importRef.current.value = "";
    }
  }

  return (
    <div className="draft-editor">
      <section className="definition-browser" aria-label="草稿定义">
        <div className="draft-tools">
          <select aria-label="定义类型" value={newKind} onChange={(event) => setNewKind(event.target.value)}>
            {editableKinds.map((kind) => <option key={kind}>{kind}</option>)}
          </select>
          <input aria-label="新定义 Semantic ID" value={newId} onChange={(event) => setNewId(event.target.value)} placeholder="namespace.Name" />
          <button className="secondary" onClick={createDefinition}>新建</button>
        </div>
        <div className="draft-file-actions">
          <button className="text-button" onClick={() => importRef.current?.click()}>导入 JSON</button>
          <button className="text-button" onClick={exportDraft}>导出 JSON</button>
          <input ref={importRef} className="sr-only" type="file" accept="application/json,.json" onChange={(event) => void importDraft(event.target.files?.[0])} />
        </div>
        <ul className="definition-browser-list">
          {definitions.map((item) => (
            <li key={`${item.kind}:${item.id}`}>
              <button className={selectedId === item.id ? "active" : ""} onClick={() => setSelectedId(item.id)}>
                <span>{item.label || item.id.split(".").at(-1)}</span>
                <code>{item.kind} · {item.id}</code>
              </button>
            </li>
          ))}
        </ul>
      </section>
      <section className="definition-form" aria-label="定义编辑器">
        {selected ? (
          <>
            <div className="definition-form-head">
              <div><span>{selected.kind}</span><h2>{selected.id}</h2></div>
              <button className="danger-button" onClick={() => void removeDefinition()}>删除</button>
            </div>
            <CommonFields document={selected} onChange={replace} />
            {selected.kind === "ObjectType" ? <ObjectFields document={selected} onChange={replace} /> : null}
            {selected.kind === "Link" ? <LinkFields document={selected} objects={documents.filter((item) => item.kind === "ObjectType")} onChange={replace} /> : null}
            {selected.kind === "Rule" ? <RuleFields document={selected} onChange={replace} /> : null}
            {selected.kind === "Mapping" ? <MappingFields document={selected} documents={documents} onChange={replace} /> : null}
            {selected.kind === "IntegrationBinding" ? <IntegrationFields document={selected} onChange={replace} /> : null}
          </>
        ) : <div className="inspector-empty"><h2>选择一个定义</h2><p>编辑内容后使用右上角“保存草稿”运行完整 Compiler 校验。</p></div>}
      </section>
    </div>
  );
}

function CommonFields({ document, onChange }: { document: DraftDocument; onChange: (next: DraftDocument) => void }) {
  return <div className="form-grid"><Field label="显示名称"><input value={text(document.label)} onChange={(event) => onChange({ ...document, label: event.target.value })} /></Field><Field label="版本"><input value={text(document.version)} onChange={(event) => onChange({ ...document, version: event.target.value })} /></Field></div>;
}

function ObjectFields({ document, onChange }: { document: DraftDocument; onChange: (next: DraftDocument) => void }) {
  const properties = array(document.properties) as Record<string, unknown>[];
  function update(index: number, patch: Record<string, unknown>) {
    onChange({ ...document, properties: properties.map((item, position) => position === index ? { ...item, ...patch } : item) });
  }
  return <><Field label="业务键（逗号分隔）"><input value={array(document.identityKeys).join(", ")} onChange={(event) => onChange({ ...document, identityKeys: csv(event.target.value) })} /></Field><div className="field-array"><div className="field-array-head"><h3>属性</h3><button className="secondary" onClick={() => onChange({ ...document, properties: [...properties, { id: "newProperty", valueType: "STRING", required: false }] })}>添加属性</button></div>{properties.map((property, index) => <div className="property-row" key={`${text(property.id)}:${index}`}><input aria-label="属性 ID" value={text(property.id)} onChange={(event) => update(index, { id: event.target.value })} /><input aria-label="属性名称" value={text(property.label)} placeholder="显示名称" onChange={(event) => update(index, { label: event.target.value })} /><select aria-label="属性类型" value={text(property.valueType)} onChange={(event) => update(index, { valueType: event.target.value })}>{["STRING", "INTEGER", "DECIMAL", "BOOLEAN", "DATE", "DATETIME"].map((type) => <option key={type}>{type}</option>)}</select><label className="check-field"><input type="checkbox" checked={Boolean(property.required)} onChange={(event) => update(index, { required: event.target.checked })} />必需</label><button aria-label={`删除属性 ${text(property.id)}`} className="icon-button" onClick={() => onChange({ ...document, properties: properties.filter((_, position) => position !== index) })}>×</button></div>)}</div></>;
}

function LinkFields({ document, objects, onChange }: { document: DraftDocument; objects: DraftDocument[]; onChange: (next: DraftDocument) => void }) {
  const identity = object(document.identity);
  return <><div className="form-grid"><Field label="起点实体"><select value={text(document.source)} onChange={(event) => onChange({ ...document, source: event.target.value })}>{objects.map(option)}</select></Field><Field label="终点实体"><select value={text(document.target)} onChange={(event) => onChange({ ...document, target: event.target.value })}>{objects.map(option)}</select></Field><Field label="基数"><select value={text(document.cardinality)} onChange={(event) => onChange({ ...document, cardinality: event.target.value })}><option>ONE</option><option>MANY</option></select></Field></div><div className="form-grid"><Field label="起点业务键"><input value={text(identity.source)} onChange={(event) => onChange({ ...document, identity: { ...identity, source: event.target.value } })} /></Field><Field label="终点业务键"><input value={text(identity.target)} onChange={(event) => onChange({ ...document, identity: { ...identity, target: event.target.value } })} /></Field></div></>;
}

function RuleFields({ document, onChange }: { document: DraftDocument; onChange: (next: DraftDocument) => void }) {
  const inputs = array(document.inputs) as Record<string, unknown>[];
  const expression = object(document.expression);
  const args = array(expression.args) as Record<string, unknown>[];
  const inputNames = inputs.map((item) => text(item.name)).filter(Boolean);
  function updateInput(index: number, patch: Record<string, unknown>) {
    onChange({ ...document, inputs: inputs.map((item, position) => position === index ? { ...item, ...patch } : item) });
  }
  function setInputSource(index: number, kind: string, reference: string) {
    if (kind === "metric") {
      updateInput(index, { metric: reference, property: undefined, objectType: undefined });
      return;
    }
    const separator = reference.lastIndexOf(".");
    updateInput(index, {
      metric: undefined,
      objectType: reference.slice(0, separator),
      property: reference.slice(separator + 1),
    });
  }
  function updateExpression(patch: Record<string, unknown>) {
    onChange({ ...document, expression: { ...expression, ...patch } });
  }
  function updateArg(index: number, name: string) {
    const next = [args[0] ?? { op: "ref", name: inputNames[0] ?? "" }, args[1] ?? { op: "ref", name: inputNames[1] ?? inputNames[0] ?? "" }];
    next[index] = { op: "ref", name };
    updateExpression({ args: next });
  }
  const binary = ["eq", "ne", "lt", "le", "gt", "ge", "add", "sub", "mul", "div", "and", "or"];
  return <><Field label="Claim ID"><input value={text(document.claim)} onChange={(event) => onChange({ ...document, claim: event.target.value || undefined })} /></Field><div className="field-array"><div className="field-array-head"><h3>规则输入</h3><button className="secondary" onClick={() => onChange({ ...document, inputs: [...inputs, { name: "input", metric: "", required: true }] })}>添加输入</button></div>{inputs.map((input, index) => { const sourceKind = input.metric ? "metric" : "property"; const source = sourceKind === "metric" ? text(input.metric) : `${text(input.objectType)}.${text(input.property)}`; return <div className="rule-input-row" key={`${text(input.name)}:${index}`}><input aria-label="输入名称" value={text(input.name)} onChange={(event) => updateInput(index, { name: event.target.value })} /><select aria-label="输入类型" value={sourceKind} onChange={(event) => setInputSource(index, event.target.value, source)}><option value="metric">指标</option><option value="property">实体属性</option></select><input aria-label="输入语义引用" value={source} onChange={(event) => setInputSource(index, sourceKind, event.target.value)} /><label className="check-field"><input type="checkbox" checked={input.required !== false} onChange={(event) => updateInput(index, { required: event.target.checked })} />必需</label><button className="icon-button" aria-label={`删除输入 ${text(input.name)}`} onClick={() => onChange({ ...document, inputs: inputs.filter((_, position) => position !== index) })}>×</button></div>; })}</div><div className="expression-builder"><h3>判断表达式</h3><div className="form-grid"><Field label="运算"><select value={text(expression.op)} onChange={(event) => updateExpression({ op: event.target.value, args: args.length >= 2 ? args : [{ op: "ref", name: inputNames[0] ?? "" }, { op: "ref", name: inputNames[1] ?? inputNames[0] ?? "" }] })}>{binary.map((op) => <option key={op}>{op}</option>)}</select></Field><Field label="左输入"><select value={text(args[0]?.name)} onChange={(event) => updateArg(0, event.target.value)}>{inputNames.map((name) => <option key={name}>{name}</option>)}</select></Field><Field label="右输入"><select value={text(args[1]?.name)} onChange={(event) => updateArg(1, event.target.value)}>{inputNames.map((name) => <option key={name}>{name}</option>)}</select></Field></div></div></>;
}

function MappingFields({ document, documents, onChange }: { document: DraftDocument; documents: DraftDocument[]; onChange: (next: DraftDocument) => void }) {
  const physical = object(document.physical);
  const targets = documents.filter((item) => item.kind === "ObjectType" || item.kind === "Metric");
  function setPhysical(field: string, value: unknown) {
    onChange({ ...document, physical: { ...physical, [field]: value || undefined } });
  }
  return <><div className="form-grid"><Field label="业务目标"><select value={text(document.target)} onChange={(event) => onChange({ ...document, target: event.target.value })}>{targets.map(option)}</select></Field><Field label="所属实体"><select value={text(document.objectType)} onChange={(event) => onChange({ ...document, objectType: event.target.value })}>{documents.filter((item) => item.kind === "ObjectType").map(option)}</select></Field><Field label="来源 ID"><input value={text(document.sourceId)} onChange={(event) => onChange({ ...document, sourceId: event.target.value })} /></Field><Field label="协议"><select value={text(document.provider)} onChange={(event) => onChange({ ...document, provider: event.target.value, physical: event.target.value === "openapi" ? { method: "GET", path: "", identityParameter: "id", identityPointer: "/id", propertyPointers: {} } : { table: "", tenantColumn: "tenant_id", identityColumn: "", propertyColumns: {} } })}><option value="postgres">PostgreSQL</option><option value="openapi">OpenAPI</option></select></Field><Field label="完整性"><select value={text(document.completeness)} onChange={(event) => onChange({ ...document, completeness: event.target.value })}><option>AUTHORITATIVE</option><option>PARTIAL</option></select></Field><Field label="基数"><select value={text(document.expectedCardinality)} onChange={(event) => onChange({ ...document, expectedCardinality: event.target.value })}><option>ONE</option><option>MANY</option></select></Field></div>{document.provider === "openapi" ? <><div className="form-grid"><Field label="HTTP 方法"><select value={text(physical.method) || "GET"} onChange={(event) => setPhysical("method", event.target.value)}><option>GET</option></select></Field><Field label="路径"><input value={text(physical.path)} placeholder="/orders" onChange={(event) => setPhysical("path", event.target.value)} /></Field><Field label="Operation ID"><input value={text(physical.operationId)} onChange={(event) => setPhysical("operationId", event.target.value)} /></Field><Field label="业务键参数"><input value={text(physical.identityParameter)} placeholder="orderId" onChange={(event) => setPhysical("identityParameter", event.target.value)} /></Field><Field label="业务键响应指针"><input value={text(physical.identityPointer)} placeholder="/orderId" onChange={(event) => setPhysical("identityPointer", event.target.value)} /></Field><Field label="记录集合指针"><input value={text(physical.recordsPointer)} placeholder="可选，例如 /items" onChange={(event) => setPhysical("recordsPointer", event.target.value)} /></Field><Field label="下一页指针"><input value={text(physical.nextPointer)} placeholder="可选，例如 /next" onChange={(event) => setPhysical("nextPointer", event.target.value)} /></Field><Field label="指标值指针"><input value={text(physical.valuePointer)} placeholder="指标 Mapping 使用" onChange={(event) => setPhysical("valuePointer", event.target.value)} /></Field></div><MappingPairs label="业务键响应映射" values={object(physical.grainPointers)} physicalLabel="JSON Pointer" onChange={(value) => setPhysical("grainPointers", value)} /><MappingPairs label="属性响应映射" values={object(physical.propertyPointers)} physicalLabel="JSON Pointer" onChange={(value) => setPhysical("propertyPointers", value)} /></> : <><div className="form-grid"><Field label="Schema"><input value={text(physical.schema)} onChange={(event) => setPhysical("schema", event.target.value)} /></Field><Field label="表 / 视图"><input value={text(physical.table)} onChange={(event) => setPhysical("table", event.target.value)} /></Field><Field label="租户列"><input value={text(physical.tenantColumn)} placeholder="tenant_id" onChange={(event) => setPhysical("tenantColumn", event.target.value)} /></Field><Field label="业务键列"><input value={text(physical.identityColumn)} onChange={(event) => setPhysical("identityColumn", event.target.value)} /></Field><Field label="值列"><input value={text(physical.valueColumn)} placeholder="指标 Mapping 使用" onChange={(event) => setPhysical("valueColumn", event.target.value)} /></Field></div><MappingPairs label="业务键列映射" values={object(physical.grainColumns)} physicalLabel="数据库列" onChange={(value) => setPhysical("grainColumns", value)} /><MappingPairs label="属性列映射" values={object(physical.propertyColumns)} physicalLabel="数据库列" onChange={(value) => setPhysical("propertyColumns", value)} /></>}</>;
}

function MappingPairs({ label, values, physicalLabel, onChange }: { label: string; values: Record<string, unknown>; physicalLabel: string; onChange: (value: Record<string, string>) => void }) {
  const entries = Object.entries(values).map(([semantic, physical]) => [semantic, text(physical)] as const);
  function update(index: number, semantic: string, physical: string) {
    onChange(Object.fromEntries(entries.map((entry, position) => position === index ? [semantic, physical] : entry).filter(([key]) => key)));
  }
  return <div className="field-array"><div className="field-array-head"><h3>{label}</h3><button className="secondary" onClick={() => onChange({ ...Object.fromEntries(entries), newField: "" })}>添加字段</button></div>{entries.map(([semantic, physical], index) => <div className="mapping-pair-row" key={`${semantic}:${index}`}><input aria-label="语义字段" value={semantic} placeholder="语义属性" onChange={(event) => update(index, event.target.value, physical)} /><span>→</span><input aria-label={physicalLabel} value={physical} placeholder={physicalLabel} onChange={(event) => update(index, semantic, event.target.value)} /><button className="icon-button" aria-label={`删除字段 ${semantic}`} onClick={() => onChange(Object.fromEntries(entries.filter((_, position) => position !== index)))}>×</button></div>)}</div>;
}

function IntegrationFields({ document, onChange }: { document: DraftDocument; onChange: (next: DraftDocument) => void }) {
  return <div className="form-grid"><Field label="逻辑来源 ID"><input value={text(document.sourceId)} onChange={(event) => onChange({ ...document, sourceId: event.target.value })} /></Field><Field label="协议"><select value={text(document.provider)} onChange={(event) => onChange({ ...document, provider: event.target.value })}><option value="postgres">PostgreSQL</option><option value="openapi">OpenAPI</option></select></Field><Field label="Mapping IDs"><textarea rows={5} value={array(document.mappings).join("\n")} onChange={(event) => onChange({ ...document, mappings: lines(event.target.value) })} /></Field><Field label="Action Binding IDs"><textarea rows={5} value={array(document.actionBindings).join("\n")} onChange={(event) => onChange({ ...document, actionBindings: lines(event.target.value) })} /></Field></div>;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="form-field"><span>{label}</span>{children}</label>;
}

function option(item: DraftDocument) {
  return <option key={item.id} value={item.id}>{item.label || item.id}</option>;
}

function makeDocument(kind: string, id: string, documents: DraftDocument[]): DraftDocument {
  const base = { apiVersion: "semaloom/v0.1", kind, id, version: "1.0.0", label: id.split(".").at(-1) };
  const firstObject = documents.find((item) => item.kind === "ObjectType");
  if (kind === "ObjectType") return { ...base, identityKeys: ["id"], properties: [{ id: "id", valueType: "STRING", required: true }] };
  if (kind === "Link") return { ...base, source: firstObject?.id ?? "", target: firstObject?.id ?? "", identity: { source: "id", target: "id" }, cardinality: "ONE", traversal: "FORWARD" };
  if (kind === "Rule") return { ...base, inputs: [], expression: { op: "bool", value: true } };
  if (kind === "Mapping") return { ...base, target: firstObject?.id ?? "", objectType: firstObject?.id ?? "", sourceId: "", provider: "postgres", expectedCardinality: "ONE", completeness: "PARTIAL", physical: { table: "", tenantColumn: "tenant_id", identityColumn: "", grainColumns: {}, propertyColumns: {} } };
  return { ...base, provider: "postgres", sourceId: "", mappings: [], actionBindings: [] };
}

function isDraftDocument(value: unknown): value is DraftDocument {
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  return typeof item.apiVersion === "string" && typeof item.kind === "string" && typeof item.id === "string" && typeof item.version === "string";
}

function text(value: unknown): string { return typeof value === "string" ? value : ""; }
function array(value: unknown): unknown[] { return Array.isArray(value) ? value : []; }
function object(value: unknown): Record<string, unknown> { return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {}; }
function csv(value: string): string[] { return value.split(",").map((item) => item.trim()).filter(Boolean); }
function lines(value: string): string[] { return value.split("\n").map((item) => item.trim()).filter(Boolean); }
