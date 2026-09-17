import { useEffect, useMemo, useState } from "react";

import { LOCAL_ID, array, identityPropertyId, makeObjectType, object, text } from "./doc";
import { cardinalityHint, cardinalityLabel } from "./labels";
import { useRowKeys } from "./rowKeys";

export type DraftDocument = Record<string, unknown> & {
  apiVersion: string;
  kind: string;
  id: string;
  version: string;
  label?: string;
};

export type DefinitionKind = "ObjectType" | "Link" | "Rule" | "Action";

type Props = {
  kind: DefinitionKind;
  documents: DraftDocument[];
  search: string;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onChange: (documents: DraftDocument[]) => void;
  onError: (message: string | null) => void;
  onCheckDelete: (semanticId: string) => Promise<{ id: string; kind: string }[]>;
};

const kindLabels: Record<DefinitionKind, string> = {
  ObjectType: "实体",
  Link: "关系",
  Rule: "规则",
  Action: "操作",
};

export function DraftEditor({
  kind,
  documents,
  search,
  selectedId,
  onSelect,
  onChange,
  onError,
  onCheckDelete,
}: Props) {
  const definitions = useMemo(
    () =>
      documents.filter(
        (item) =>
          item.kind === kind &&
          `${item.id} ${item.label ?? ""}`.toLowerCase().includes(search.toLowerCase()),
      ),
    [documents, search, kind],
  );
  const namespaces = useMemo(
    () => [...new Set(documents.filter((item) => item.kind === "ObjectType").map((item) => item.id.split(".")[0] ?? "").filter(Boolean))],
    [documents],
  );
  const [newNamespace, setNewNamespace] = useState("");
  const [newName, setNewName] = useState("");
  const [newLabel, setNewLabel] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  useEffect(() => {
    if (!newNamespace && namespaces[0]) setNewNamespace(namespaces[0]);
  }, [namespaces, newNamespace]);
  useEffect(() => {
    if (!definitions.some((item) => item.id === selectedId)) {
      onSelect(definitions[0]?.id ?? null);
    }
  }, [definitions, selectedId, onSelect]);

  const selected = documents.find((item) => item.id === selectedId) ?? null;

  function replace(next: DraftDocument) {
    onError(null);
    onChange(documents.map((item) => (item.id === next.id ? next : item)));
  }

  function createDefinition() {
    const local = newName.trim();
    const display = newLabel.trim();
    if (!newNamespace || (kind === "ObjectType" ? !display : false) || !LOCAL_ID.test(local)) {
      setFormError(kind === "ObjectType" ? "请填写显示名称和英文语义 ID" : "请选择领域并填写英文名称");
      return;
    }
    const id = `${newNamespace}.${local}`;
    if (documents.some((item) => item.id === id)) {
      setFormError("该语义 ID 已存在");
      return;
    }
    const document = kind === "ObjectType" ? makeObjectType(newNamespace, local, display) : makeDocument(kind, id, documents, display || local);
    onChange([...documents, document]);
    onSelect(id);
    setNewName("");
    setNewLabel("");
    setFormError(null);
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
    onSelect(null);
    onError(null);
  }

  return (
    <div className="draft-editor">
      <section className="definition-browser" aria-label={`${kindLabels[kind]}列表`}>
        <div className="draft-tools">
          <select aria-label="领域" value={newNamespace} onChange={(event) => setNewNamespace(event.target.value)}>
            {namespaces.map((item) => <option key={item}>{item}</option>)}
          </select>
          {kind === "ObjectType" ? <input aria-label="显示名称" value={newLabel} onChange={(event) => setNewLabel(event.target.value)} placeholder="显示名称，例如 仓库" /> : null}
          <input aria-label={`新${kindLabels[kind]}名称`} value={newName} onChange={(event) => setNewName(event.target.value)} placeholder={kind === "ObjectType" ? "英文语义 ID，例如 Warehouse" : "名称，例如 Site"} />
          <button className="secondary" onClick={createDefinition}>新建{kindLabels[kind]}</button>
          {formError ? <p className="field-error" role="alert">{formError}</p> : null}
        </div>
        <ul className="definition-browser-list">
          {definitions.map((item) => (
            <li key={`${item.kind}:${item.id}`}>
              <button className={selectedId === item.id ? "active" : ""} onClick={() => onSelect(item.id)}>
                <span>{item.label || item.id.split(".").at(-1)}</span>
                <code>{item.id}</code>
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
            {selected.kind === "Rule" ? <RuleFields document={selected} documents={documents} onChange={replace} /> : null}
            {selected.kind === "Action" ? <ActionFields document={selected} objects={documents.filter((item) => item.kind === "ObjectType")} onChange={replace} /> : null}
          </>
        ) : <div className="inspector-empty"><h2>选择一个{kindLabels[kind]}</h2><p>左侧新建或点选后编辑，再用右上角保存。</p></div>}
      </section>
    </div>
  );
}

function CommonFields({ document, onChange }: { document: DraftDocument; onChange: (next: DraftDocument) => void }) {
  return <Field label="显示名称"><input aria-label="显示名称" value={text(document.label)} onChange={(event) => onChange({ ...document, label: event.target.value })} /></Field>;
}

function ObjectFields({ document, onChange }: { document: DraftDocument; onChange: (next: DraftDocument) => void }) {
  const properties = array(document.properties) as Record<string, unknown>[];
  const rowKeys = useRowKeys(properties.length, document.id);
  function update(index: number, patch: Record<string, unknown>) {
    const previousId = text(properties[index].id);
    const nextProperties = properties.map((item, position) => position === index ? { ...item, ...patch } : item);
    const identityKeys = array(document.identityKeys).map(String);
    let nextKeys = identityKeys;
    const nextId = patch.id;
    if (typeof nextId === "string" && nextId !== previousId) {
      nextKeys = identityKeys.map((item) => (item === previousId ? nextId : item));
    }
    onChange({ ...document, properties: nextProperties, identityKeys: nextKeys.length ? nextKeys : identityKeys });
  }
  const identityKeys = array(document.identityKeys).map(String);
  function toggleKey(propertyId: string, on: boolean) {
    const next = on ? [...new Set([...identityKeys, propertyId])] : identityKeys.filter((item) => item !== propertyId);
    onChange({ ...document, identityKeys: next.length ? next : [propertyId] });
  }
  return <><div className="field-array"><div className="field-array-head"><h3>属性</h3><button className="secondary" onClick={() => onChange({ ...document, properties: [...properties, { id: "newProperty", valueType: "STRING", required: false }] })}>添加属性</button></div>{properties.map((property, index) => <div className="property-row" key={rowKeys[index] ?? `property-${index}`}><input aria-label="属性 ID" value={text(property.id)} onChange={(event) => update(index, { id: event.target.value })} /><input aria-label="属性名称" value={text(property.label)} placeholder="显示名称" onChange={(event) => update(index, { label: event.target.value })} /><select aria-label="属性类型" value={text(property.valueType)} onChange={(event) => update(index, { valueType: event.target.value })}>{["STRING", "INTEGER", "DECIMAL", "BOOLEAN", "DATE", "DATETIME"].map((type) => <option key={type}>{type}</option>)}</select><label className="check-field"><input type="checkbox" checked={identityKeys.includes(text(property.id))} onChange={(event) => toggleKey(text(property.id), event.target.checked)} />业务键</label><label className="check-field"><input type="checkbox" checked={Boolean(property.required)} onChange={(event) => update(index, { required: event.target.checked })} />必需</label><button aria-label={`删除属性 ${text(property.id)}`} className="icon-button" onClick={() => onChange({ ...document, properties: properties.filter((_, position) => position !== index) })}>×</button></div>)}</div></>;
}


function LinkFields({ document, objects, onChange }: { document: DraftDocument; objects: DraftDocument[]; onChange: (next: DraftDocument) => void }) {
  const identity = array(document.identity) as Record<string, unknown>[];
  const sourceProps = array(objects.find((item) => item.id === text(document.source))?.properties) as Record<string, unknown>[];
  const targetProps = array(objects.find((item) => item.id === text(document.target))?.properties) as Record<string, unknown>[];
  const sourceLabel = text(objects.find((item) => item.id === text(document.source))?.label) || text(document.source) || "源";
  const targetLabel = text(objects.find((item) => item.id === text(document.target))?.label) || text(document.target) || "目标";
  function updatePair(index: number, patch: Record<string, unknown>) {
    onChange({ ...document, identity: identity.map((item, position) => position === index ? { ...item, ...patch } : item) });
  }
  function addPair() {
    onChange({
      ...document,
      identity: [...identity, { source: text(sourceProps[0]?.id), target: text(targetProps[0]?.id) }],
    });
  }
  return <><div className="form-grid"><Field label="起点实体"><select aria-label="起点实体" value={text(document.source)} onChange={(event) => onChange({ ...document, source: event.target.value })}>{objects.map(option)}</select></Field><Field label="终点实体"><select aria-label="终点实体" value={text(document.target)} onChange={(event) => onChange({ ...document, target: event.target.value })}>{objects.map(option)}</select></Field><Field label="基数"><select aria-label="基数" value={text(document.cardinality) || "ONE"} onChange={(event) => onChange({ ...document, cardinality: event.target.value })}><option value="ONE">{cardinalityLabel("ONE")}</option><option value="MANY">{cardinalityLabel("MANY")}</option></select></Field></div><p className="mapping-hint">{cardinalityHint(sourceLabel, targetLabel, text(document.cardinality) || "ONE")}。目标实体为复合业务身份时，每个身份字段都必须有一条对应关系。</p><div className="field-array"><div className="field-array-head"><h3>业务键对应</h3><button className="secondary" onClick={addPair}>添加键对应</button></div>{identity.map((pair, index) => <div className="property-row" key={`${text(pair.source)}:${text(pair.target)}:${index}`}><Field label="起点业务键"><select aria-label={index === 0 ? "起点业务键" : `起点业务键 ${index + 1}`} value={text(pair.source)} onChange={(event) => updatePair(index, { source: event.target.value })}>{sourceProps.map((item) => <option key={text(item.id)}>{text(item.id)}</option>)}</select></Field><Field label="终点业务键"><select aria-label={index === 0 ? "终点业务键" : `终点业务键 ${index + 1}`} value={text(pair.target)} onChange={(event) => updatePair(index, { target: event.target.value })}>{targetProps.map((item) => <option key={text(item.id)}>{text(item.id)}</option>)}</select></Field>{identity.length > 1 ? <button className="icon-button" aria-label={`删除键对应 ${index + 1}`} onClick={() => onChange({ ...document, identity: identity.filter((_, position) => position !== index) })}>×</button> : null}</div>)}</div></>;
}

function RuleFields({ document, documents, onChange }: { document: DraftDocument; documents: DraftDocument[]; onChange: (next: DraftDocument) => void }) {
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
  const metrics = documents.filter((item) => item.kind === "Metric");
  const propertyRefs = documents.filter((item) => item.kind === "ObjectType").flatMap((item) =>
    (array(item.properties) as Record<string, unknown>[]).map((property) => `${item.id}.${text(property.id)}`),
  );
  const firstMetric = metrics[0]?.id ?? "";
  return <><div className="field-array"><div className="field-array-head"><h3>规则输入</h3><button className="secondary" onClick={() => onChange({ ...document, inputs: [...inputs, { name: "input", metric: firstMetric, required: true }] })}>添加输入</button></div>{inputs.map((input, index) => { const sourceKind = input.metric ? "metric" : "property"; const source = sourceKind === "metric" ? text(input.metric) : `${text(input.objectType)}.${text(input.property)}`; return <div className="rule-input-row" key={`${text(input.name)}:${index}`}><input aria-label="输入名称" value={text(input.name)} onChange={(event) => updateInput(index, { name: event.target.value })} /><select aria-label="输入类型" value={sourceKind} onChange={(event) => setInputSource(index, event.target.value, sourceKind === "metric" ? firstMetric : propertyRefs[0] ?? "")}><option value="metric">指标</option><option value="property">实体属性</option></select><select aria-label="输入语义引用" value={source} onChange={(event) => setInputSource(index, sourceKind, event.target.value)}>{sourceKind === "metric" ? metrics.map((item) => <option key={item.id} value={item.id}>{String(item.label || item.id)}</option>) : propertyRefs.map((item) => <option key={item}>{item}</option>)}</select><label className="check-field"><input type="checkbox" checked={input.required !== false} onChange={(event) => updateInput(index, { required: event.target.checked })} />必需</label><button className="icon-button" aria-label={`删除输入 ${text(input.name)}`} onClick={() => onChange({ ...document, inputs: inputs.filter((_, position) => position !== index) })}>×</button></div>; })}</div><div className="expression-builder"><h3>判断表达式</h3><div className="form-grid"><Field label="运算"><select value={text(expression.op)} onChange={(event) => updateExpression({ op: event.target.value, args: args.length >= 2 ? args : [{ op: "ref", name: inputNames[0] ?? "" }, { op: "ref", name: inputNames[1] ?? inputNames[0] ?? "" }] })}>{binary.map((op) => <option key={op}>{op}</option>)}</select></Field><Field label="左输入"><select value={text(args[0]?.name)} onChange={(event) => updateArg(0, event.target.value)}>{inputNames.map((name) => <option key={name}>{name}</option>)}</select></Field><Field label="右输入"><select value={text(args[1]?.name)} onChange={(event) => updateArg(1, event.target.value)}>{inputNames.map((name) => <option key={name}>{name}</option>)}</select></Field></div></div></>;
}

function ActionFields({ document, objects, onChange }: { document: DraftDocument; objects: DraftDocument[]; onChange: (next: DraftDocument) => void }) {
  const parameters = array(document.parameters) as Record<string, unknown>[];
  function updateParam(index: number, patch: Record<string, unknown>) {
    onChange({ ...document, parameters: parameters.map((item, position) => position === index ? { ...item, ...patch } : item) });
  }
  return (
    <>
      <div className="form-grid">
        <Field label="目标实体"><select value={text(document.targetObject)} onChange={(event) => onChange({ ...document, targetObject: event.target.value })}>{objects.map(option)}</select></Field>
      </div>
      <Field label="效果说明"><textarea rows={3} value={text(document.effect)} onChange={(event) => onChange({ ...document, effect: event.target.value })} /></Field>
      <Field label="前提 Claim / Rule（逗号分隔）"><input value={array(document.preconditions).join(", ")} onChange={(event) => onChange({ ...document, preconditions: csv(event.target.value) })} /></Field>
      <div className="field-array">
        <div className="field-array-head"><h3>参数</h3><button className="secondary" onClick={() => onChange({ ...document, parameters: [...parameters, { name: "param", valueType: "STRING", required: true }] })}>添加参数</button></div>
        {parameters.map((parameter, index) => (
          <div className="property-row" key={`${text(parameter.name)}:${index}`}>
            <input aria-label="参数名称" value={text(parameter.name)} onChange={(event) => updateParam(index, { name: event.target.value })} />
            <select aria-label="参数类型" value={text(parameter.valueType)} onChange={(event) => updateParam(index, { valueType: event.target.value })}>{["STRING", "INTEGER", "DECIMAL", "BOOLEAN", "DATE", "DATETIME"].map((type) => <option key={type}>{type}</option>)}</select>
            <label className="check-field"><input type="checkbox" checked={parameter.required !== false} onChange={(event) => updateParam(index, { required: event.target.checked })} />必需</label>
            <button className="icon-button" aria-label={`删除参数 ${text(parameter.name)}`} onClick={() => onChange({ ...document, parameters: parameters.filter((_, position) => position !== index) })}>×</button>
          </div>
        ))}
      </div>
    </>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="form-field"><span>{label}</span>{children}</label>;
}

function option(item: DraftDocument) {
  return <option key={item.id} value={item.id}>{item.label || item.id}</option>;
}

function makeDocument(kind: string, id: string, documents: DraftDocument[], label: string): DraftDocument {
  const base = { apiVersion: "semaloom/v0.1", kind, id, version: "1.0.0", label };
  const firstObject = documents.find((item) => item.kind === "ObjectType");
  if (kind === "ObjectType") return makeObjectType(id.split(".")[0] ?? "procurement", id.split(".").slice(1).join("."), label);
  if (kind === "Link") { const key = array(firstObject?.identityKeys).map(String)[0] ?? identityPropertyId(String(firstObject?.id.split(".").at(-1) ?? "id")); return { ...base, source: firstObject?.id ?? "", target: firstObject?.id ?? "", identity: [{ source: key, target: key }], cardinality: "ONE", traversal: "FORWARD" }; }
  if (kind === "Rule") return { ...base, inputs: [], expression: { op: "bool", value: true } };
  return { ...base, targetObject: firstObject?.id ?? "", effect: "Describe the business effect", preconditions: [], parameters: [] };
}

function csv(value: string): string[] { return value.split(",").map((item) => item.trim()).filter(Boolean); }
