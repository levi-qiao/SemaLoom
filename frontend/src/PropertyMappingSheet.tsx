import { useEffect, useMemo, useState } from "react";

import { apiHeaders, checkedJson } from "./api";
import {
  array,
  attachMapping,
  detachMapping,
  emptyMappingPhysical,
  isOpenApi,
  mappingResourceLabel,
  object,
  rehomeMapping,
  replaceDocument,
  sameJson,
  text,
} from "./doc";
import { additivityOptions, draftPreviewHint, previewOutcomeText } from "./labels";
import { bindObjectColumn, makeMappingDocument, previewFailureFromHttp } from "./MappingEditor";
import { useRowKeys } from "./rowKeys";
import { useI18n } from "./i18n";
import type { DraftDocument, SourceProfileSummary, SourceResource } from "./types";

type Props = {
  objectType: DraftDocument;
  documents: DraftDocument[];
  savedDocuments: DraftDocument[];
  savedRevision: number;
  onChange: (documents: DraftDocument[]) => void;
  onError: (message: string | null) => void;
};

type Binding = { mappingId: string; column: string };
type Preview = {
  kind: string;
  reason: string | null;
  fields: { semanticField: string; physicalField: string; value: string | null }[];
};

export function PropertyMappingSheet({
  objectType,
  documents,
  savedDocuments,
  savedRevision,
  onChange,
  onError,
}: Props) {
  const { t } = useI18n();
  const properties = array(objectType.properties) as Record<string, unknown>[];
  const identityKeys = array(objectType.identityKeys).map(String);
  const rowKeys = useRowKeys(properties.length, objectType.id);
  const mappings = documents.filter((item) => item.kind === "Mapping" && item.target === objectType.id);
  const [profiles, setProfiles] = useState<SourceProfileSummary[]>([]);
  const [schemas, setSchemas] = useState<Record<string, SourceResource[]>>({});
  const [focusMapping, setFocusMapping] = useState("");
  const [activeProperty, setActiveProperty] = useState(identityKeys[0] ?? text(properties[0]?.id));
  const [tableRows, setTableRows] = useState<Record<string, string | null>[]>([]);
  const [rowsReason, setRowsReason] = useState<string | null>(null);
  const [pickedRow, setPickedRow] = useState<number | null>(null);
  const [identity, setIdentity] = useState<Record<string, string>>({});
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void fetch("/v0.1/studio/source-profiles").then(checkedJson)
      .then((payload) => setProfiles(payload.profiles ?? []))
      .catch(() => setProfiles([]));
  }, []);

  const sourceKey = mappings.map((item) => text(item.sourceId)).filter(Boolean).join("|");
  useEffect(() => {
    const sourceIds = [...new Set(sourceKey.split("|").filter(Boolean))];
    for (const sourceId of sourceIds) {
      void fetch(`/v0.1/studio/source-profiles/${encodeURIComponent(sourceId)}/schema`).then(checkedJson)
        .then((payload) => setSchemas((current) => ({ ...current, [sourceId]: payload.resources ?? [] })))
        .catch(() => setSchemas((current) => ({ ...current, [sourceId]: [] })));
    }
  }, [sourceKey]);

  const mappingIds = mappings.map((item) => item.id).join("|");
  useEffect(() => {
    if (mappings.some((item) => item.id === focusMapping)) return;
    const tableFirst = mappings.find((item) => !isOpenApi(item.provider));
    setFocusMapping(tableFirst?.id ?? mappings[0]?.id ?? "");
  }, [mappingIds, focusMapping, mappings]);

  const focused = mappings.find((item) => item.id === focusMapping) ?? mappings[0] ?? null;
  const focusedPhysical = object(focused?.physical);
  const focusedTable = text(focusedPhysical.table);
  const focusedPath = text(focusedPhysical.path);
  const focusedApi = focused ? isOpenApi(focused.provider) : false;
  const focusedResources = schemas[text(focused?.sourceId)] ?? [];
  const focusedColumns = useMemo((): { name: string; type?: string }[] => {
    if (!focused) return [];
    if (focusedApi) {
      const op = focusedResources.find((item) => item.name === focusedPath || item.id === text(focusedPhysical.operationId));
      if (op?.columns?.length) return op.columns;
    } else {
      const table = focusedResources.find((item) => item.name === focusedTable || item.id.endsWith(`.${focusedTable}`));
      if (table?.columns?.length) return table.columns;
    }
    const names = new Set<string>();
    for (const value of Object.values({
      ...object(focusedApi ? focusedPhysical.grainPointers : focusedPhysical.grainColumns),
      ...object(focusedApi ? focusedPhysical.propertyPointers : focusedPhysical.propertyColumns),
    })) {
      if (value) names.add(String(value));
    }
    return [...names].map((name) => ({ name }));
  }, [focused, focusedApi, focusedResources, focusedTable, focusedPath, focusedPhysical]);
  const tableSchema = focusedResources.find((item) => item.name === focusedTable)?.schema ?? null;
  const parameters = focusedApi
    ? focusedResources.find((item) => item.name === focusedPath || item.id === text(focusedPhysical.operationId))?.parameters ?? []
    : [];

  useEffect(() => {
    if (!focused || focusedApi || !focused.sourceId || !focusedTable) {
      setTableRows([]);
      setRowsReason(focusedApi ? "API_PREVIEW" : null);
      return;
    }
    void fetch(`/v0.1/studio/source-profiles/${encodeURIComponent(String(focused.sourceId))}/rows`, {
      method: "POST",
      headers: apiHeaders(),
      body: JSON.stringify({ table: focusedTable, schema: tableSchema, limit: 20 }),
    }).then(checkedJson).then((payload) => {
      setTableRows(payload.rows ?? []);
      setRowsReason(payload.reason ?? null);
    }).catch(() => {
      setTableRows([]);
      setRowsReason("SAMPLE_UNAVAILABLE");
    });
    setPickedRow(null);
  }, [focused?.id, focusedTable, tableSchema, focusedApi, focused?.sourceId]);

  useEffect(() => {
    setIdentity({});
    setPreview(null);
    setPreviewError(null);
  }, [focusMapping]);

  const uniqueTables = [...new Set(mappings.map((mapping) => resourceName(mapping)).filter(Boolean))];
  const multiTable = uniqueTables.length > 1;
  const missingJoin = mappings.some((mapping) => identityKeys.some((key) => !columnOf(mapping, key, identityKeys)));
  const saved = Boolean(focused) && savedDocuments.some((item) => item.id === focused?.id && sameJson(item, focused));
  const hasResource = focusedApi ? Boolean(focusedPath || text(focusedPhysical.operationId)) : Boolean(focusedTable);
  const canPreview = saved && identityKeys.length > 0 && identityKeys.every((key) => Boolean(text(identity[key]).trim())) && hasResource;

  function replaceObject(next: DraftDocument) {
    onChange(replaceDocument(documents, next));
  }

  function updateProperty(index: number, patch: Record<string, unknown>) {
    const previousId = text(properties[index].id);
    const nextProperties = properties.map((item, position) => (position === index ? { ...item, ...patch } : item));
    let nextKeys = identityKeys;
    if (typeof patch.id === "string" && patch.id !== previousId) {
      const nextId = patch.id;
      nextKeys = identityKeys.map((item) => (item === previousId ? nextId : item));
      if (!nextKeys.length) nextKeys = [nextId];
    }
    replaceObject({ ...objectType, properties: nextProperties, identityKeys: nextKeys });
  }

  function bindingOf(propertyId: string): Binding | null {
    if (identityKeys.includes(propertyId) && focused) {
      return { mappingId: focused.id, column: columnOf(focused, propertyId, identityKeys) };
    }
    for (const mapping of mappings) {
      const column = columnOf(mapping, propertyId, identityKeys);
      if (column) return { mappingId: mapping.id, column };
    }
    return null;
  }

  function setPropertyBinding(propertyId: string, mappingId: string, column: string) {
    const identityField = identityKeys.includes(propertyId);
    onChange(documents.map((item) => {
      if (item.kind !== "Mapping" || item.target !== objectType.id) return item;
      if (item.id === mappingId) return bindObjectColumn(item, propertyId, column, identityField);
      if (identityField) return item;
      if (columnOf(item, propertyId, identityKeys)) return bindObjectColumn(item, propertyId, "", false);
      return item;
    }));
    setFocusMapping(mappingId);
    setActiveProperty(propertyId);
  }

  function addProperty() {
    replaceObject({
      ...objectType,
      properties: [...properties, { id: "newProperty", valueType: "STRING", required: false }],
    });
  }

  function addMapping() {
    const source = profiles[0];
    const created = makeMappingDocument(objectType, source?.sourceId ?? "orders_pg", source?.provider ?? "postgres", documents);
    onChange(attachMapping(documents, created));
    setFocusMapping(created.id);
  }

  function removeFocusedMapping() {
    if (!focused) return;
    onChange(detachMapping(documents.filter((item) => item.id !== focused.id), focused.id));
    setFocusMapping("");
  }

  function retargetSource(nextId: string) {
    if (!focused) return;
    const profile = profiles.find((item) => item.sourceId === nextId);
    const provider = String(profile?.provider ?? focused.provider);
    const next = {
      ...focused,
      sourceId: nextId,
      provider,
      physical: emptyMappingPhysical(provider, identityKeys),
    };
    onChange(rehomeMapping(replaceDocument(documents, next), next.id, nextId, provider));
    setTableRows([]);
    setRowsReason(null);
  }

  function boundCount(mapping: DraftDocument) {
    return properties.filter((property) => Boolean(columnOf(mapping, text(property.id), identityKeys))).length;
  }

  function pickColumn(column: string) {
    const propertyId = activeProperty || identityKeys[0];
    const mappingId = focused?.id;
    if (!propertyId || !mappingId) return;
    setPropertyBinding(propertyId, mappingId, column);
  }

  function pickRow(index: number, row: Record<string, string | null>) {
    setPickedRow(index);
    const next: Record<string, string> = {};
    for (const key of identityKeys) {
      const column = focused ? columnOf(focused, key, identityKeys) : "";
      if (column && row[column] != null) next[key] = String(row[column]);
    }
    if (Object.keys(next).length) setIdentity(next);
  }

  function patchFocused(next: DraftDocument) {
    onChange(replaceDocument(documents, next));
  }

  async function runPreview() {
    if (!canPreview || !focused) return;
    setBusy(true);
    setPreview(null);
    setPreviewError(null);
    onError(null);
    try {
      const payload = await fetch("/v0.1/studio/sample", {
        method: "POST",
        headers: apiHeaders(),
        body: JSON.stringify({
          mappingId: focused.id,
          identity,
          draftId: "default",
          bindings: {},
        }),
      }).then(checkedJson);
      const result = payload as Preview;
      setPreview(result);
      if (result.kind !== "PRESENT") {
        setPreviewError(previewOutcomeText(text(focused.provider), result.kind, result.reason));
      }
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : "UNKNOWN_ERROR";
      const failure = previewFailureFromHttp(text(focused.provider), message);
      setPreviewError(failure);
      onError(failure);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="entity-sheet mapping-card">
      <div className="entity-sheet-main">
        <p className="mapping-hint">{t("mapping.sheetHint")}</p>
        <div className="source-tabs" aria-label={t("mapping.sourceTabsAria")}>
          {mappings.map((mapping) => (
            <button
              key={mapping.id}
              type="button"
              className={mapping.id === focused?.id ? "source-tab active" : "source-tab"}
              aria-selected={mapping.id === focused?.id}
              onClick={() => setFocusMapping(mapping.id)}
            >
              <small>{isOpenApi(mapping.provider) ? t("mapping.resourceTypeApi") : t("mapping.resourceTypeTable")}</small>
              <strong>{resourceName(mapping) || mappingResourceLabel(mapping)}</strong>
              <small>{t("mapping.boundPropertiesCount", { count: boundCount(mapping) })}</small>
            </button>
          ))}
          <button className="secondary sheet-action" onClick={addMapping}>{t("mapping.addSourceShort")}</button>
          <button className="secondary sheet-action" onClick={addProperty}>{t("mapping.addProperty")}</button>
          {focused && mappings.length > 1 ? (
            <button className="text-button" onClick={removeFocusedMapping}>{t("mapping.removeThisSource")}</button>
          ) : null}
        </div>
        {focused ? (
          <div className="form-grid">
            <label className="form-field"><span>{t("mapping.dataSource")}</span>
              <select aria-label={t("mapping.dataSource")} value={text(focused.sourceId)} onChange={(event) => retargetSource(event.target.value)}>
                {text(focused.sourceId) && !profiles.some((item) => item.sourceId === text(focused.sourceId)) ? (
                  <option value={text(focused.sourceId)}>{text(focused.sourceId)}</option>
                ) : null}
                {profiles.map((item) => <option key={item.sourceId} value={item.sourceId}>{item.label}</option>)}
              </select>
            </label>
            {focusedApi ? (
              <label className="form-field"><span>{t("mapping.apiOperation")}</span>
                <select aria-label={t("mapping.apiOperation")} value={focusedPath} onChange={(event) => {
                  const resource = focusedResources.find((item) => item.name === event.target.value);
                  patchFocused({
                    ...focused,
                    physical: { ...focusedPhysical, path: event.target.value, operationId: resource?.operationId || resource?.id || "" },
                  });
                }}>
                  <option value="">{t("mapping.selectGetOp")}</option>
                  {focusedPath && !focusedResources.some((item) => item.name === focusedPath) ? (
                    <option value={focusedPath}>{focusedPath}</option>
                  ) : null}
                  {focusedResources.filter((item) => item.kind === "operation" || item.method === "GET").map((item) => (
                    <option key={item.id} value={item.name}>{item.method ?? "GET"} {item.name}</option>
                  ))}
                </select>
              </label>
            ) : (
              <label className="form-field"><span>{t("mapping.table")}</span>
                <select aria-label={t("mapping.resourceTypeTable")} value={focusedTable} onChange={(event) => {
                  const resource = focusedResources.find((item) => item.name === event.target.value);
                  const schema = resource?.schema && resource.schema !== "public" ? resource.schema : undefined;
                  const physical: Record<string, unknown> = { ...focusedPhysical, table: event.target.value };
                  if (schema) physical.schema = schema;
                  else delete physical.schema;
                  patchFocused({ ...focused, physical });
                }}>
                  <option value="">{t("mapping.selectTable")}</option>
                  {focusedTable && !focusedResources.some((item) => item.name === focusedTable) ? (
                    <option value={focusedTable}>{focusedTable}</option>
                  ) : null}
                  {focusedResources.filter((item) => item.kind === "table" || (!item.kind && !item.method)).map((item) => (
                    <option key={item.id} value={item.name}>
                      {item.schema && item.schema !== "public" ? `${item.schema}.${item.name}` : item.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {identityKeys.map((key) => {
              const current = focused ? columnOf(focused, key, identityKeys) : "";
              const cols = focused ? columnsFor(focused, schemas) : [];
              return (
                <label key={key} className={current ? "form-field" : "form-field is-warn"}>
                  <span>{t("mapping.bindIdentityKey", { key })}</span>
                  <select
                    aria-label={`${resourceName(focused)} ${key} ${t("mapping.joinKey")}`}
                    value={current}
                    onChange={(event) => focused && setPropertyBinding(key, focused.id, event.target.value)}
                  >
                    <option value="">{t("mapping.selectJoinColumn")}</option>
                    {fieldOptions(cols, current).map((column) => <option key={column.name} value={column.name}>{column.name}</option>)}
                  </select>
                </label>
              );
            })}
            {focusedApi ? identityKeys.map((key) => (
              <label className="form-field" key={key}><span>{t("mapping.identityParam", { key })}</span>
                <select
                  aria-label={t("mapping.identityParam", { key })}
                  value={text(object(focusedPhysical.parameterBindings)[key])}
                  onChange={(event) => patchFocused({
                    ...focused,
                    physical: {
                      ...focusedPhysical,
                      parameterBindings: { ...object(focusedPhysical.parameterBindings), [key]: event.target.value },
                    },
                  })}
                >
                  {(parameters.length ? parameters : [{ name: key }]).map((item) => (
                    <option key={item.name} value={item.name}>{item.name}</option>
                  ))}
                </select>
              </label>
            )) : null}
          </div>
        ) : <p className="empty">{t("mapping.noSourcesYet")}</p>}
        {multiTable ? (
          <div className="join-banner" role="status">
            <p>
              {missingJoin
                ? t("mapping.multiSourceNotice", { count: uniqueTables.length })
                : t("mapping.multiSourceConfigured", { count: uniqueTables.length })}
            </p>
            <div className="join-grid">
              {mappings.map((mapping) => (
                <div key={mapping.id} className="join-row">
                  <strong>{resourceName(mapping) || mapping.id}</strong>
                  {identityKeys.map((key) => {
                    const current = columnOf(mapping, key, identityKeys);
                    const cols = columnsFor(mapping, schemas);
                    const missing = !current;
                    return (
                      <label key={key} className={missing ? "form-field is-warn" : "form-field"}>
                        <span>{key}{missing ? t("mapping.unboundCannotJoin") : ""}</span>
                        <select
                          aria-label={`${resourceName(mapping)} ${key} ${t("mapping.joinKey")}`}
                          value={current}
                          onChange={(event) => setPropertyBinding(key, mapping.id, event.target.value)}
                        >
                          <option value="">{t("mapping.selectJoinColumn")}</option>
                          {fieldOptions(cols, current).map((column) => <option key={column.name} value={column.name}>{column.name}</option>)}
                        </select>
                      </label>
                    );
                  })}
                </div>
              ))}
            </div>
          </div>
        ) : null}
        <div className="field-array">
          <div className={multiTable ? "source-record-list is-multi" : "source-record-list"}>
            <div className="source-record-head">
              <span>{t("mapping.headerId")}</span><span>{t("mapping.headerName")}</span><span>{t("mapping.headerType")}</span><span>{t("mapping.headerKey")}</span>
              {multiTable ? <span>{t("mapping.headerSource")}</span> : null}
              <span>{t("mapping.headerField")}</span><span />
            </div>
            {properties.map((property, index) => {
              const semantic = text(property.id);
              const numeric = text(property.valueType) === "DECIMAL" || text(property.valueType) === "INTEGER";
              const bound = bindingOf(semantic);
              const mapping = mappings.find((item) => item.id === bound?.mappingId) ?? focused;
              const cols = mapping ? columnsFor(mapping, schemas) : [];
              return (
                <div
                  className={"source-record-row" + (activeProperty === semantic ? " is-active" : "")}
                  key={rowKeys[index] ?? `property-${index}`}
                  onClick={() => {
                    setActiveProperty(semantic);
                    if (bound?.mappingId) setFocusMapping(bound.mappingId);
                  }}
                >
                  <input aria-label={t("mapping.propId")} value={semantic} onChange={(event) => updateProperty(index, { id: event.target.value })} />
                  <input aria-label={t("mapping.propName")} value={text(property.label)} placeholder={t("entity.label")} onChange={(event) => updateProperty(index, { label: event.target.value })} />
                  <span className={numeric ? "type-unit has-unit" : "type-unit"}>
                    <select aria-label={t("mapping.propType")} value={text(property.valueType)} onChange={(event) => {
                      const valueType = event.target.value;
                      const measure = valueType === "DECIMAL" || valueType === "INTEGER";
                      updateProperty(index, measure ? { valueType } : { valueType, unit: undefined, additivity: undefined });
                    }}>
                      {["STRING", "INTEGER", "DECIMAL", "BOOLEAN", "DATE", "DATETIME"].map((type) => <option key={type}>{type}</option>)}
                    </select>
                    {numeric ? (
                      <>
                        <input aria-label={t("mapping.propUnit")} value={text(property.unit)} placeholder="CNY" onChange={(event) => updateProperty(index, { unit: event.target.value || undefined })} />
                        <select aria-label={t("mapping.additivity")} value={text(property.additivity) || "FULL"} onChange={(event) => updateProperty(index, { additivity: event.target.value })}>
                          {additivityOptions().map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
                        </select>
                      </>
                    ) : null}
                  </span>
                  <label className="check-field">
                    <input type="checkbox" checked={identityKeys.includes(semantic)} onChange={(event) => {
                      const next = event.target.checked ? [...new Set([...identityKeys, semantic])] : identityKeys.filter((item) => item !== semantic);
                      replaceObject({ ...objectType, identityKeys: next.length ? next : [semantic] });
                    }} />{t("mapping.headerKey")}
                  </label>
                  {multiTable ? (
                    <select
                      aria-label={t("mapping.propSource", { name: semantic })}
                      title={mapping ? `${isOpenApi(mapping.provider) ? t("mapping.resourceTypeApi") : t("mapping.table")} ${resourceName(mapping)}` : ""}
                      value={bound?.mappingId ?? mapping?.id ?? ""}
                      onChange={(event) => setPropertyBinding(semantic, event.target.value, identityKeys.includes(semantic) ? (bound?.column ?? "") : "")}
                    >
                      {mappings.map((item) => (
                        <option key={item.id} value={item.id}>
                          {isOpenApi(item.provider) ? t("mapping.resourceTypeApi") : t("mapping.table")} {resourceName(item) || item.id}
                        </option>
                      ))}
                    </select>
                  ) : null}
                  <select
                    aria-label={t("mapping.propColumn", { name: semantic })}
                    title={bound?.column || ""}
                    value={bound?.column ?? ""}
                    onChange={(event) => mapping && setPropertyBinding(semantic, mapping.id, event.target.value)}
                  >
                    <option value="">{t("mapping.selectField")}</option>
                    {fieldOptions(cols, bound?.column ?? "").map((column) => <option key={column.name} value={column.name}>{column.name}</option>)}
                  </select>
                  <button className="icon-button" aria-label={t("mapping.deleteProp", { name: semantic })} onClick={() => replaceObject({
                    ...objectType,
                    properties: properties.filter((_, position) => position !== index),
                    identityKeys: identityKeys.filter((item) => item !== semantic).length ? identityKeys.filter((item) => item !== semantic) : identityKeys,
                  })}>×</button>
                </div>
              );
            })}
          </div>
        </div>
        {(() => {
          const active = properties.find((item) => text(item.id) === activeProperty);
          const dictionaryOk = Boolean(active) && ["STRING", "INTEGER", "BOOLEAN"].includes(text(active?.valueType)) && !identityKeys.includes(text(active?.id));
          const values = array(active?.values) as Record<string, unknown>[];
          if (!dictionaryOk || !active) return null;
          return (
            <div className="field-array property-dictionary">
              <div className="field-array-head">
                <div>
                  <h3>{t("mapping.dictValues")}</h3>
                  <p className="chat-choice-reason">{t("mapping.dictValuesHint")}</p>
                </div>
                <button type="button" className="secondary" onClick={() => updateProperty(properties.findIndex((item) => text(item.id) === activeProperty), { values: [...values, { id: "", label: "" }] })}>{t("mapping.addDictValue")}</button>
              </div>
              {values.map((item, index) => (
                <div className="property-row" key={`${text(item.id)}-${index}`}>
                  <input aria-label={t("mapping.dictStoredValue")} placeholder={t("mapping.dictStoredValue")} value={text(item.id)} onChange={(event) => {
                    const next = values.map((row, position) => position === index ? { ...row, id: event.target.value } : row);
                    updateProperty(properties.findIndex((row) => text(row.id) === activeProperty), { values: next });
                  }} />
                  <input aria-label={t("mapping.dictDisplayName")} placeholder={t("mapping.dictDisplayName")} value={text(item.label)} onChange={(event) => {
                    const next = values.map((row, position) => position === index ? { ...row, label: event.target.value } : row);
                    updateProperty(properties.findIndex((row) => text(row.id) === activeProperty), { values: next });
                  }} />
                  <input aria-label={t("mapping.dictAliases")} placeholder={t("mapping.dictAliases")} value={array(item.aliases).map(String).join(", ")} onChange={(event) => {
                    const aliases = event.target.value.split(/[,，]/).map((part) => part.trim()).filter(Boolean);
                    const next = values.map((row, position) => position === index ? { ...row, aliases } : row);
                    updateProperty(properties.findIndex((row) => text(row.id) === activeProperty), { values: next });
                  }} />
                  <button type="button" className="icon-button" aria-label={t("mapping.deleteDictValue", { name: text(item.id) })} onClick={() => {
                    const next = values.filter((_, position) => position !== index);
                    updateProperty(properties.findIndex((row) => text(row.id) === activeProperty), { values: next.length ? next : undefined });
                  }}>×</button>
                </div>
              ))}
            </div>
          );
        })()}
      </div>
      <div className="entity-sheet-side">
        <div className="mapping-preview">
          <div className="mapping-preview-head">
            <strong>{focusedApi ? (focusedPath || t("mapping.interfaceField")) : (focusedTable || t("mapping.tablePreview"))}</strong>
            <small>
              {activeProperty
                ? (focusedApi
                  ? t("mapping.pickColumnToBindApi", { name: text(properties.find((item) => text(item.id) === activeProperty)?.label) || activeProperty })
                  : t("mapping.pickColumnToBind", { name: text(properties.find((item) => text(item.id) === activeProperty)?.label) || activeProperty }))
                : t("mapping.pickPropertyFirstShort")}
            </small>
          </div>
          {focusedColumns.length ? (
            <div className="mapping-preview-table">
              <table>
                <thead>
                  <tr>
                    {focusedColumns.map((column) => (
                      <th key={column.name}>
                        <button type="button" className="mapping-col" aria-label={t("mapping.bindCol", { name: column.name })} onClick={() => pickColumn(column.name)}>
                          {column.name}<small>{column.type}</small>
                        </button>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {focusedApi ? (
                    <tr><td colSpan={Math.max(focusedColumns.length, 1)}>{t("mapping.apiNoRowPreview")}</td></tr>
                  ) : tableRows.length ? tableRows.map((row, index) => (
                    <tr key={index} className={pickedRow === index ? "is-picked" : undefined} onClick={() => pickRow(index, row)}>
                      {focusedColumns.map((column) => <td key={column.name}>{row[column.name] ?? "—"}</td>)}
                    </tr>
                  )) : (
                    <tr>
                      <td colSpan={Math.max(focusedColumns.length, 1)}>
                        {rowsReason === "TENANT_SCOPE_REQUIRED" ? t("mapping.tenantScopeRequired") : rowsReason === "SAMPLE_UNAVAILABLE" || rowsReason === "SOURCE_UNAVAILABLE"
                          ? t("mapping.noSampleRows")
                          : rowsReason === "TABLE_NOT_IN_CATALOG"
                            ? t("mapping.tableNotInCatalog")
                            : t("mapping.emptySampleRows")}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="mapping-hint">{focused ? t("mapping.selectSourceHint") : t("mapping.addSourceHint")}</p>
          )}
          {focused ? (
            <div className="try-read">
              {identityKeys.map((key) => (
                <label className="form-field" key={key}>
                  <span>{t("mapping.sampleIdentityKey", { key })}</span>
                  <input
                    value={text(identity[key])}
                    placeholder={key}
                    onChange={(event) => setIdentity((current) => ({ ...current, [key]: event.target.value }))}
                  />
                </label>
              ))}
              <button className="secondary" disabled={busy || !canPreview} onClick={() => void runPreview()}>{t("mapping.testRead")}</button>
              {saved ? (
                <p className="mapping-hint">{draftPreviewHint(true, savedRevision)}</p>
              ) : (
                <p className="notice">{draftPreviewHint(false, savedRevision)}</p>
              )}
              {previewError ? <p className="field-error" role="alert">{previewError}</p> : null}
              {preview ? (
                <p className="mapping-hint">
                  {t("mapping.testReadOutcome", { outcome: previewOutcomeText(text(focused.provider), preview.kind, preview.reason) })}
                  {preview.reason ? ` · ${preview.reason}` : ""}
                  {preview.fields.filter((item) => item.value).length
                    ? ` · ${preview.fields.filter((item) => item.value).map((item) => `${item.semanticField}=${item.value}`).join(", ")}`
                    : ""}
                </p>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function resourceName(mapping: DraftDocument): string {
  const physical = object(mapping.physical);
  return text(physical.table) || text(physical.path) || mappingResourceLabel(mapping);
}

function columnOf(mapping: DraftDocument, propertyId: string, identityKeys: string[]): string {
  const physical = object(mapping.physical);
  const grain = object(isOpenApi(mapping.provider) ? physical.grainPointers : physical.grainColumns);
  const props = object(isOpenApi(mapping.provider) ? physical.propertyPointers : physical.propertyColumns);
  if (text(grain[propertyId])) return text(grain[propertyId]);
  if (text(props[propertyId])) return text(props[propertyId]);
  return "";
}

function fieldOptions(columns: { name: string }[], current: string) {
  if (current && !columns.some((item) => item.name === current)) {
    return [{ name: current }, ...columns];
  }
  return columns;
}

function columnsFor(mapping: DraftDocument, schemas: Record<string, SourceResource[]>): { name: string; type?: string }[] {
  const physical = object(mapping.physical);
  const resources = schemas[text(mapping.sourceId)] ?? [];
  if (isOpenApi(mapping.provider)) {
    const op = resources.find((item) => item.name === text(physical.path) || item.id === text(physical.operationId));
    return op?.columns ?? [];
  }
  const table = text(physical.table);
  const match = resources.find((item) => item.name === table || item.id.endsWith(`.${table}`));
  return match?.columns ?? [];
}
