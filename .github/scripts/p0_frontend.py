from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def edit(path: str, old: str, new: str) -> None:
    file = ROOT / path
    text = file.read_text()
    if old not in text:
        raise SystemExit(f"missing replacement in {path}: {old[:120]!r}")
    file.write_text(text.replace(old, new, 1))


# --- frontend wire types expose the same identity/capability contract as backend ---
edit(
    "frontend/src/types.ts",
    '  identityField: string;\n  requiredBindings: string[];\n',
    '  identityField: string;\n  identityFields: string[];\n  capabilities: string[];\n  requiredBindings: string[];\n',
)
edit(
    "frontend/src/types.ts",
    '  identityKeys: string[];\n  properties:',
    '  identityKeys: string[];\n'
    '  identity: { scope: "TENANT"; components: { property: string; normalization: string }[] };\n'
    '  properties:',
)

# --- document constructors: structured identity and capability defaults ---
edit(
    "frontend/src/doc.ts",
    '    identityKeys: [key],\n    properties: [{ id: key, label: "业务编号", valueType: "STRING", required: true }],\n',
    '    identityKeys: [key],\n'
    '    identity: { scope: "TENANT", components: [{ property: key, normalization: "NONE" }] },\n'
    '    properties: [{ id: key, label: "业务编号", valueType: "STRING", required: true }],\n',
)
edit(
    "frontend/src/doc.ts",
    'export function emptyMappingPhysical(provider: string, identityKey: string): Record<string, unknown> {\n  if (provider === "openapi") {\n    return {\n      method: "GET",\n      path: "",\n      operationId: "",\n      identityParameter: identityKey,\n      identityPointer: `/${identityKey}`,\n      grainPointers: { [identityKey]: `/${identityKey}` },\n      propertyPointers: {},\n    };\n  }\n  return {\n    table: "",\n    tenantColumn: "tenant_id",\n    identityColumn: "",\n    grainColumns: { [identityKey]: "" },\n    propertyColumns: {},\n  };\n}\n',
    '''function identityList(identity: string | string[]): string[] {\n  const values = Array.isArray(identity) ? identity : [identity];\n  return values.map(String).filter(Boolean);\n}\n\nexport function mappingCapabilities(provider: string): string[] {\n  return provider === "postgres"\n    ? ["POINT_READ", "OBJECT_SEARCH", "COLLECTION_QUERY", "RELATIONAL_JOIN", "BATCH_KEY_LOOKUP"]\n    : ["POINT_READ"];\n}\n\nexport function withIdentityKeys(document: DraftDocument, keys: string[]): DraftDocument {\n  const previous = new Map(\n    array(object(document.identity).components).map((item) => {\n      const component = object(item);\n      return [text(component.property), text(component.normalization) || "NONE"];\n    }),\n  );\n  return {\n    ...document,\n    identityKeys: keys,\n    identity: {\n      scope: "TENANT",\n      components: keys.map((property) => ({\n        property,\n        normalization: previous.get(property) ?? "NONE",\n      })),\n    },\n  };\n}\n\nexport function emptyMappingPhysical(provider: string, identity: string | string[]): Record<string, unknown> {\n  const identities = identityList(identity);\n  const first = identities[0] ?? "id";\n  if (provider === "openapi") {\n    return {\n      method: "GET",\n      path: "",\n      operationId: "",\n      identityParameter: first,\n      identityPointer: `/${first}`,\n      identityParameters: Object.fromEntries(identities.map((key) => [key, key])),\n      identityPointers: Object.fromEntries(identities.map((key) => [key, `/${key}`])),\n      grainPointers: Object.fromEntries(identities.map((key) => [key, `/${key}`])),\n      propertyPointers: {},\n    };\n  }\n  return {\n    table: "",\n    tenantColumn: "tenant_id",\n    identityColumn: "",\n    identityColumns: Object.fromEntries(identities.map((key) => [key, ""])),\n    grainColumns: Object.fromEntries(identities.map((key) => [key, ""])),\n    propertyColumns: {},\n  };\n}\n''',
)
edit(
    "frontend/src/doc.ts",
    'export function emptyMetricPhysical(\n  provider: string,\n  identityKey: string,\n  grain: string[],\n): Record<string, unknown> {\n  const dims = grain.length ? grain : [identityKey];\n',
    'export function emptyMetricPhysical(\n'
    '  provider: string,\n'
    '  identity: string | string[],\n'
    '  grain: string[],\n'
    '): Record<string, unknown> {\n'
    '  const identities = identityList(identity);\n'
    '  const first = identities[0] ?? "id";\n'
    '  const dims = grain.length ? grain : identities.length ? identities : [first];\n',
)
edit(
    "frontend/src/doc.ts",
    '      identityParameter: identityKey,\n      identityPointer: `/${identityKey}`,\n      valuePointer: "/value",\n      grainPointers,\n',
    '      identityParameter: first,\n'
    '      identityPointer: `/${first}`,\n'
    '      identityParameters: Object.fromEntries(identities.map((key) => [key, key])),\n'
    '      identityPointers: Object.fromEntries(identities.map((key) => [key, `/${key}`])),\n'
    '      valuePointer: "/value",\n'
    '      grainPointers,\n',
)
edit(
    "frontend/src/doc.ts",
    '    identityColumn: "",\n    valueColumn: "",\n    grainColumns,\n',
    '    identityColumn: "",\n'
    '    identityColumns: Object.fromEntries(identities.map((key) => [key, ""])),\n'
    '    valueColumn: "",\n'
    '    grainColumns,\n',
)

