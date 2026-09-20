import { array, object, text } from "./doc";
import { cardinalityHint, cardinalityLabel } from "./labels";
import type { DraftDocument } from "./types";

export function LinkFields({ document, objects, onChange }: { document: DraftDocument; objects: DraftDocument[]; onChange: (next: DraftDocument) => void }) {
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
  return (
    <>
      <div className="form-grid">
        <Field label="起点实体">
          <select aria-label="起点实体" value={text(document.source)} onChange={(event) => onChange({ ...document, source: event.target.value })}>
            {objects.map(option)}
          </select>
        </Field>
        <Field label="终点实体">
          <select aria-label="终点实体" value={text(document.target)} onChange={(event) => onChange({ ...document, target: event.target.value })}>
            {objects.map(option)}
          </select>
        </Field>
        <Field label="基数">
          <select aria-label="基数" value={text(document.cardinality) || "ONE"} onChange={(event) => onChange({ ...document, cardinality: event.target.value })}>
            <option value="ONE">{cardinalityLabel("ONE")}</option>
            <option value="MANY">{cardinalityLabel("MANY")}</option>
          </select>
        </Field>
        <div className="relation-cardinality-callout">
          <span className="hint-pill">基数规则</span>
          <p>{cardinalityHint(sourceLabel, targetLabel, text(document.cardinality) || "ONE")}。目标实体为复合业务身份时，每个身份字段都必须有一条对应关系。</p>
        </div>
      </div>
      <div className="field-array relation-keys-section">
        <div className="field-array-head">
          <div className="field-array-title-wrap">
            <h3>业务键对应</h3>
            <span className="field-array-sub">定义起点实体的外键与终点实体主键映射</span>
          </div>
          <button className="secondary" onClick={addPair}>＋ 添加键对应</button>
        </div>
        <div className="relation-keys-list">
          {identity.map((pair, index) => (
            <div className="relation-key-row" key={`${text(pair.source)}:${text(pair.target)}:${index}`}>
              <div className="relation-key-col">
                <Field label={index === 0 ? "起点业务键" : `起点业务键 ${index + 1}`}>
                  <select aria-label={index === 0 ? "起点业务键" : `起点业务键 ${index + 1}`} value={text(pair.source)} onChange={(event) => updatePair(index, { source: event.target.value })}>
                    {sourceProps.map((item) => <option key={text(item.id)}>{text(item.id)}</option>)}
                  </select>
                </Field>
              </div>
              <div className="relation-key-arrow" title="关联到">→</div>
              <div className="relation-key-col">
                <Field label={index === 0 ? "终点业务键" : `终点业务键 ${index + 1}`}>
                  <select aria-label={index === 0 ? "终点业务键" : `终点业务键 ${index + 1}`} value={text(pair.target)} onChange={(event) => updatePair(index, { target: event.target.value })}>
                    {targetProps.map((item) => <option key={text(item.id)}>{text(item.id)}</option>)}
                  </select>
                </Field>
              </div>
              {identity.length > 1 ? (
                <button className="icon-button delete-key-btn" aria-label={`删除键对应 ${index + 1}`} title="删除键对应" onClick={() => onChange({ ...document, identity: identity.filter((_, position) => position !== index) })}>×</button>
              ) : <div className="icon-button-placeholder" />}
            </div>
          ))}
        </div>
      </div>
    </>
  );
}

export function RuleFields({ document, documents, onChange }: { document: DraftDocument; documents: DraftDocument[]; onChange: (next: DraftDocument) => void }) {
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
  const binary = ["eq", "ne", "lt", "le", "gt", "ge", "add", "sub", "mul", "div", "and", "or", "bool"];
  const metrics = documents.filter((item) => item.kind === "Metric");
  const propertyRefs = documents.filter((item) => item.kind === "ObjectType").flatMap((item) =>
    (array(item.properties) as Record<string, unknown>[]).map((property) => `${item.id}.${text(property.id)}`),
  );
  const firstMetric = metrics[0]?.id ?? "";
  const firstProperty = propertyRefs[0] ?? "";
  function addInput() {
    if (firstMetric) {
      onChange({ ...document, inputs: [...inputs, { name: "input", metric: firstMetric, required: true }] });
      return;
    }
    if (firstProperty) {
      const separator = firstProperty.lastIndexOf(".");
      onChange({
        ...document,
        inputs: [...inputs, {
          name: "input",
          objectType: firstProperty.slice(0, separator),
          property: firstProperty.slice(separator + 1),
          required: true,
        }],
      });
      return;
    }
    onChange({ ...document, inputs: [...inputs, { name: "input", required: true }] });
  }
  return <><div className="field-array"><div className="field-array-head"><h3>规则输入</h3><button className="secondary" onClick={addInput}>添加输入</button></div>{inputs.map((input, index) => { const sourceKind = input.metric ? "metric" : "property"; const source = sourceKind === "metric" ? text(input.metric) : `${text(input.objectType)}.${text(input.property)}`; return <div className="rule-input-row" key={`${text(input.name)}:${index}`}><input aria-label="输入名称" value={text(input.name)} onChange={(event) => updateInput(index, { name: event.target.value })} /><select aria-label="输入类型" value={sourceKind} onChange={(event) => setInputSource(index, event.target.value, sourceKind === "metric" ? firstMetric : propertyRefs[0] ?? "")}><option value="metric">指标</option><option value="property">实体属性</option></select><select aria-label="输入语义引用" value={source} onChange={(event) => setInputSource(index, sourceKind, event.target.value)}>{sourceKind === "metric" ? metrics.map((item) => <option key={item.id} value={item.id}>{String(item.label || item.id)}</option>) : propertyRefs.map((item) => <option key={item}>{item}</option>)}</select><label className="check-field"><input type="checkbox" checked={input.required !== false} onChange={(event) => updateInput(index, { required: event.target.checked })} />必需</label><button className="icon-button" aria-label={`删除输入 ${text(input.name)}`} onClick={() => onChange({ ...document, inputs: inputs.filter((_, position) => position !== index) })}>×</button></div>; })}</div><div className="expression-builder"><h3>判断表达式</h3><div className="form-grid"><Field label="运算"><select aria-label="运算" value={text(expression.op)} onChange={(event) => updateExpression({ op: event.target.value, args: args.length >= 2 ? args : [{ op: "ref", name: inputNames[0] ?? "" }, { op: "ref", name: inputNames[1] ?? inputNames[0] ?? "" }] })}>{binary.map((op) => <option key={op}>{op}</option>)}</select></Field><Field label="左输入"><select aria-label="左输入" value={text(args[0]?.name)} onChange={(event) => updateArg(0, event.target.value)}>{inputNames.map((name) => <option key={name}>{name}</option>)}</select></Field><Field label="右输入"><select aria-label="右输入" value={text(args[1]?.name)} onChange={(event) => updateArg(1, event.target.value)}>{inputNames.map((name) => <option key={name}>{name}</option>)}</select></Field></div></div></>;
}

