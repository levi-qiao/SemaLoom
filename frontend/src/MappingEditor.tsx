import { useEffect, useMemo, useState } from "react";

import { apiHeaders, checkedJson } from "./api";
import {
  array,
  emptyMappingPhysical,
  emptyMetricPhysical,
  isOpenApi,
  mappingResourceLabel,
  metricById,
  object,
  rehomeMapping,
  replaceDocument,
  text,
} from "./doc";
import { draftPreviewHint, previewOutcomeText } from "./labels";
import type { DraftDocument, SourceProfileSummary, SourceResource } from "./types";

type Preview = {
  kind: string;
  reason: string | null;
  fields: { semanticField: string; physicalField: string; value: string | null }[];
};

type Props = {
  mapping: DraftDocument;
  objectType?: DraftDocument;
  documents: DraftDocument[];
  profiles: SourceProfileSummary[];
  compact?: boolean;
  saved: boolean;
  savedRevision: number;
  onChange: (documents: DraftDocument[]) => void;
  onError: (message: string | null) => void;
};

export function MappingEditor({
  mapping,
  objectType,
  documents,
  profiles,
  compact = false,
  saved,
  savedRevision,
  onChange,
  onError,
}: Props) {
  const physical = object(mapping.physical);
  const api = isOpenApi(mapping.provider);
  const sourceId = text(mapping.sourceId);
  const metric = metricById(documents, mapping.target);
  const metricMode = metric !== null;
  const [resources, setResources] = useState<SourceResource[]>([]);
  const [schemaReason, setSchemaReason] = useState<string | null>(null);
  const [identity, setIdentity] = useState("");
  const [bindings, setBindings] = useState<Record<string, string>>({});
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [activeField, setActiveField] = useState("");
  const [tableRows, setTableRows] = useState<Record<string, string | null>[]>([]);
  const [rowsReason, setRowsReason] = useState<string | null>(null);
  const [pickedRow, setPickedRow] = useState<number | null>(null);

  useEffect(() => {
    setPreview(null);
    setPreviewError(null);
    if (!sourceId) {
      setResources([]);
      setSchemaReason(null);
      return;
    }
    void fetch(`/v0.1/studio/source-profiles/${encodeURIComponent(sourceId)}/schema`)
      .then(checkedJson)
      .then((payload) => {
        setResources(payload.resources ?? []);
        setSchemaReason(payload.reason ?? null);
      })
      .catch(() => {
        setResources([]);
        setSchemaReason("SOURCE_UNAVAILABLE");
      });
  }, [sourceId, mapping.id]);

  useEffect(() => {
    setPreview(null);
    setPreviewError(null);
  }, [mapping.physical, saved]);

  useEffect(() => {
    setBindings({});
    setIdentity("");
    setActiveField(identityKeys[0] ?? "");
    setTableRows([]);
    setRowsReason(null);
    setPickedRow(null);
  }, [mapping.id]);

  const tables = resources.filter((item) => item.kind === "table" || (!item.kind && !item.method));
  const operations = resources.filter((item) => item.kind === "operation" || item.method === "GET");
  const table = text(physical.table);
  const path = text(physical.path);
  const selectedTable = tables.find((item) => item.name === table || item.id.endsWith(`.${table}`));
  const selectedOperation = operations.find((item) => item.name === path || item.id === text(physical.operationId));
  const columns = api ? selectedOperation?.columns ?? [] : selectedTable?.columns ?? [];
  const parameters = selectedOperation?.parameters ?? [];
  const properties = array(objectType?.properties) as Record<string, unknown>[];
  const identityKeys = array(objectType?.identityKeys).map(String);
  const grain = object(api ? physical.grainPointers : physical.grainColumns);
  const propertyBindings = object(api ? physical.propertyPointers : physical.propertyColumns);
  const filters = object(physical.filters);
  const hasResource = api ? Boolean(path || text(physical.operationId)) : Boolean(table);
  const boundColumns = useMemo(() => {
    const found = new Set<string>();
    for (const value of Object.values({ ...grain, ...propertyBindings })) {
      if (value) found.add(String(value));
    }
    if (text(physical.identityColumn)) found.add(text(physical.identityColumn));
    if (text(physical.valueColumn)) found.add(text(physical.valueColumn));
    return found;
  }, [grain, propertyBindings, physical.identityColumn, physical.valueColumn]);
  const extraBindings = useMemo(
    () => requiredPreviewBindings(physical, metricMode, identityKeys),
    [physical, metricMode, identityKeys],
  );
  const extrasFilled = extraBindings.every((dim) => Boolean(text(bindings[dim]).trim()));
  const canPreview = saved && Boolean(identity.trim()) && hasResource && extrasFilled;
  const tableSchema = selectedTable?.schema ?? null;

  useEffect(() => {
    if (api || !sourceId || !table) {
      setTableRows([]);
      setRowsReason(null);
      return;
    }
    void fetch(`/v0.1/studio/source-profiles/${encodeURIComponent(sourceId)}/rows`, {
      method: "POST",
      headers: apiHeaders(),
      body: JSON.stringify({ table, schema: tableSchema, limit: 20 }),
    })
      .then(checkedJson)
      .then((payload) => {
        setTableRows(payload.rows ?? []);
        setRowsReason(payload.reason ?? null);
      })
      .catch(() => {
        setTableRows([]);
        setRowsReason("SAMPLE_UNAVAILABLE");
      });
  }, [api, sourceId, table, tableSchema]);

  function patch(next: DraftDocument) {
    onChange(replaceDocument(documents, next));
  }

  function setPhysical(nextPhysical: Record<string, unknown>) {
    patch({ ...mapping, physical: nextPhysical });
  }

  function setSource(nextId: string) {
    const profile = profiles.find((item) => item.sourceId === nextId);
    const provider = profile?.provider ?? "postgres";
    const identityKey = identityKeys[0] ?? "id";
    const nextMapping = {
      ...mapping,
      sourceId: nextId,
      provider,
      physical: metric
        ? emptyMetricPhysical(provider, identityKey, array(metric.grain).map(String))
        : emptyMappingPhysical(provider, identityKey),
    };
    onChange(rehomeMapping(replaceDocument(documents, nextMapping), nextMapping.id, nextId, provider));
  }

  function selectTable(nextTable: string) {
    const resource = tables.find((item) => item.name === nextTable);
    const schema = resource?.schema && resource.schema !== "public" ? resource.schema : undefined;
    setPhysical(
      postgresPhysical(physical, {
        table: nextTable,
        schema,
      }, metricMode),
    );
  }

  function selectOperation(nextPath: string) {
    const resource = operations.find((item) => item.name === nextPath);
    const identityKey = identityKeys[0] ?? "id";
    const parameter = resource?.parameters?.[0]?.name || text(physical.identityParameter) || identityKey;
    setPhysical(
      openApiPhysical(physical, {
        path: nextPath,
        operationId: resource?.operationId || resource?.id || "",
        identityParameter: parameter,
      }, metricMode),
    );
  }

  function setBinding(semantic: string, value: string, identityField: boolean) {
    if (api) {
      const grainPointers = { ...grain };
      const propertyPointers = { ...propertyBindings };
      if (identityField || grain[semantic] !== undefined) {
        grainPointers[semantic] = value;
        setPhysical(
          openApiPhysical(physical, {
            identityPointer: identityField ? value : physical.identityPointer,
            grainPointers,
          }, metricMode),
        );
        return;
      }
      if (value) propertyPointers[semantic] = value;
      else delete propertyPointers[semantic];
      setPhysical(openApiPhysical(physical, { propertyPointers }, metricMode));
      return;
    }
    if (identityField || grain[semantic] !== undefined) {
      setPhysical(
        postgresPhysical(physical, {
          identityColumn: identityField ? value : physical.identityColumn,
          grainColumns: { ...grain, [semantic]: value },
        }, metricMode),
      );
      return;
    }
    const next = { ...propertyBindings };
    if (value) next[semantic] = value;
    else delete next[semantic];
    setPhysical(postgresPhysical(physical, { propertyColumns: next }, metricMode));
  }

  function pickColumn(column: string) {
    const semantic = activeField || identityKeys[0];
    if (!semantic) return;
    setActiveField(semantic);
    setBinding(semantic, column, identityKeys.includes(semantic));
  }

  function pickRow(index: number, row: Record<string, string | null>) {
    setPickedRow(index);
    const identityCol = text(physical.identityColumn) || columns[0]?.name;
    const value = identityCol ? row[identityCol] : null;
    if (value) setIdentity(String(value));
  }

  function setFilter(previousKey: string, nextKey: string, value: string) {
    const next = { ...filters };
    if (previousKey !== nextKey) delete next[previousKey];
    if (nextKey) next[nextKey] = value;
    else delete next[nextKey];
    setPhysical(postgresPhysical(physical, { filters: next }, true));
  }

  async function runPreview() {
    if (!canPreview) return;
    setBusy(true);
    setPreview(null);
    setPreviewError(null);
    onError(null);
    try {
      const extra: Record<string, string> = {};
      for (const dim of extraBindings) {
        const value = text(bindings[dim]).trim();
        if (value) extra[dim] = value;
      }
      const payload = await fetch("/v0.1/studio/sample", {
        method: "POST",
        headers: apiHeaders(),
        body: JSON.stringify({
          mappingId: mapping.id,
          identity,
          draftId: "default",
          bindings: extra,
        }),
      }).then(checkedJson);
      const result = payload as Preview;
      setPreview(result);
      if (result.kind !== "PRESENT") {
        setPreviewError(previewOutcomeText(text(mapping.provider), result.kind, result.reason));
      }
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : "UNKNOWN_ERROR";
      const failure = previewFailureFromHttp(text(mapping.provider), message);
      setPreviewError(failure);
      onError(failure);
    } finally {
      setBusy(false);
    }
  }

  const grainDims = metricMode
    ? (array(metric?.grain).map(String).length ? array(metric?.grain).map(String) : Object.keys(grain))
    : [];

  const previewPane = compact || api ? null : (
    <div className="mapping-preview">
      <div className="mapping-preview-head">
        <strong>{table || "表预览"}</strong>
        <small>
          {activeField
            ? `点列名绑定到「${text(properties.find((item) => text(item.id) === activeField)?.label) || activeField}」；点行填入试读键`
            : "先点左侧属性，再点列名绑定"}
        </small>
      </div>
      {columns.length ? (
        <div className="mapping-preview-table">
          <table>
            <thead>
              <tr>
                {columns.map((column) => (
                  <th key={column.name}>
                    <button
                      type="button"
                      className={"mapping-col" + (boundColumns.has(column.name) ? " is-bound" : "")}
                      aria-label={`绑定 ${column.name}`}
                      onClick={() => pickColumn(column.name)}
                    >
                      {column.name}
                      <small>{column.type}</small>
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tableRows.length ? tableRows.map((row, index) => (
                <tr
                  key={index}
                  className={pickedRow === index ? "is-picked" : undefined}
                  onClick={() => pickRow(index, row)}
                >
                  {columns.map((column) => (
                    <td key={column.name}>{row[column.name] ?? "—"}</td>
                  ))}
                </tr>
              )) : (
                <tr>
                  <td colSpan={Math.max(columns.length, 1)}>
                    {rowsReason === "SAMPLE_UNAVAILABLE" || rowsReason === "SOURCE_UNAVAILABLE"
                      ? "样本行暂时读不到，仍可点列名绑定。"
                      : "还没有样本行。点列名即可绑定字段。"}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="mapping-hint">{table ? "此表还没有列清单。" : "选择表后，这里列出字段和样本，点选即可绑定。"}</p>
      )}
    </div>
  );

  return (
    <article className="bind-card mapping-card">
      <strong>{String(mapping.label || mapping.target || mapping.id)}</strong>
      <small>{mappingResourceLabel(mapping)}</small>
      <div className={compact ? "mapping-stack" : "mapping-split"}>
      <div className="mapping-bind">
      {compact ? (
        <p className="mapping-hint">{sourceId || "未选来源"} / {mappingResourceLabel(mapping)}</p>
      ) : (
        <div className="form-grid">
          <label className="form-field">
            <span>数据源</span>
            <select aria-label="数据源" value={sourceId} onChange={(event) => setSource(event.target.value)}>
              {profiles.map((item) => (
                <option key={item.sourceId} value={item.sourceId}>{item.label}</option>
              ))}
            </select>
          </label>
          {api ? (
            <label className="form-field">
              <span>接口</span>
              <select aria-label="接口" value={path} onChange={(event) => selectOperation(event.target.value)}>
                <option value="">选择已授权 GET 操作</option>
                {path && !operations.some((item) => item.name === path || item.id === path) ? (
                  <option value={path}>{path}</option>
                ) : null}
                {operations.map((item) => (
                  <option key={item.id} value={item.name}>
                    {item.method ?? "GET"} {item.name}{item.operationId ? ` · ${item.operationId}` : ""}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <label className="form-field">
              <span>表</span>
              <select aria-label="数据表" value={table} onChange={(event) => selectTable(event.target.value)}>
                <option value="">选择表</option>
                {tables.map((item) => (
                  <option key={item.id} value={item.name}>
                    {item.schema && item.schema !== "public" ? `${item.schema}.${item.name}` : item.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          {!compact && api ? (
            <label className="form-field">
              <span>身份参数</span>
              <select
                aria-label="身份参数"
                value={text(physical.identityParameter)}
                onChange={(event) =>
                  setPhysical(openApiPhysical(physical, { identityParameter: event.target.value }, metricMode))
                }
              >
                {(parameters.length ? parameters : identityKeys.map((item) => ({ name: item }))).map((item) => (
                  <option key={item.name} value={item.name}>{item.name}</option>
                ))}
              </select>
            </label>
          ) : null}
        </div>
      )}
      {compact ? null : metricMode ? (
        <>
          {api ? (
            <label className="form-field">
              <span>取值指针</span>
              <select
                aria-label="取值指针"
                value={text(physical.valuePointer)}
                onChange={(event) => setPhysical(openApiPhysical(physical, { valuePointer: event.target.value }, true))}
              >
                <option value="">选择响应字段</option>
                {columns.map((column) => (
                  <option key={column.name} value={column.name}>{column.name}</option>
                ))}
              </select>
            </label>
          ) : (
            <label className="form-field">
              <span>取值列</span>
              <select
                aria-label="取值列"
                value={text(physical.valueColumn)}
                onChange={(event) => setPhysical(postgresPhysical(physical, { valueColumn: event.target.value }, true))}
              >
                <option value="">选择列</option>
                {columns.map((column) => (
                  <option key={column.name} value={column.name}>{column.name}</option>
                ))}
              </select>
            </label>
          )}
          <label className="form-field">
            <span>Mapping 口径</span>
            <input
              aria-label="Mapping 口径"
              value={text(mapping.perspective)}
              placeholder="例如 TAX_RETURN，可留空"
              onChange={(event) => {
                const value = event.target.value;
                const next = { ...mapping };
                if (value) next.perspective = value;
                else delete next.perspective;
                patch(next);
              }}
            />
          </label>
          {grainDims.map((semantic) => {
            const identityField = identityKeys.includes(semantic);
            const value = text(grain[semantic]) || (identityField ? text(physical.identityColumn) : "");
            return (
              <div className="mapping-pair-row" key={semantic}>
                <span>
                  <strong>{semantic}</strong>
                  <small>{identityField ? "业务键" : "粒度"}</small>
                </span>
                <i>→</i>
                <select
                  aria-label={`${semantic} ${api ? "响应字段" : "列"}`}
                  value={value}
                  onChange={(event) => setBinding(semantic, event.target.value, identityField)}
                >
                  <option value="">{api ? "此接口无此字段" : "此表无此字段"}</option>
                  {columns.map((column) => (
                    <option key={column.name} value={column.name}>{column.name}</option>
                  ))}
                </select>
              </div>
            );
          })}
          {api ? null : (
            <div className="field-array">
              <div className="field-array-head">
                <h3>固定筛选</h3>
                <button
                  className="secondary"
                  onClick={() => {
                    const column = columns.find((item) => !filters[item.name])?.name || "metric";
                    setFilter("", column, text(filters[column]));
                  }}
                >
                  添加筛选
                </button>
              </div>
              {Object.entries(filters).map(([column, value]) => (
                <div className="mapping-pair-row filter-row" key={column}>
                  <select
                    aria-label={`${column} 筛选列`}
                    value={column}
                    onChange={(event) => setFilter(column, event.target.value, String(value ?? ""))}
                  >
                    {(!columns.some((item) => item.name === column) ? [{ name: column }] : []).concat(columns).map((item) => (
                      <option key={item.name} value={item.name}>{item.name}</option>
                    ))}
                  </select>
                  <i>→</i>
                  <input
                    aria-label={`${column} 筛选值`}
                    value={String(value ?? "")}
                    onChange={(event) => setFilter(column, column, event.target.value)}
                  />
                  <button className="icon-button" aria-label={`删除筛选 ${column}`} onClick={() => setFilter(column, "", "")}>×</button>
                </div>
              ))}
            </div>
          )}
        </>
      ) : (
        <>
          <div className="pair-list">
          {properties.filter((property) => identityKeys.includes(text(property.id)) || text(grain[text(property.id)]) || text(propertyBindings[text(property.id)])).map((property) => {
            const semantic = text(property.id);
            const identityField = identityKeys.includes(semantic);
            const value = text(grain[semantic]) || text(propertyBindings[semantic]);
            return (
              <div className={"pair-item" + (activeField === semantic ? " is-active" : "")} key={semantic} onClick={() => setActiveField(semantic)}>
                <span className="pair-label">
                  <strong>{text(property.label) || semantic}</strong>
                  <small>{identityField ? "业务键" : text(property.unit) || "属性"}</small>
                </span>
                <select aria-label={`${semantic} ${api ? "响应字段" : "列"}`} value={value} onChange={(event) => setBinding(semantic, event.target.value, identityField)}>
                  <option value="">{api ? "此接口无此字段" : "此表无此字段"}</option>
                  {fieldOptions(columns, value).map((column) => (
                    <option key={column.name} value={column.name}>{column.name}</option>
                  ))}
                </select>
              </div>
            );
          })}
          </div>
          {properties.filter((property) => !identityKeys.includes(text(property.id)) && !text(grain[text(property.id)]) && !text(propertyBindings[text(property.id)])).length ? (
            <details>
              <summary className="mapping-hint">此来源没有的字段</summary>
              <div className="pair-list">
              {properties.filter((property) => !identityKeys.includes(text(property.id)) && !text(grain[text(property.id)]) && !text(propertyBindings[text(property.id)])).map((property) => {
                const semantic = text(property.id);
                return (
                  <div className={"pair-item" + (activeField === semantic ? " is-active" : "")} key={semantic} onClick={() => setActiveField(semantic)}>
                    <span className="pair-label">
                      <strong>{text(property.label) || semantic}</strong>
                      <small>{api ? "接口可留空" : "表可留空"}</small>
                    </span>
                    <select aria-label={`${semantic} ${api ? "响应字段" : "列"}`} value="" onChange={(event) => setBinding(semantic, event.target.value, false)}>
                      <option value="">{api ? "此接口无此字段" : "此表无此字段"}</option>
                      {columns.map((column) => (
                        <option key={column.name} value={column.name}>{column.name}</option>
                      ))}
                    </select>
                  </div>
                );
              })}
              </div>
            </details>
          ) : null}
        </>
      )}
      {!compact && api && !columns.length ? (
        <p className="mapping-hint">
          {schemaReason === "SPEC_UNAVAILABLE"
            ? "接口清单暂时读不到，下面保留已保存的字段对应。"
            : "当前操作未提供响应字段清单，已保存的对应仍可用。"}
        </p>
      ) : null}
      <label className="form-field">
        <span>试读业务键</span>
        <input value={identity} placeholder="例如 PO-001" onChange={(event) => setIdentity(event.target.value)} />
      </label>
      {extraBindings.map((dim) => (
        <label className="form-field" key={dim}>
          <span>试读 {dim}</span>
          <input
            aria-label={`试读 ${dim}`}
            value={text(bindings[dim])}
            onChange={(event) => setBindings((current) => ({ ...current, [dim]: event.target.value }))}
          />
        </label>
      ))}
      <button
        className="secondary"
        disabled={busy || !canPreview}
        onClick={() => void runPreview()}
      >
        试读
      </button>
      {saved ? (
        <p className="mapping-hint">{draftPreviewHint(true, savedRevision)}</p>
      ) : (
        <p className="notice">{draftPreviewHint(false, savedRevision)}</p>
      )}
      {previewError ? <p className="field-error" role="alert">{previewError}</p> : null}
      {preview ? (
        <p className="mapping-hint">
          草稿预览 · {previewOutcomeText(text(mapping.provider), preview.kind, preview.reason)}
          {preview.reason ? ` · ${preview.reason}` : ""}
          {preview.fields.filter((item) => item.value).length
            ? ` · ${preview.fields.filter((item) => item.value).map((item) => `${item.semanticField}=${item.value}`).join("，")}`
            : ""}
        </p>
      ) : null}
      </div>
      {previewPane}
      </div>
    </article>
  );
}

export function bindObjectColumn(
  mapping: DraftDocument,
  semantic: string,
  column: string,
  identityField: boolean,
): DraftDocument {
  const physical = object(mapping.physical);
  if (isOpenApi(mapping.provider)) {
    const grain = object(physical.grainPointers);
    const props = object(physical.propertyPointers);
    if (identityField || grain[semantic] !== undefined) {
      const grainPointers = { ...grain, [semantic]: column };
      if (!column) delete grainPointers[semantic];
      return {
        ...mapping,
        physical: openApiPhysical(physical, {
          identityPointer: identityField ? column : physical.identityPointer,
          grainPointers,
        }, false),
      };
    }
    const propertyPointers = { ...props };
    if (column) propertyPointers[semantic] = column;
    else delete propertyPointers[semantic];
    return { ...mapping, physical: openApiPhysical(physical, { propertyPointers }, false) };
  }
  const grain = object(physical.grainColumns);
  const props = object(physical.propertyColumns);
  if (identityField || grain[semantic] !== undefined) {
    const grainColumns = { ...grain, [semantic]: column };
    if (!column) delete grainColumns[semantic];
    return {
      ...mapping,
      physical: postgresPhysical(physical, {
        identityColumn: identityField ? column : physical.identityColumn,
        grainColumns,
      }, false),
    };
  }
  const propertyColumns = { ...props };
  if (column) propertyColumns[semantic] = column;
  else delete propertyColumns[semantic];
  return { ...mapping, physical: postgresPhysical(physical, { propertyColumns }, false) };
}

function fieldOptions(columns: { name: string }[], current: string) {
  if (current && !columns.some((item) => item.name === current)) {
    return [{ name: current }, ...columns];
  }
  return columns;
}

function postgresPhysical(
  physical: Record<string, unknown>,
  patch: Record<string, unknown>,
  metricMode: boolean,
): Record<string, unknown> {
  const next: Record<string, unknown> = {
    table: patch.table !== undefined ? patch.table : physical.table,
    tenantColumn: patch.tenantColumn !== undefined ? patch.tenantColumn : (physical.tenantColumn ?? "tenant_id"),
    identityColumn: patch.identityColumn !== undefined ? patch.identityColumn : physical.identityColumn,
    grainColumns: patch.grainColumns !== undefined ? patch.grainColumns : object(physical.grainColumns),
  };
  const schema = patch.schema !== undefined ? patch.schema : physical.schema;
  if (schema) next.schema = schema;
  const propertyColumns = patch.propertyColumns !== undefined ? patch.propertyColumns : object(physical.propertyColumns);
  if (!metricMode || Object.keys(object(propertyColumns)).length) next.propertyColumns = propertyColumns;
  if (metricMode || physical.valueColumn !== undefined || patch.valueColumn !== undefined) {
    next.valueColumn = patch.valueColumn !== undefined ? patch.valueColumn : physical.valueColumn;
  }
  if (metricMode || physical.filters !== undefined || patch.filters !== undefined) {
    next.filters = patch.filters !== undefined ? patch.filters : object(physical.filters);
  }
  return next;
}

function openApiPhysical(
  physical: Record<string, unknown>,
  patch: Record<string, unknown>,
  metricMode: boolean,
): Record<string, unknown> {
  const next: Record<string, unknown> = {
    method: "GET",
    path: patch.path !== undefined ? patch.path : physical.path,
    operationId: patch.operationId !== undefined ? patch.operationId : physical.operationId,
    identityParameter: patch.identityParameter !== undefined ? patch.identityParameter : physical.identityParameter,
    identityPointer: patch.identityPointer !== undefined ? patch.identityPointer : physical.identityPointer,
    grainPointers: patch.grainPointers !== undefined ? patch.grainPointers : object(physical.grainPointers),
  };
  const propertyPointers = patch.propertyPointers !== undefined ? patch.propertyPointers : object(physical.propertyPointers);
  if (!metricMode || Object.keys(object(propertyPointers)).length) next.propertyPointers = propertyPointers;
  if (metricMode || physical.valuePointer !== undefined || patch.valuePointer !== undefined) {
    next.valuePointer = patch.valuePointer !== undefined ? patch.valuePointer : physical.valuePointer;
  }
  return next;
}

function requiredPreviewBindings(
  physical: Record<string, unknown>,
  metricMode: boolean,
  identityKeys: string[],
): string[] {
  if (!metricMode) return [];
  if (physical.valueColumn == null && physical.valuePointer == null) return [];
  const locked = new Set(Object.keys(object(physical.filters)));
  const identityCol = text(physical.identityColumn);
  const grain = object(physical.grainColumns);
  const required: string[] = [];
  for (const [semantic, column] of Object.entries(grain)) {
    if (identityKeys.includes(semantic) || String(column) === identityCol || locked.has(semantic) || locked.has(String(column))) {
      continue;
    }
    required.push(semantic);
  }
  return required;
}

export function previewFailureFromHttp(provider: string, message: string) {
  const lower = message.toLowerCase();
  if (lower.includes("unavailable") || lower.includes("econnrefused") || lower.includes("network")) {
    return previewOutcomeText(provider, "UNAVAILABLE", "SOURCE_UNAVAILABLE");
  }
  return previewOutcomeText(provider, "UNAVAILABLE", message);
}

export function newMappingId(objectTypeId: string, sourceId: string, documents: DraftDocument[]) {
  let suffix = sourceId;
  let id = `${objectTypeId}.${suffix}`;
  let n = 2;
  while (documents.some((item) => item.id === id)) {
    suffix = `${sourceId}_${n}`;
    id = `${objectTypeId}.${suffix}`;
    n += 1;
  }
  return id;
}

export function makeMappingDocument(
  objectType: DraftDocument,
  sourceId: string,
  provider: string,
  documents: DraftDocument[],
): DraftDocument {
  const identityKey = String(array(objectType.identityKeys)[0] ?? "id");
  const existing = documents.filter((item) => item.kind === "Mapping" && item.target === objectType.id);
  return {
    apiVersion: "semaloom/v0.1",
    kind: "Mapping",
    id: newMappingId(objectType.id, sourceId, documents),
    version: "1.0.0",
    label: String(objectType.label ?? objectType.id),
    target: objectType.id,
    objectType: objectType.id,
    sourceId,
    provider,
    expectedCardinality: "ONE",
    completeness: existing.length ? "PARTIAL" : "AUTHORITATIVE",
    physical: emptyMappingPhysical(provider, identityKey),
  };
}

export function makeMetricMappingDocument(
  metric: DraftDocument,
  objectType: DraftDocument,
  sourceId: string,
  provider: string,
  documents: DraftDocument[],
): DraftDocument {
  const identityKey = String(array(objectType.identityKeys)[0] ?? "id");
  const grain = array(metric.grain).map(String);
  const perspective = text(metric.perspective);
  return {
    apiVersion: "semaloom/v0.1",
    kind: "Mapping",
    id: newMappingId(metric.id, sourceId, documents),
    version: "1.0.0",
    label: String(metric.label ?? metric.id),
    target: metric.id,
    objectType: objectType.id,
    sourceId,
    provider,
    expectedCardinality: "ONE",
    completeness: "AUTHORITATIVE",
    ...(perspective ? { perspective } : {}),
    physical: emptyMetricPhysical(provider, identityKey, grain),
  };
}
