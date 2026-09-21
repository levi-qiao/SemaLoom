import type { DraftDocument } from "./types";
import { currentLocale, translate } from "./i18n";

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

function identityPropertyId(local: string): string {
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
    properties: [{ id: key, label: translate(currentLocale(), "doc.businessId"), valueType: "STRING", required: true }],
  };
}

export function uniqueDocumentId(documents: DraftDocument[], namespace: string, local: string): string {
  let id = `${namespace}.${local}`;
  let n = 2;
  while (documents.some((item) => item.id === id)) {
    id = `${namespace}.${local}${n}`;
    n += 1;
  }
  return id;
}

function namespaceOf(objectType: DraftDocument): string {
  return objectType.id.split(".")[0] ?? "domain";
}

function localOf(objectType: DraftDocument): string {
  return String(objectType.id.split(".").at(-1) || "Object");
}

/** A Rule scoped to this object so the entity page can add one without a separate definition browser. */
export function makeRuleForObject(objectType: DraftDocument, documents: DraftDocument[]): DraftDocument {
  const id = uniqueDocumentId(documents, namespaceOf(objectType), `${localOf(objectType)}Claim`);
  const properties = array(objectType.properties).map(object).filter((item) => text(item.id));
  const measures = measureProperties(objectType);
  const picked = (measures.length >= 2 ? measures : properties).slice(0, 2);
  const inputs = picked.map((property) => ({
    name: text(property.id),
    objectType: objectType.id,
    property: text(property.id),
    required: true,
  }));
  const names = inputs.map((item) => item.name);
  const expression =
    names.length >= 2
      ? { op: "le", args: [{ op: "ref", name: names[0] }, { op: "ref", name: names[1] }] }
      : { op: "bool", value: true };
  return {
    apiVersion: "semaloom/v0.1",
    kind: "Rule",
    id,
    version: "1.0.0",
    label: translate(currentLocale(), "doc.newRule"),
    claim: id,
    inputs,
    expression,
  };
}

/** An Action targeting this object; preconditions stay empty until the user picks a Rule. */
export function makeActionForObject(objectType: DraftDocument, documents: DraftDocument[]): DraftDocument {
  const id = uniqueDocumentId(documents, namespaceOf(objectType), `${localOf(objectType)}Action`);
  return {
    apiVersion: "semaloom/v0.1",
    kind: "Action",
    id,
    version: "1.0.0",
    label: translate(currentLocale(), "doc.newAction"),
    targetObject: objectType.id,
    effect: translate(currentLocale(), "doc.actionEffectPlaceholder"),
    preconditions: [],
    parameters: [],
  };
}

export function documentById(documents: DraftDocument[], id: string | null | undefined) {
  return documents.find((item) => item.id === id) ?? null;
}

/** Normalize Link.identity to the canonical pair-array shape (scalar legacy drafts upgrade in place). */
export function linkIdentityPairs(identity: unknown): { source: string; target: string }[] {
  if (Array.isArray(identity)) {
    return identity
      .map((pair) => {
        const row = object(pair);
        return { source: text(row.source), target: text(row.target) };
      })
      .filter((pair) => pair.source || pair.target);
  }
  const row = object(identity);
  if (row.source || row.target) {
    return [{ source: text(row.source), target: text(row.target) }];
  }
  return [];
}

export function linkIdentitySummary(identity: unknown): { sourceKey: string; targetKey: string } {
  const pairs = linkIdentityPairs(identity);
  return {
    sourceKey: pairs.map((pair) => pair.source).filter(Boolean).join(" + "),
    targetKey: pairs.map((pair) => pair.target).filter(Boolean).join(" + "),
  };
}

/** Default pairs covering every target identity key (name match, then positional zip). */
export function defaultLinkIdentity(
  sourceDoc: DraftDocument | null | undefined,
  targetDoc: DraftDocument | null | undefined,
): { source: string; target: string }[] {
  const sourceKeys = array(sourceDoc?.identityKeys).map(String).filter(Boolean);
  const targetKeys = array(targetDoc?.identityKeys).map(String).filter(Boolean);
  const sourceProps = array(sourceDoc?.properties)
    .map((item) => text((item as Record<string, unknown>).id))
    .filter(Boolean);
  const sourcePool = sourceKeys.length ? sourceKeys : sourceProps;
  if (!targetKeys.length) {
    const source = sourcePool[0] ?? "id";
    return [{ source, target: source }];
  }
  return targetKeys.map((targetKey, index) => ({
    source: sourcePool.includes(targetKey)
      ? targetKey
      : (sourcePool[index] ?? sourcePool[0] ?? "id"),
    target: targetKey,
  }));
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

function measureProperties(objectType: DraftDocument): Record<string, unknown>[] {
  return array(objectType.properties)
    .map(object)
    .filter((item) => Boolean(text(item.unit)) || text(item.valueType) === "DECIMAL" || text(item.valueType) === "INTEGER");
}

/** Optional Metric vocabulary entry (aliases / select / label). Not a physical Mapping class. */
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
  const additivity = text(document.additivity);
  if (additivity === "FULL" || additivity === "SEMI" || additivity === "NONE") {
    next.additivity = additivity;
  }
  return next;
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

export function mappingResourceLabel(mapping: DraftDocument): string {
  const physical = object(mapping.physical);
  if (isOpenApi(mapping.provider)) {
    return text(physical.path) || text(physical.operationId) || translate(currentLocale(), "doc.noApiSelected");
  }
  const schema = text(physical.schema);
  const table = text(physical.table);
  if (schema && schema !== "public" && table) return `${schema}.${table}`;
  return table || translate(currentLocale(), "doc.noTableSelected");
}

export function replaceDocument(documents: DraftDocument[], next: DraftDocument): DraftDocument[] {
  return documents.map((item) => (item.id === next.id ? next : item));
}

export function referencesEntity(document: DraftDocument, entityId: string): boolean {
  if (document.id === entityId) return false;
  if (document.source === entityId || document.target === entityId || document.targetObject === entityId) {
    return true;
  }
  if (document.objectType === entityId || text(document.rule) === entityId || text(document.claim) === entityId) {
    return true;
  }
  if (array(document.preconditions).some((item) => String(item) === entityId)) return true;
  return array(document.inputs).some((item) => {
    const row = object(item);
    return text(row.objectType) === entityId || text(row.metric) === entityId;
  });
}

export function ownedByEntity(document: DraftDocument, entityId: string): boolean {
  if (document.kind === "Mapping" && (document.objectType === entityId || document.target === entityId)) {
    return true;
  }
  if (document.kind === "Metric" && document.objectType === entityId) return true;
  if (document.kind === "Action" && document.targetObject === entityId) return true;
  if (document.kind === "Rule") {
    const types = array(document.inputs).map((item) => text(object(item).objectType)).filter(Boolean);
    return types.length > 0 && types.every((id) => id === entityId);
  }
  return false;
}