export function ActionFields({
  document,
  objects,
  onChange,
  allDocuments,
  onDocumentsChange,
}: {
  document: DraftDocument;
  objects: DraftDocument[];
  onChange: (next: DraftDocument) => void;
  allDocuments?: DraftDocument[];
  onDocumentsChange?: (docs: DraftDocument[]) => void;
}) {
  const parameters = array(document.parameters) as Record<string, unknown>[];
  const binding = allDocuments?.find((d) => d.kind === "ActionBinding" && d.action === document.id);

  function updateParam(index: number, patch: Record<string, unknown>) {
    onChange({ ...document, parameters: parameters.map((item, position) => position === index ? { ...item, ...patch } : item) });
  }

  function handleApiLinkChange(val: string) {
    if (!allDocuments || !onDocumentsChange) return;
    if (!val) {
      // Detach binding
      onDocumentsChange(allDocuments.filter((d) => !(d.kind === "ActionBinding" && d.action === document.id)));
      return;
    }
    const [sourceId, method, path, opId] = val.split(":");
    const newBinding: DraftDocument = {
      apiVersion: "semaloom/v0.1",
      kind: "ActionBinding",
      id: `${document.id}.openapi`,
      version: "1.0.0",
      action: document.id,
      sourceId: sourceId || "proc_draft_api",
      provider: "openapi",
      idempotent: true,
      reconcilable: true,
      physical: {
        operationId: opId || "createPurchaseDraft",
        method: method || "POST",
        path: path || "/drafts",
      },
    };
    const withoutExisting = allDocuments.filter((d) => !(d.kind === "ActionBinding" && d.action === document.id));
    onDocumentsChange([...withoutExisting, newBinding]);
  }

  const phys = (binding?.physical || {}) as Record<string, unknown>;
  const bindingMethod = String(phys.method || "POST");
  const bindingPath = String(phys.path || "/drafts");
  const bindingOpId = String(phys.operationId || "");
  const bindingSourceId = String(binding?.sourceId || "");

  const currentBindingVal = binding
    ? `${bindingSourceId}:${bindingMethod}:${bindingPath}:${bindingOpId}`
    : "";

  return (
    <>
      <div className="form-grid">
        <Field label="目标实体">
          <select value={text(document.targetObject)} onChange={(event) => onChange({ ...document, targetObject: event.target.value })}>
            {objects.map(option)}
          </select>
        </Field>
        <Field label="关联外部 API 接口 (可选)">
          <select
            aria-label="关联外部 API 接口"
            value={currentBindingVal}
            onChange={(e) => handleApiLinkChange(e.target.value)}
          >
            <option value="">无关联 (纯内部语义操作)</option>
            <option value="proc_draft_api:POST:/drafts:createPurchaseDraft">
              proc_draft_api: POST /drafts (采购草稿单下发)
            </option>
            <option value="proc_draft_api:GET:/order-risk:getOrderRisk">
              proc_draft_api: GET /order-risk (履约风险接口)
            </option>
          </select>
        </Field>
      </div>

      {binding ? (
        <div className="action-api-bound-notice">
          <span className="method-badge post">{bindingMethod}</span>
          <code>{bindingPath}</code>
          <span className="bound-source-tag">{bindingSourceId}</span>
          <span className="bound-status-tag">已绑定外部微服务</span>
        </div>
      ) : null}

      <Field label="效果说明"><textarea rows={3} value={text(document.effect)} onChange={(event) => onChange({ ...document, effect: event.target.value })} /></Field>
      <Field label="前提 Claim / Rule（逗号分隔）"><input value={array(document.preconditions).join(", ")} onChange={(event) => onChange({ ...document, preconditions: csv(event.target.value) })} /></Field>
      <div className="field-array">
        <div className="field-array-head"><h3>参数</h3><button className="secondary" onClick={() => onChange({ ...document, parameters: [...parameters, { name: "param", valueType: "STRING", required: true }] })}>添加参数</button></div>
        {parameters.map((parameter, index) => (
          <div className="property-row" key={`${text(parameter.name)}:${index}`}>
            <input aria-label="参数名称" value={text(parameter.name)} onChange={(event) => updateParam(index, { name: event.target.value })} />
            <input aria-label="参数显示名" value={text(parameter.label)} placeholder="显示名称" onChange={(event) => updateParam(index, { label: event.target.value })} />
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

function csv(value: string): string[] { return value.split(",").map((item) => item.trim()).filter(Boolean); }
