import type { DraftDocument } from "./types";

export const LOCAL_ID = /^[A-Za-z][A-Za-z0-9_]*$/;

export function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

export function array(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

export function object(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

export function sameJson(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

export function identityPropertyId(local: string): string {
  const base = local.charAt(0).toLowerCase() + local.slice(1);
  return /Id$/.test(base) ? base : `${base}Id`;
}

export function makeObjectType(namespace: string, local: string, label: string): DraftDocument {
  const key = identityPropertyId(local);
  return {
    apiVersion: "semaloom/v0.1",
    kind: "ObjectType",
    id: `${namespace}.${local}`,
    version: "1.0.0",
    label: label.trim() || local,
    identityKeys: [key],
    properties: [{ id: key, label: "业务编号", valueType: "STRING", required: true }],
  };
}

export function documentById(documents: DraftDocument[], id: string | null | undefined) {
  return documents.find((item) => item.id === id) ?? null;
}

export function isOpenApi(value: unknown): boolean {
  return text(value) === "openapi";
}

function identityList(identityKeys: string[]): string[] {
  return identityKeys.map(String).filter(Boolean);
}

export function emptyMappingPhysical(
  provider: string,
  identityKeys: string[],
): Record<string, unknown> {
  const identities = identityList(identityKeys);
  if (provider === "openapi") {
    return {
      method: "GET",
      path: "",
      operationId: "",
      parameterBindings: Object.fromEntries(identities.map((key) => [key, key])),
      grainPointers: Object.fromEntries(identities.map((key) => [key, `/${key}`])),
      propertyPointers: {},
    };
  }
  return {
    table: "",
    tenantColumn: "tenant_id",
    grainColumns: Object.fromEntries(identities.map((key) => [key, ""])),
    propertyColumns: {},
  };
}

export function emptyMetricPhysical(
  provider: string,
  identityKeys: string[],
  grain: string[],
): Record<string, unknown> {
  const identities = identityList(identityKeys);
  const dims = grain.length ? grain : identities;
  if (provider === "openapi") {
    const grainPointers = Object.fromEntries(dims.map((dim) => [dim, `/${dim}`]));
    return {
      method: "GET",
      path: "",
      operationId: "",
      parameterBindings: Object.fromEntries(identities.map((key) => [key, key])),
      valuePointer: "/value",
      grainPointers,
    };
  }
  return {
    table: "",
    tenantColumn: "tenant_id",
    valueColumn: "",
    grainColumns: Object.fromEntries(dims.map((dim) => [dim, ""])),
    filters: {},
  };
}

export function metricById(documents: DraftDocument[], id: unknown): DraftDocument | null {
  return documents.find((item) => item.kind === "Metric" && item.id === id) ?? null;
}

export function measureProperties(objectType: DraftDocument): Record<string, unknown>[] {
  return array(objectType.properties)
    .map(object)
    .filter((item) => Boolean(text(item.unit)) || text(item.valueType) === "DECIMAL" || text(item.valueType) === "INTEGER");
}

export function coveringObjectMapping(
  documents: DraftDocument[],
  objectTypeId: string,
  propertyId: string,
): DraftDocument | null {
  if (!propertyId) return null;
  return (
    documents.find((item) => {
      if (item.kind !== "Mapping" || item.target !== objectTypeId) return false;
      const physical = object(item.physical);
      const slots = {
        ...object(physical.propertyColumns),
        ...object(physical.propertyPointers),
        ...object(physical.grainColumns),
        ...object(physical.grainPointers),
      };
      return propertyId in slots;
    }) ?? null
  );
}

/** Optional Metric vocabulary entry (aliases / select / label). Not a physical Mapping class. */
export function makeMetric(
  objectType: DraftDocument,
  local: string,
  label: string,
  unit: string,
  propertyId?: string,
): DraftDocument {
  const namespace = objectType.id.split(".")[0] ?? "domain";
  const identities = array(objectType.identityKeys).map(String).filter(Boolean);
  const property = propertyId || text(measureProperties(objectType)[0]?.id);
  const document: DraftDocument = {
    apiVersion: "semaloom/v0.1",
    kind: "Metric",
    id: `${namespace}.${local}`,
    version: "1.0.0",
    label: label.trim() || local,
    objectType: objectType.id,
    aggregation: "NONE",
  };
  if (property) {
    document.property = property;
    const slot = measureProperties(objectType).find((item) => text(item.id) === property);
    if (text(slot?.unit)) document.unit = text(slot?.unit);
    if (text(slot?.valueType)) document.valueType = text(slot?.valueType);
  } else {
    document.valueType = "DECIMAL";
    document.unit = unit.trim();
    document.grain = identities.length ? identities : ["id"];
  }
  return document;
}

export function canonicalMetric(document: DraftDocument): DraftDocument {
  const grain = array(document.grain).map(String).filter(Boolean);
  const derived = array(document.derivedFrom).map(String).filter(Boolean);
  const next: DraftDocument = {
    apiVersion: "semaloom/v0.1",
    kind: "Metric",
    id: document.id,
    version: text(document.version) || "1.0.0",
    objectType: text(document.objectType),
    aggregation: ["NONE", "SUM", "MAX", "MIN"].includes(text(document.aggregation))
      ? text(document.aggregation)
      : "NONE",
  };
  const property = text(document.property);
  if (property) next.property = property;
  const select = object(document.select);
  if (Object.keys(select).length) next.select = { ...select };
  const valueType = text(document.valueType);
  if (valueType === "INTEGER" || valueType === "DECIMAL") next.valueType = valueType;
  const unit = text(document.unit);
  if (unit) next.unit = unit;
  if (grain.length) next.grain = grain;
  const label = text(document.label);
  const description = text(document.description);
  const perspective = text(document.perspective);
  if (label) next.label = label;
  if (description) next.description = description;
  if (perspective) next.perspective = perspective;
  if (derived.length) next.derivedFrom = derived;
  const aliases = array(document.aliases).map(String);
  if (aliases.length) next.aliases = aliases;
  if (document.population) next.population = { ...object(document.population) };
  return next;
}

export function renameMetric(documents: DraftDocument[], previousId: string, next: DraftDocument): DraftDocument[] {
  const metric = canonicalMetric(next);
  return documents.map((item) => {
    if (item.id === previousId && item.kind === "Metric") return metric;
    if (item.kind === "Mapping" && item.target === previousId) {
      return { ...item, target: metric.id, objectType: metric.objectType };
    }
    if (item.kind === "Metric" && array(item.derivedFrom).map(String).includes(previousId)) {
      return canonicalMetric({
        ...item,
        derivedFrom: array(item.derivedFrom).map((id) => (id === previousId ? metric.id : id)),
      });
    }
    return item;
  });
}

export function jsonContains(value: unknown, expected: string): boolean {
  if (value === expected) return true;
  if (Array.isArray(value)) return value.some((item) => jsonContains(item, expected));
  if (value && typeof value === "object") {
    return Object.values(value as Record<string, unknown>).some((item) => jsonContains(item, expected));
  }
  return false;
}

export function ownedByMetric(document: DraftDocument, metricId: string): boolean {
  return document.kind === "Mapping" && document.target === metricId;
}

export function attachMapping(documents: DraftDocument[], mapping: DraftDocument): DraftDocument[] {
  if (documents.some((item) => item.id === mapping.id)) {
    return rehomeMapping(documents, mapping.id, text(mapping.sourceId), text(mapping.provider));
  }
  return rehomeMapping([...documents, mapping], mapping.id, text(mapping.sourceId), text(mapping.provider));
}

export function rehomeMapping(
  documents: DraftDocument[],
  mappingId: string,
  sourceId: string,
  provider: string,
): DraftDocument[] {
  return documents.map((item) => {
    if (item.kind !== "IntegrationBinding") return item;
    const mappings = array(item.mappings).map(String);
    const has = mappings.includes(mappingId);
    const owner = text(item.sourceId) === sourceId && text(item.provider) === provider;
    if (owner && !has) return { ...item, mappings: [...mappings, mappingId] };
    if (!owner && has) return { ...item, mappings: mappings.filter((id) => id !== mappingId) };
    return item;
  });
}

export function detachMapping(documents: DraftDocument[], mappingId: string): DraftDocument[] {
  return documents.map((item) => {
    if (item.kind !== "IntegrationBinding") return item;
    const mappings = array(item.mappings).map(String);
    if (!mappings.includes(mappingId)) return item;
    return { ...item, mappings: mappings.filter((id) => id !== mappingId) };
  });
}

export function removeMetric(documents: DraftDocument[], metricId: string): DraftDocument[] {
  const owned = documents.filter((item) => ownedByMetric(item, metricId)).map((item) => item.id);
  let next = documents.filter((item) => item.id !== metricId && !ownedByMetric(item, metricId));
  for (const mappingId of owned) next = detachMapping(next, mappingId);
  return next;
}

export function mappingResourceLabel(mapping: DraftDocument): string {
  const physical = object(mapping.physical);
  if (isOpenApi(mapping.provider)) {
    return text(physical.path) || text(physical.operationId) || "未选接口";
  }
  const schema = text(physical.schema);
  const table = text(physical.table);
  if (schema && schema !== "public" && table) return `${schema}.${table}`;
  return table || "未选表";
}

export function replaceDocument(documents: DraftDocument[], next: DraftDocument): DraftDocument[] {
  return documents.map((item) => (item.id === next.id ? next : item));
}

export function referencesEntity(document: DraftDocument, entityId: string): boolean {
  if (document.id === entityId) return false;
  if (document.source === entityId || document.target === entityId || document.targetObject === entityId) {
    return true;
  }
  if (document.objectType === entityId) return true;
  return array(document.inputs).some((item) => object(item).objectType === entityId);
}

export function ownedByEntity(document: DraftDocument, entityId: string): boolean {
  if (document.kind === "Mapping" && (document.objectType === entityId || document.target === entityId)) {
    return true;
  }
  if (document.kind === "Metric" && document.objectType === entityId) return true;
  return document.kind === "Action" && document.targetObject === entityId;
}
