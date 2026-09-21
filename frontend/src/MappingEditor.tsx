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
import { useI18n } from "./i18n";
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
  const { t, locale } = useI18n();
  const physical = object(mapping.physical);
  const api = isOpenApi(mapping.provider);
  const sourceId = text(mapping.sourceId);
  const metric = metricById(documents, mapping.target);
  const metricMode = metric !== null;
  const [resources, setResources] = useState<SourceResource[]>([]);
  const [schemaReason, setSchemaReason] = useState<string | null>(null);
  const [identity, setIdentity] = useState<Record<string, string>>({});
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

  const tables = resources.filter((item) => item.kind === "table" || (!item.kind && !item.method));
  const operations = resources.filter((item) => item.kind === "operation" || item.method === "GET");
  const table = text(physical.table);
  const path = text(physical.path);
  const selectedTable = tables.find((item) => item.name === table || item.id.endsWith(`.${table}`));
  const selectedOperation = operations.find((item) => item.name === path || item.id === text(physical.operationId));
  const columns = api ? selectedOperation?.columns ?? [] : selectedTable?.columns ?? [];
  const parameters = selectedOperation?.parameters ?? [];
  const properties = array(objectType?.properties) as Record<string, unknown>[];
  const identityKeys = array(objectType?.identityKeys).map(String).filter(Boolean);
  const grain = object(api ? physical.grainPointers : physical.grainColumns);
  const propertyBindings = object(api ? physical.propertyPointers : physical.propertyColumns);
  const filters = object(physical.filters);
  const hasResource = api ? Boolean(path || text(physical.operationId)) : Boolean(table);

  useEffect(() => {
    setBindings({});
    setIdentity({});
    setActiveField(identityKeys[0] ?? "");
    setTableRows([]);
    setRowsReason(null);
    setPickedRow(null);
  }, [mapping.id]);

  const boundColumns = useMemo(() => {
    const found = new Set<string>();
    for (const value of Object.values({ ...grain, ...propertyBindings })) {
      if (value) found.add(String(value));
    }
    if (text(physical.valueColumn)) found.add(text(physical.valueColumn));
    return found;
  }, [grain, propertyBindings, physical.valueColumn]);
  const extraBindings = useMemo(
    () => requiredPreviewBindings(physical, metricMode, identityKeys),
    [physical, metricMode, identityKeys],
  );
  const extrasFilled = extraBindings.every((dim) => Boolean(text(bindings[dim]).trim()));
  const identityFilled = identityKeys.length > 0 && identityKeys.every((key) => Boolean(text(identity[key]).trim()));
  const canPreview = saved && identityFilled && hasResource && extrasFilled;
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
    const nextMapping = {
      ...mapping,
      sourceId: nextId,
      provider,
      physical: metric
        ? emptyMetricPhysical(provider, identityKeys, array(metric.grain).map(String))
        : emptyMappingPhysical(provider, identityKeys),
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
    const current = object(physical.parameterBindings);
    const parameterBindings = { ...current };
    identityKeys.forEach((key, index) => {
      const exact = resource?.parameters?.find((item) => item.name === key)?.name;
      const positional = resource?.parameters?.[index]?.name;
      parameterBindings[key] = exact || text(current[key]) || positional || key;
    });
    setPhysical(
      openApiPhysical(physical, {
        path: nextPath,
        operationId: resource?.operationId || resource?.id || "",
        parameterBindings,
      }, metricMode),
    );
  }

  function setBinding(semantic: string, value: string, identityField: boolean) {
    if (api) {
      const grainPointers = { ...grain };
      const propertyPointers = { ...propertyBindings };
      if (identityField || grain[semantic] !== undefined) {
        if (value) grainPointers[semantic] = value;
        else delete grainPointers[semantic];
        setPhysical(openApiPhysical(physical, { grainPointers }, metricMode));
        return;
      }
      if (value) propertyPointers[semantic] = value;
      else delete propertyPointers[semantic];
      setPhysical(openApiPhysical(physical, { propertyPointers }, metricMode));
      return;
    }
    if (identityField || grain[semantic] !== undefined) {
      const grainColumns = { ...grain };
      if (value) grainColumns[semantic] = value;
      else delete grainColumns[semantic];
      setPhysical(postgresPhysical(physical, { grainColumns }, metricMode));
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
    const nextIdentity: Record<string, string> = { ...identity };
    for (const key of identityKeys) {
      const column = text(grain[key]);
      const value = column ? row[column] : null;
      if (value != null) nextIdentity[key] = String(value);
    }
    setIdentity(nextIdentity);
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
        <strong>{table || t("mapping.tablePreview")}</strong>
        <small>
          {activeField
            ? t("mapping.pickColumnToBind", { name: text(properties.find((item) => text(item.id) === activeField)?.label) || activeField })
            : t("mapping.pickPropertyFirst")}
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
                      aria-label={t("mapping.bindCol", { name: column.name })}
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
                      ? t("mapping.noSampleRows")
                      : t("mapping.emptySampleRows")}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="mapping-hint">{table ? t("mapping.noColumnsInTable") : t("mapping.selectTableHint")}</p>
      )}
    </div>
  );

  const currentProfile = profiles.find((item) => item.sourceId === sourceId);
  const resourceLabel = mappingResourceLabel(mapping);

  return (
    <article className="bind-card mapping-card">
      {compact ? (
        <div className="compact-mapping-head">
          <div className="compact-mapping-title-row">
            <span className={`provider-badge ${api ? "openapi" : "postgres"}`}>
              {api ? "API" : "PG"}
            </span>
            <strong className="compact-mapping-title">{currentProfile?.label || sourceId || t("mapping.unselectedSource")}</strong>
          </div>
          <div className="compact-mapping-sub">
            <span className="compact-resource-type">{api ? t("mapping.resourceTypeApi") : t("mapping.resourceTypeTable")}</span>
            <code className="compact-resource-name">{resourceLabel}</code>
          </div>
        </div>
      ) : (
        <>
          <strong>{String(mapping.label || mapping.target || mapping.id)}</strong>
          <small>{resourceLabel}</small>
        </>
      )}
      <div className={compact ? "mapping-stack" : "mapping-split"}>
      <div className="mapping-bind">
      {compact ? (
        <div className="compact-mapping-summary">
          <span className="compact-bound-count">
            {Object.keys(propertyBindings).length + Object.keys(grain).length > 0
              ? t("mapping.configuredFieldsCount", { count: Object.keys(propertyBindings).length + Object.keys(grain).length })
              : t("mapping.pendingFields")}
          </span>
          {Object.keys(grain).length > 0 ? (
            <span className="compact-grain-tag">{t("mapping.grainKeys", { keys: Object.keys(grain).join(", ") })}</span>
          ) : null}
        </div>
      ) : (
        <div className="form-grid">
          <label className="form-field">
            <span>{t("mapping.dataSource")}</span>
            <select aria-label={t("mapping.dataSource")} value={sourceId} onChange={(event) => setSource(event.target.value)}>
              {profiles.map((item) => (
                <option key={item.sourceId} value={item.sourceId}>{item.label}</option>
              ))}
            </select>
          </label>
          {api ? (
            <label className="form-field">
              <span>{t("mapping.apiOperation")}</span>
              <select aria-label={t("mapping.apiOperation")} value={path} onChange={(event) => selectOperation(event.target.value)}>
                <option value="">{t("mapping.selectGetOp")}</option>
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
              <span>{t("mapping.table")}</span>
              <select aria-label={t("mapping.table")} value={table} onChange={(event) => selectTable(event.target.value)}>
                <option value="">{t("mapping.selectTable")}</option>
                {tables.map((item) => (
                  <option key={item.id} value={item.name}>
                    {item.schema && item.schema !== "public" ? `${item.schema}.${item.name}` : item.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          {!compact && api ? identityKeys.map((key) => (
            <label className="form-field" key={key}>
              <span>{t("mapping.param", { key })}</span>
              <select
                aria-label={t("mapping.param", { key })}
                value={text(object(physical.parameterBindings)[key])}
                onChange={(event) => {
                  const parameterBindings = {
                    ...object(physical.parameterBindings),
                    [key]: event.target.value,
                  };
                  setPhysical(openApiPhysical(physical, { parameterBindings }, metricMode));
                }}
              >
                {(parameters.length ? parameters : identityKeys.map((item) => ({ name: item }))).map((item) => (
                  <option key={item.name} value={item.name}>{item.name}</option>
                ))}
              </select>
            </label>
          )) : null}
        </div>
      )}
      {compact ? null : metricMode ? (
        <>
          {api ? (
            <label className="form-field">
              <span>{t("mapping.valuePointer")}</span>
              <select
                aria-label={t("mapping.valuePointer")}
                value={text(physical.valuePointer)}
                onChange={(event) => setPhysical(openApiPhysical(physical, { valuePointer: event.target.value }, true))}
              >
                <option value="">{t("mapping.selectResponseField")}</option>
                {columns.map((column) => (
                  <option key={column.name} value={column.name}>{column.name}</option>
                ))}
              </select>
            </label>
          ) : (
            <label className="form-field">
              <span>{t("mapping.valueColumn")}</span>
              <select
                aria-label={t("mapping.valueColumn")}
                value={text(physical.valueColumn)}
                onChange={(event) => setPhysical(postgresPhysical(physical, { valueColumn: event.target.value }, true))}
              >
                <option value="">{t("mapping.selectColumn")}</option>
                {columns.map((column) => (
                  <option key={column.name} value={column.name}>{column.name}</option>
                ))}
              </select>
            </label>
          )}
          <label className="form-field">
            <span>{t("mapping.perspective")}</span>
            <input
              aria-label={t("mapping.perspective")}
              value={text(mapping.perspective)}
              placeholder={t("mapping.perspectivePlaceholder")}
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
            const value = text(grain[semantic]);
            return (
              <div className="mapping-pair-row" key={semantic}>
                <span>
                  <strong>{semantic}</strong>
                  <small>{identityField ? t("mapping.businessKey") : t("mapping.grain")}</small>
                </span>
                <i>→</i>
                <select
                  aria-label={`${semantic} ${api ? t("mapping.responseField") : t("mapping.column")}`}
                  value={value}
                  onChange={(event) => setBinding(semantic, event.target.value, identityField)}
                >
                  <option value="">{api ? t("mapping.fieldNotPresentApi") : t("mapping.fieldNotPresentTable")}</option>
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
                <h3>{t("mapping.fixedFilters")}</h3>
                <button
                  className="secondary"
                  onClick={() => {
                    const column = columns.find((item) => !filters[item.name])?.name || "metric";
                    setFilter("", column, text(filters[column]));
                  }}
                >
                  {t("mapping.addFilter")}
                </button>
              </div>
              {Object.entries(filters).map(([column, value]) => (
                <div className="mapping-pair-row filter-row" key={column}>
                  <select
                    aria-label={t("mapping.filterColumn", { column })}
                    value={column}
                    onChange={(event) => setFilter(column, event.target.value, String(value ?? ""))}
                  >
                    {(!columns.some((item) => item.name === column) ? [{ name: column }] : []).concat(columns).map((item) => (
                      <option key={item.name} value={item.name}>{item.name}</option>
                    ))}
                  </select>
                  <i>→</i>
                  <input
                    aria-label={t("mapping.filterValue", { column })}
                    value={String(value ?? "")}
                    onChange={(event) => setFilter(column, column, event.target.value)}
                  />
                  <button className="icon-button" aria-label={t("mapping.deleteFilter", { column })} onClick={() => setFilter(column, "", "")}>×</button>
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
                  <small>{identityField ? t("mapping.businessKey") : text(property.unit) || t("mapping.property")}</small>
                </span>
                <select aria-label={`${semantic} ${api ? t("mapping.responseField") : t("mapping.column")}`} value={value} onChange={(event) => setBinding(semantic, event.target.value, identityField)}>
                  <option value="">{api ? t("mapping.fieldNotPresentApi") : t("mapping.fieldNotPresentTable")}</option>
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
              <summary className="mapping-hint">{t("mapping.unmappedFields")}</summary>
              <div className="pair-list">
              {properties.filter((property) => !identityKeys.includes(text(property.id)) && !text(grain[text(property.id)]) && !text(propertyBindings[text(property.id)])).map((property) => {
                const semantic = text(property.id);
                return (
                  <div className={"pair-item" + (activeField === semantic ? " is-active" : "")} key={semantic} onClick={() => setActiveField(semantic)}>
                    <span className="pair-label">
                      <strong>{text(property.label) || semantic}</strong>
                      <small>{api ? t("mapping.apiOptional") : t("mapping.tableOptional")}</small>
                    </span>
                    <select aria-label={`${semantic} ${api ? t("mapping.responseField") : t("mapping.column")}`} value="" onChange={(event) => setBinding(semantic, event.target.value, false)}>
                      <option value="">{api ? t("mapping.fieldNotPresentApi") : t("mapping.fieldNotPresentTable")}</option>
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
            ? t("mapping.specMissingHint")
            : t("mapping.noResponseSchemaHint")}
        </p>
      ) : null}
      {compact ? (
        <div className="compact-test-read">
          <div className="test-read-header">
            <span className="test-read-title">{t("mapping.sampleRead")}</span>
            {saved ? (
              <span className="test-read-hint">{draftPreviewHint(true, savedRevision)}</span>
            ) : (
              <span className="notice test-read-hint">{draftPreviewHint(false, savedRevision)}</span>
            )}
          </div>
          <div className="test-read-controls">
            {identityKeys.map((key) => (
              <label className="form-field inline-test-field" key={key}>
                <span className="test-field-label">{t("mapping.sampleKey", { key })}</span>
                <input
                  aria-label={t("mapping.sampleKey", { key })}
                  value={text(identity[key])}
                  placeholder={t("mapping.inputKey", { key })}
                  onChange={(event) => setIdentity((current) => ({ ...current, [key]: event.target.value }))}
                />
              </label>
            ))}
            {extraBindings.map((dim) => (
              <label className="form-field inline-test-field" key={dim}>
                <span className="test-field-label">{t("mapping.sampleDim", { dim })}</span>
                <input
                  aria-label={t("mapping.sampleDim", { dim })}
                  value={text(bindings[dim])}
                  placeholder={t("mapping.inputDim", { dim })}
                  onChange={(event) => setBindings((current) => ({ ...current, [dim]: event.target.value }))}
                />
              </label>
            ))}
            <button
              className="secondary test-read-btn"
              disabled={busy || !canPreview}
              onClick={() => void runPreview()}
            >
              {busy ? t("mapping.reading") : t("mapping.testRead")}
            </button>
          </div>
          {previewError ? <p className="field-error" role="alert">{previewError}</p> : null}
          {preview ? (
            <div className="preview-outcome-card">
              <span className="preview-outcome-badge">
                {previewOutcomeText(text(mapping.provider), preview.kind, preview.reason)}
              </span>
              {preview.reason ? <span className="preview-reason">{preview.reason}</span> : null}
              {preview.fields.filter((item) => item.value).length > 0 ? (
                <span className="preview-values">
                  {preview.fields
                    .filter((item) => item.value)
                    .map((item) => `${item.semanticField}=${item.value}`)
                    .join(", ")}
                </span>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : (
        <>
          {identityKeys.map((key) => (
            <label className="form-field" key={key}>
              <span>{t("mapping.sampleKey", { key })}</span>
              <input
                aria-label={t("mapping.sampleKey", { key })}
                value={text(identity[key])}
                placeholder={t("mapping.inputKey", { key })}
                onChange={(event) => setIdentity((current) => ({ ...current, [key]: event.target.value }))}
              />
            </label>
          ))}
          {extraBindings.map((dim) => (
            <label className="form-field" key={dim}>
              <span>{t("mapping.sampleDim", { dim })}</span>
              <input
                aria-label={t("mapping.sampleDim", { dim })}
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
            {t("mapping.testRead")}
          </button>
          {saved ? (
            <p className="mapping-hint">{draftPreviewHint(true, savedRevision)}</p>
          ) : (
            <p className="notice">{draftPreviewHint(false, savedRevision)}</p>
          )}
          {previewError ? <p className="field-error" role="alert">{previewError}</p> : null}
          {preview ? (
            <p className="mapping-hint">
              {t("mapping.testReadOutcome", { outcome: previewOutcomeText(text(mapping.provider), preview.kind, preview.reason) })}
              {preview.reason ? ` · ${preview.reason}` : ""}
              {preview.fields.filter((item) => item.value).length
                ? ` · ${preview.fields.filter((item) => item.value).map((item) => `${item.semanticField}=${item.value}`).join(", ")}`
                : ""}
            </p>
          ) : null}
        </>
      )}
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
        physical: openApiPhysical(physical, { grainPointers }, false),
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
      physical: postgresPhysical(physical, { grainColumns }, false),
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
    parameterBindings: patch.parameterBindings !== undefined ? patch.parameterBindings : object(physical.parameterBindings),
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
  const required: string[] = [];
  if (!metricMode) return required;
  if (physical.valueColumn == null && physical.valuePointer == null) return required;
  const locked = new Set(Object.keys(object(physical.filters)));
  const grain = { ...object(physical.grainColumns), ...object(physical.grainPointers) };
  for (const [semantic, column] of Object.entries(grain)) {
    if (identityKeys.includes(semantic) || locked.has(semantic) || locked.has(String(column))) {
      continue;
    }
    if (!required.includes(semantic)) required.push(semantic);
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

function newMappingId(objectTypeId: string, sourceId: string, documents: DraftDocument[]) {
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
  const identityKeys = array(objectType.identityKeys).map(String).filter(Boolean);
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
    physical: emptyMappingPhysical(provider, identityKeys),
  };
}