# --- MappingEditor: preview and author every identity component ---
edit(
    "frontend/src/MappingEditor.tsx",
    '  isOpenApi,\n  mappingResourceLabel,\n',
    '  isOpenApi,\n  mappingCapabilities,\n  mappingResourceLabel,\n',
)
edit(
    "frontend/src/MappingEditor.tsx",
    '  const [identity, setIdentity] = useState("");\n',
    '  const [identity, setIdentity] = useState<Record<string, string>>({});\n',
)
edit(
    "frontend/src/MappingEditor.tsx",
    '    setIdentity("");\n',
    '    setIdentity({});\n',
)
edit(
    "frontend/src/MappingEditor.tsx",
    '  const canPreview = saved && Boolean(identity.trim()) && hasResource && extrasFilled;\n',
    '  const canPreview = saved && identityKeys.length > 0 && identityKeys.every((key) => Boolean(text(identity[key]).trim())) && hasResource && extrasFilled;\n',
)
edit(
    "frontend/src/MappingEditor.tsx",
    '    const identityKey = identityKeys[0] ?? "id";\n    const nextMapping = {\n      ...mapping,\n      sourceId: nextId,\n      provider,\n      physical: metric\n        ? emptyMetricPhysical(provider, identityKey, array(metric.grain).map(String))\n        : emptyMappingPhysical(provider, identityKey),\n    };\n',
    '    const nextMapping = {\n'
    '      ...mapping,\n'
    '      sourceId: nextId,\n'
    '      provider,\n'
    '      identityFields: identityKeys,\n'
    '      capabilities: mappingCapabilities(provider),\n'
    '      physical: metric\n'
    '        ? emptyMetricPhysical(provider, identityKeys, array(metric.grain).map(String))\n'
    '        : emptyMappingPhysical(provider, identityKeys),\n'
    '    };\n',
)
edit(
    "frontend/src/MappingEditor.tsx",
    '      const identityKey = identityKeys[0] ?? "id";\n      const parameter = resource?.parameters?.[0]?.name || text(physical.identityParameter) || identityKey;\n',
    '      const identityKey = identityKeys[0] ?? "id";\n'
    '      const parameter = resource?.parameters?.[0]?.name || text(physical.identityParameter) || identityKey;\n'
    '      const existingParams = object(physical.identityParameters);\n'
    '      const identityParameters = Object.fromEntries(\n'
    '        identityKeys.map((key, index) => [\n'
    '          key,\n'
    '          text(existingParams[key]) || resource?.parameters?.[index]?.name || key,\n'
    '        ]),\n'
    '      );\n',
)
edit(
    "frontend/src/MappingEditor.tsx",
    '        identityParameter: parameter,\n      }, metricMode),\n',
    '        identityParameter: parameter,\n'
    '        identityParameters,\n'
    '      }, metricMode),\n',
)
edit(
    "frontend/src/MappingEditor.tsx",
    '    if (api) {\n      const grainPointers = { ...grain };\n      const propertyPointers = { ...propertyBindings };\n      if (identityField || grain[semantic] !== undefined) {\n        grainPointers[semantic] = value;\n        setPhysical(\n          openApiPhysical(physical, {\n            identityPointer: identityField ? value : physical.identityPointer,\n            grainPointers,\n          }, metricMode),\n        );\n',
    '    if (api) {\n'
    '      const grainPointers = { ...grain };\n'
    '      const propertyPointers = { ...propertyBindings };\n'
    '      if (identityField || grain[semantic] !== undefined) {\n'
    '        grainPointers[semantic] = value;\n'
    '        const identityPointers = { ...object(physical.identityPointers) };\n'
    '        if (identityField) identityPointers[semantic] = value;\n'
    '        setPhysical(\n'
    '          openApiPhysical(physical, {\n'
    '            identityPointer: identityField && semantic === identityKeys[0] ? value : physical.identityPointer,\n'
    '            identityPointers,\n'
    '            grainPointers,\n'
    '          }, metricMode),\n'
    '        );\n',
)
edit(
    "frontend/src/MappingEditor.tsx",
    '    if (identityField || grain[semantic] !== undefined) {\n      setPhysical(\n        postgresPhysical(physical, {\n          identityColumn: identityField ? value : physical.identityColumn,\n          grainColumns: { ...grain, [semantic]: value },\n        }, metricMode),\n      );\n',
    '    if (identityField || grain[semantic] !== undefined) {\n'
    '      const identityColumns = { ...object(physical.identityColumns) };\n'
    '      if (identityField) identityColumns[semantic] = value;\n'
    '      setPhysical(\n'
    '        postgresPhysical(physical, {\n'
    '          identityColumn: identityField && semantic === identityKeys[0] ? value : physical.identityColumn,\n'
    '          identityColumns,\n'
    '          grainColumns: { ...grain, [semantic]: value },\n'
    '        }, metricMode),\n'
    '      );\n',
)
edit(
    "frontend/src/MappingEditor.tsx",
    '    const identityCol = text(physical.identityColumn) || columns[0]?.name;\n    const value = identityCol ? row[identityCol] : null;\n    if (value) setIdentity(String(value));\n',
    '    const values: Record<string, string> = {};\n'
    '    for (const key of identityKeys) {\n'
    '      const column = text(grain[key]) || (key === identityKeys[0] ? text(physical.identityColumn) : "");\n'
    '      if (column && row[column] != null) values[key] = String(row[column]);\n'
    '    }\n'
    '    if (Object.keys(values).length) setIdentity(values);\n',
)
# runPreview payload already says identity; object value will serialize correctly.
edit(
    "frontend/src/MappingEditor.tsx",
    '      <label className="form-field">\n        <span>试读业务键</span>\n        <input value={identity} placeholder="例如 PO-001" onChange={(event) => setIdentity(event.target.value)} />\n      </label>\n',
    '      {identityKeys.map((key) => (\n'
    '        <label className="form-field" key={`preview-${key}`}>\n'
    '          <span>试读业务键 {key}</span>\n'
    '          <input\n'
    '            value={text(identity[key])}\n'
    '            placeholder={key === identityKeys[0] ? "例如 PO-001" : key}\n'
    '            onChange={(event) => setIdentity((current) => ({ ...current, [key]: event.target.value }))}\n'
    '          />\n'
    '        </label>\n'
    '      ))}\n',
)
# API parameter editor becomes one selector per identity component.
edit(
    "frontend/src/MappingEditor.tsx",
    '          {!compact && api ? (\n            <label className="form-field">\n              <span>身份参数</span>\n              <select\n                aria-label="身份参数"\n                value={text(physical.identityParameter)}\n                onChange={(event) =>\n                  setPhysical(openApiPhysical(physical, { identityParameter: event.target.value }, metricMode))\n                }\n              >',
    '          {!compact && api ? identityKeys.map((key) => (\n'
    '            <label className="form-field" key={`identity-param-${key}`}>\n'
    '              <span>身份参数 {key}</span>\n'
    '              <select\n'
    '                aria-label={`身份参数 ${key}`}\n'
    '                value={text(object(physical.identityParameters)[key]) || (key === identityKeys[0] ? text(physical.identityParameter) : key)}\n'
    '                onChange={(event) => {\n'
    '                  const next = { ...object(physical.identityParameters), [key]: event.target.value };\n'
    '                  setPhysical(openApiPhysical(physical, {\n'
    '                    identityParameter: key === identityKeys[0] ? event.target.value : physical.identityParameter,\n'
    '                    identityParameters: next,\n'
    '                  }, metricMode));\n'
    '                }}\n'
    '              >',
)
edit(
    "frontend/src/MappingEditor.tsx",
    '              </select>\n            </label>\n          ) : null}',
    '              </select>\n'
    '            </label>\n'
    '          )) : null}',
)
# bindObjectColumn persists identity pointer/column maps.
edit(
    "frontend/src/MappingEditor.tsx",
    '      return {\n        ...mapping,\n        physical: openApiPhysical(physical, {\n          identityPointer: identityField ? column : physical.identityPointer,\n          grainPointers,\n        }, false),\n      };\n',
    '      const identityPointers = { ...object(physical.identityPointers) };\n'
    '      if (identityField) {\n'
    '        if (column) identityPointers[semantic] = column;\n'
    '        else delete identityPointers[semantic];\n'
    '      }\n'
    '      return {\n'
    '        ...mapping,\n'
    '        physical: openApiPhysical(physical, {\n'
    '          identityPointer: identityField && semantic === array(mapping.identityFields)[0] ? column : physical.identityPointer,\n'
    '          identityPointers,\n'
    '          grainPointers,\n'
    '        }, false),\n'
    '      };\n',
)
edit(
    "frontend/src/MappingEditor.tsx",
    '    return {\n      ...mapping,\n      physical: postgresPhysical(physical, {\n        identityColumn: identityField ? column : physical.identityColumn,\n        grainColumns,\n      }, false),\n    };\n',
    '    const identityColumns = { ...object(physical.identityColumns) };\n'
    '    if (identityField) {\n'
    '      if (column) identityColumns[semantic] = column;\n'
    '      else delete identityColumns[semantic];\n'
    '    }\n'
    '    return {\n'
    '      ...mapping,\n'
    '      physical: postgresPhysical(physical, {\n'
    '        identityColumn: identityField && semantic === array(mapping.identityFields)[0] ? column : physical.identityColumn,\n'
    '        identityColumns,\n'
    '        grainColumns,\n'
    '      }, false),\n'
    '    };\n',
)
edit(
    "frontend/src/MappingEditor.tsx",
    '    identityColumn: patch.identityColumn !== undefined ? patch.identityColumn : physical.identityColumn,\n    grainColumns:',
    '    identityColumn: patch.identityColumn !== undefined ? patch.identityColumn : physical.identityColumn,\n'
    '    identityColumns: patch.identityColumns !== undefined ? patch.identityColumns : object(physical.identityColumns),\n'
    '    grainColumns:',
)
edit(
    "frontend/src/MappingEditor.tsx",
    '    identityPointer: patch.identityPointer !== undefined ? patch.identityPointer : physical.identityPointer,\n    grainPointers:',
    '    identityPointer: patch.identityPointer !== undefined ? patch.identityPointer : physical.identityPointer,\n'
    '    identityParameters: patch.identityParameters !== undefined ? patch.identityParameters : object(physical.identityParameters),\n'
    '    identityPointers: patch.identityPointers !== undefined ? patch.identityPointers : object(physical.identityPointers),\n'
    '    grainPointers:',
)
# new mappings carry the neutral compiled contract in drafts too.
edit(
    "frontend/src/MappingEditor.tsx",
    '  const identityKey = String(array(objectType.identityKeys)[0] ?? "id");\n  const existing = documents.filter',
    '  const identityKeys = array(objectType.identityKeys).map(String);\n  const existing = documents.filter',
)
edit(
    "frontend/src/MappingEditor.tsx",
    '    completeness: existing.length ? "PARTIAL" : "AUTHORITATIVE",\n    physical: emptyMappingPhysical(provider, identityKey),\n',
    '    completeness: existing.length ? "PARTIAL" : "AUTHORITATIVE",\n'
    '    identityFields: identityKeys,\n'
    '    capabilities: mappingCapabilities(provider),\n'
    '    physical: emptyMappingPhysical(provider, identityKeys),\n',
)
edit(
    "frontend/src/MappingEditor.tsx",
    '  const identityKey = String(array(objectType.identityKeys)[0] ?? "id");\n  const grain = array(metric.grain).map(String);\n',
    '  const identityKeys = array(objectType.identityKeys).map(String);\n'
    '  const grain = array(metric.grain).map(String);\n',
)
edit(
    "frontend/src/MappingEditor.tsx",
    '    ...(perspective ? { perspective } : {}),\n    physical: emptyMetricPhysical(provider, identityKey, grain),\n',
    '    ...(perspective ? { perspective } : {}),\n'
    '    identityFields: identityKeys,\n'
    '    capabilities: mappingCapabilities(provider),\n'
    '    physical: emptyMetricPhysical(provider, identityKeys, grain),\n',
)

# --- PropertyMappingSheet: UI already lets users mark multiple business keys; make it executable ---
edit(
    "frontend/src/PropertyMappingSheet.tsx",
    '  isOpenApi,\n  mappingResourceLabel,\n',
    '  isOpenApi,\n  mappingCapabilities,\n  mappingResourceLabel,\n',
)
edit(
    "frontend/src/PropertyMappingSheet.tsx",
    '  text,\n} from "./doc";\n',
    '  text,\n  withIdentityKeys,\n} from "./doc";\n',
)
edit(
    "frontend/src/PropertyMappingSheet.tsx",
    '  const [identity, setIdentity] = useState("");\n',
    '  const [identity, setIdentity] = useState<Record<string, string>>({});\n',
)
edit(
    "frontend/src/PropertyMappingSheet.tsx",
    '    setIdentity("");\n',
    '    setIdentity({});\n',
)
edit(
    "frontend/src/PropertyMappingSheet.tsx",
    '  const canPreview = saved && Boolean(identity.trim()) && hasResource;\n',
    '  const canPreview = saved && identityKeys.length > 0 && identityKeys.every((key) => Boolean(text(identity[key]).trim())) && hasResource;\n',
)
edit(
    "frontend/src/PropertyMappingSheet.tsx",
    '    replaceObject({ ...objectType, properties: nextProperties, identityKeys: nextKeys });\n',
    '    replaceObject(withIdentityKeys({ ...objectType, properties: nextProperties }, nextKeys));\n',
)
edit(
    "frontend/src/PropertyMappingSheet.tsx",
    '    const identityKey = identityKeys[0] ?? "id";\n    const next = {\n      ...focused,\n      sourceId: nextId,\n      provider,\n      physical: emptyMappingPhysical(provider, identityKey),\n    };\n',
    '    const next = {\n'
    '      ...focused,\n'
    '      sourceId: nextId,\n'
    '      provider,\n'
    '      identityFields: identityKeys,\n'
    '      capabilities: mappingCapabilities(provider),\n'
    '      physical: emptyMappingPhysical(provider, identityKeys),\n'
    '    };\n',
)
edit(
    "frontend/src/PropertyMappingSheet.tsx",
    '    const identityCol = text(focusedPhysical.identityColumn) || focusedColumns[0]?.name;\n    if (identityCol && row[identityCol]) setIdentity(String(row[identityCol]));\n',
    '    const values: Record<string, string> = {};\n'
    '    for (const key of identityKeys) {\n'
    '      const column = focused ? columnOf(focused, key, identityKeys) : "";\n'
    '      if (column && row[column] != null) values[key] = String(row[column]);\n'
    '    }\n'
    '    if (Object.keys(values).length) setIdentity(values);\n',
)
# API identity parameter selector in sheet: per key.
edit(
    "frontend/src/PropertyMappingSheet.tsx",
    '            {focusedApi ? (\n              <label className="form-field"><span>身份参数</span>\n                <select\n                  aria-label="身份参数"\n                  value={text(focusedPhysical.identityParameter)}\n                  onChange={(event) => patchFocused({\n                    ...focused,\n                    physical: { ...focusedPhysical, identityParameter: event.target.value },\n                  })}\n                >\n                  {(parameters.length ? parameters : identityKeys.map((item) => ({ name: item }))).map((item) => (\n                    <option key={item.name} value={item.name}>{item.name}</option>\n                  ))}\n                </select>\n              </label>\n            ) : null}\n',
    '            {focusedApi ? identityKeys.map((key) => (\n'
    '              <label className="form-field" key={`api-identity-${key}`}><span>身份参数 {key}</span>\n'
    '                <select\n'
    '                  aria-label={`身份参数 ${key}`}\n'
    '                  value={text(object(focusedPhysical.identityParameters)[key]) || (key === identityKeys[0] ? text(focusedPhysical.identityParameter) : key)}\n'
    '                  onChange={(event) => {\n'
    '                    const identityParameters = { ...object(focusedPhysical.identityParameters), [key]: event.target.value };\n'
    '                    patchFocused({\n'
    '                      ...focused,\n'
    '                      physical: {\n'
    '                        ...focusedPhysical,\n'
    '                        identityParameter: key === identityKeys[0] ? event.target.value : focusedPhysical.identityParameter,\n'
    '                        identityParameters,\n'
    '                      },\n'
    '                    });\n'
    '                  }}\n'
    '                >\n'
    '                  {(parameters.length ? parameters : identityKeys.map((item) => ({ name: item }))).map((item) => (\n'
    '                    <option key={item.name} value={item.name}>{item.name}</option>\n'
    '                  ))}\n'
    '                </select>\n'
    '              </label>\n'
    '            )) : null}\n',
)
# Identity checkbox keeps identity metadata synchronized.
edit(
    "frontend/src/PropertyMappingSheet.tsx",
    '                      replaceObject({ ...objectType, identityKeys: next.length ? next : [semantic] });\n',
    '                      replaceObject(withIdentityKeys(objectType, next.length ? next : [semantic]));\n',
)
# Deleting an identity property also keeps structured metadata in sync.
edit(
    "frontend/src/PropertyMappingSheet.tsx",
    '                  <button className="icon-button" aria-label={`删除属性 ${semantic}`} onClick={() => replaceObject({\n                    ...objectType,\n                    properties: properties.filter((_, position) => position !== index),\n                    identityKeys: identityKeys.filter((item) => item !== semantic).length ? identityKeys.filter((item) => item !== semantic) : identityKeys,\n                  })}>×</button>\n',
    '                  <button className="icon-button" aria-label={`删除属性 ${semantic}`} onClick={() => {\n'
    '                    const nextKeys = identityKeys.filter((item) => item !== semantic);\n'
    '                    replaceObject(withIdentityKeys({\n'
    '                      ...objectType,\n'
    '                      properties: properties.filter((_, position) => position !== index),\n'
    '                    }, nextKeys.length ? nextKeys : identityKeys));\n'
    '                  }}>×</button>\n',
)
# Composite preview form.
edit(
    "frontend/src/PropertyMappingSheet.tsx",
    '              <label className="form-field">\n                <span>试读业务键</span>\n                <input value={identity} placeholder="例如 PO-001" onChange={(event) => setIdentity(event.target.value)} />\n              </label>\n',
    '              {identityKeys.map((key) => (\n'
    '                <label className="form-field" key={`try-${key}`}>\n'
    '                  <span>试读业务键 {key}</span>\n'
    '                  <input\n'
    '                    value={text(identity[key])}\n'
    '                    placeholder={key === identityKeys[0] ? "例如 PO-001" : key}\n'
    '                    onChange={(event) => setIdentity((current) => ({ ...current, [key]: event.target.value }))}\n'
    '                  />\n'
    '                </label>\n'
    '              ))}\n',
)

print("frontend P0 refactor applied")
