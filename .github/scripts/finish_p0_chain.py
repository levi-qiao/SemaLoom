from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace(path: str, old: str, new: str, *, count: int = 1) -> None:
    p = ROOT / path
    text = p.read_text()
    actual = text.count(old)
    if actual < count:
        raise SystemExit(f"{path}: expected >= {count} occurrences, found {actual}: {old[:120]!r}")
    p.write_text(text.replace(old, new, count))


# Backend Studio: composite identity must cross the same Provider contract as Query.
replace(
    "src/semaloom/runtime/studio.py",
    'from semaloom.core.provider import ReadProvider\n',
    'from semaloom.core.provider import IdentityValue, ReadProvider\n',
)
replace(
    "src/semaloom/runtime/studio.py",
    '        "targetKind": "metric" if mapping.target in targets else "object",\n        "identityField": _identity_field(mapping),\n        "requiredBindings": _required_preview_bindings(mapping),\n',
    '        "targetKind": "metric" if mapping.target in targets else "object",\n'
    '        "identityField": _identity_field(mapping),\n'
    '        "capabilities": list(mapping.capabilities),\n'
    '        "requiredBindings": _required_preview_bindings(mapping),\n',
)
replace(
    "src/semaloom/runtime/studio.py",
    '    identity: str,\n',
    '    identity: str | dict[str, str | int | bool],\n',
)
replace(
    "src/semaloom/runtime/studio.py",
    '    metric_ids = {item.id for item in bundle.metrics}\n    extra = _preview_extra_filters(mapping, bindings or {})\n',
    '    metric_ids = {item.id for item in bundle.metrics}\n'
    '    identity_value = _preview_identity(bundle, mapping, identity)\n'
    '    extra = _preview_extra_filters(mapping, bindings or {}, set(identity_value))\n',
)
replace(
    "src/semaloom/runtime/studio.py",
    '            mapping, tenant=tenant, identity_value=identity, extra_filters=extra or None\n',
    '            mapping, tenant=tenant, identity_value=identity_value, extra_filters=extra or None\n',
)
replace(
    "src/semaloom/runtime/studio.py",
    '        result = provider.fetch_object(mapping, tenant=tenant, identity_value=identity)\n',
    '        result = provider.fetch_object(mapping, tenant=tenant, identity_value=identity_value)\n',
)
replace(
    "src/semaloom/runtime/studio.py",
    '    identity_field = _identity_field(mapping)\n    preview_values = {identity_field: identity, **(bindings or {}), **values}\n',
    '    preview_values = {**identity_value, **(bindings or {}), **values}\n',
)
replace(
    "src/semaloom/runtime/studio.py",
    '        "identity": identity,\n',
    '        "identity": identity_value,\n',
)
replace(
    "src/semaloom/runtime/studio.py",
    '\ndef _identity_field(mapping: MappingDef) -> str:\n',
    '''\ndef _preview_identity(\n    bundle: CompiledBundle,\n    mapping: MappingDef,\n    identity: str | dict[str, str | int | bool],\n) -> IdentityValue:\n    obj = next((item for item in bundle.object_types if item.id == mapping.object_type), None)\n    if obj is None or not obj.identity_keys:\n        raise ValueError("UNSUPPORTED_IDENTITY")\n    if isinstance(identity, str):\n        if len(obj.identity_keys) != 1:\n            raise ValueError("COMPOSITE_IDENTITY_REQUIRED")\n        return {obj.identity_keys[0]: identity}\n    value: IdentityValue = dict(identity)\n    if set(value) != set(obj.identity_keys):\n        raise ValueError("INVALID_IDENTITY")\n    return {key: value[key] for key in obj.identity_keys}\n\n\ndef _identity_field(mapping: MappingDef) -> str:\n''',
)
replace(
    "src/semaloom/runtime/studio.py",
    'def _required_preview_bindings(mapping: MappingDef) -> list[str]:\n',
    'def _required_preview_bindings(mapping: MappingDef) -> list[str]:\n',
)
replace(
    "src/semaloom/runtime/studio.py",
    '    identity_col = physical.get("identityColumn")\n    grain = physical.get("grainColumns")\n',
    '    identity_col = physical.get("identityColumn")\n'
    '    identity_semantics = set()\n'
    '    for key in ("identityColumns", "identityPointers"):\n'
    '        raw = physical.get(key)\n'
    '        if isinstance(raw, dict):\n'
    '            identity_semantics.update(str(item) for item in raw)\n'
    '    grain = physical.get("grainColumns")\n',
)
replace(
    "src/semaloom/runtime/studio.py",
    '        if column == identity_col or semantic in locked or column in locked:\n',
    '        if semantic in identity_semantics or column == identity_col or semantic in locked or column in locked:\n',
)
replace(
    "src/semaloom/runtime/studio.py",
    'def _preview_extra_filters(mapping: MappingDef, bindings: dict[str, str]) -> dict[str, str]:\n',
    'def _preview_extra_filters(\n    mapping: MappingDef, bindings: dict[str, str], identity_keys: set[str]\n) -> dict[str, str]:\n',
)
replace(
    "src/semaloom/runtime/studio.py",
    '        if column == identity_col or semantic not in bindings:\n',
    '        if semantic in identity_keys or column == identity_col or semantic not in bindings:\n',
)

# HTTP Studio sample: preserve legacy scalar input only for scalar identities.
replace(
    "src/semaloom/app/http.py",
    '    identity: str\n',
    '    identity: str | dict[str, str]\n',
)
replace(
    "src/semaloom/app/http.py",
    '    envelope = QueryService(bundle, request.app.state.services.provider).execute(\n        QueryRequest(\n            api_version="semaloom/v0.1",\n            select=(\n                ObjectSelect(\n                    object_type=object_id,\n                    identity={object_type.identity_keys[0]: body.identity},\n                    properties=tuple(body.properties),\n                ),\n            ),\n',
    '    if isinstance(body.identity, str):\n'
    '        if len(object_type.identity_keys) != 1:\n'
    '            raise HTTPException(status_code=422, detail="COMPOSITE_IDENTITY_REQUIRED")\n'
    '        identity = {object_type.identity_keys[0]: body.identity}\n'
    '    else:\n'
    '        identity = dict(body.identity)\n'
    '    if set(identity) != set(object_type.identity_keys):\n'
    '        raise HTTPException(status_code=422, detail="INVALID_IDENTITY")\n'
    '    envelope = QueryService(bundle, request.app.state.services.provider).execute(\n'
    '        QueryRequest(\n'
    '            api_version="semaloom/v0.1",\n'
    '            select=(\n'
    '                ObjectSelect(\n'
    '                    object_type=object_id,\n'
    '                    identity=identity,\n'
    '                    properties=tuple(body.properties),\n'
    '                ),\n'
    '            ),\n',
)

# AI instructions: capability-driven wording, not provider-name-driven wording.
replace(
    "src/semaloom/app/chat/system_prompt.txt",
    '集合统计默认同源同事实表。已声明且基数为 ONE 的 PostgreSQL Link，可以用关联对象属性做 groupBy 或筛选（例如 finance.Company.name 或 procurement.Supplier.name）；同源走 SQL JOIN，跨源由引擎按业务键分批对齐，不要发明 SQL，也不要把键列表交给模型循环查询。一对多、非 PostgreSQL 目标、多跳或未声明路径仍不支持。',
    '集合统计是否支持关联分析，以 describe_semantic 返回的 analysisCapabilities 为准。已声明且基数为 ONE、并具备 EQUI_JOIN 能力的 Link，可以用关联对象属性做 groupBy 或筛选（例如 finance.Company.name 或 procurement.Supplier.name）；具体同源 JOIN 或跨源键对齐由引擎执行，不要根据 provider 名称自行猜测能力，不要发明 SQL，也不要把键列表交给模型循环查询。一对多、多跳或未声明/未授权能力仍不支持。',
)

# Frontend wire contract: show neutral capabilities returned by Studio.
replace(
    "frontend/src/types.ts",
    '  identityField: string;\n  requiredBindings: string[];\n',
    '  identityField: string;\n  capabilities: string[];\n  requiredBindings: string[];\n',
)

# Shared draft helpers support every business identity component while keeping legacy first-key fields.
replace(
    "frontend/src/doc.ts",
    'export function emptyMappingPhysical(provider: string, identityKey: string): Record<string, unknown> {\n  if (provider === "openapi") {\n    return {\n      method: "GET",\n      path: "",\n      operationId: "",\n      identityParameter: identityKey,\n      identityPointer: `/${identityKey}`,\n      grainPointers: { [identityKey]: `/${identityKey}` },\n      propertyPointers: {},\n    };\n  }\n  return {\n    table: "",\n    tenantColumn: "tenant_id",\n    identityColumn: "",\n    grainColumns: { [identityKey]: "" },\n    propertyColumns: {},\n  };\n}\n',
    '''export function mappingCapabilities(provider: string): string[] {\n  return provider === "postgres"\n    ? ["POINT_READ", "COLLECTION_READ", "EQUI_JOIN"]\n    : ["POINT_READ"];\n}\n\nfunction identityList(identity: string | string[]): string[] {\n  const values = Array.isArray(identity) ? identity : [identity];\n  return values.map(String).filter(Boolean);\n}\n\nexport function emptyMappingPhysical(provider: string, identity: string | string[]): Record<string, unknown> {\n  const identityKeys = identityList(identity);\n  const first = identityKeys[0] ?? "id";\n  if (provider === "openapi") {\n    return {\n      method: "GET",\n      path: "",\n      operationId: "",\n      identityParameter: first,\n      identityPointer: `/${first}`,\n      identityParameters: Object.fromEntries(identityKeys.map((key) => [key, key])),\n      identityPointers: Object.fromEntries(identityKeys.map((key) => [key, `/${key}`])),\n      grainPointers: Object.fromEntries(identityKeys.map((key) => [key, `/${key}`])),\n      propertyPointers: {},\n    };\n  }\n  return {\n    table: "",\n    tenantColumn: "tenant_id",\n    identityColumn: "",\n    identityColumns: Object.fromEntries(identityKeys.map((key) => [key, ""])),\n    grainColumns: Object.fromEntries(identityKeys.map((key) => [key, ""])),\n    propertyColumns: {},\n  };\n}\n''',
)
replace(
    "frontend/src/doc.ts",
    '  identityKey: string,\n  grain: string[],\n): Record<string, unknown> {\n  const dims = grain.length ? grain : [identityKey];\n',
    '  identity: string | string[],\n  grain: string[],\n): Record<string, unknown> {\n  const identityKeys = identityList(identity);\n  const first = identityKeys[0] ?? "id";\n  const dims = grain.length ? grain : (identityKeys.length ? identityKeys : [first]);\n',
)
replace(
    "frontend/src/doc.ts",
    '      identityParameter: identityKey,\n      identityPointer: `/${identityKey}`,\n      valuePointer: "/value",\n      grainPointers,\n',
    '      identityParameter: first,\n      identityPointer: `/${first}`,\n      identityParameters: Object.fromEntries(identityKeys.map((key) => [key, key])),\n      identityPointers: Object.fromEntries(identityKeys.map((key) => [key, `/${key}`])),\n      valuePointer: "/value",\n      grainPointers,\n',
)
replace(
    "frontend/src/doc.ts",
    '    identityColumn: "",\n    valueColumn: "",\n    grainColumns,\n',
    '    identityColumn: "",\n    identityColumns: Object.fromEntries(identityKeys.map((key) => [key, ""])),\n    valueColumn: "",\n    grainColumns,\n',
)

# Mapping editor: exact composite preview identity + composite physical identity maps.
replace(
    "frontend/src/MappingEditor.tsx",
    '  isOpenApi,\n  mappingResourceLabel,\n',
    '  isOpenApi,\n  mappingCapabilities,\n  mappingResourceLabel,\n',
)
replace(
    "frontend/src/MappingEditor.tsx",
    '  const [identity, setIdentity] = useState("");\n',
    '  const [identity, setIdentity] = useState<Record<string, string>>({});\n',
)
replace(
    "frontend/src/MappingEditor.tsx",
    '    setIdentity("");\n',
    '    setIdentity({});\n',
)
replace(
    "frontend/src/MappingEditor.tsx",
    '  const canPreview = saved && Boolean(identity.trim()) && hasResource && extrasFilled;\n',
    '  const canPreview = saved && identityKeys.length > 0 && identityKeys.every((key) => Boolean(text(identity[key]).trim())) && hasResource && extrasFilled;\n',
)
replace(
    "frontend/src/MappingEditor.tsx",
    '    const identityKey = identityKeys[0] ?? "id";\n    const nextMapping = {\n      ...mapping,\n      sourceId: nextId,\n      provider,\n      physical: metric\n        ? emptyMetricPhysical(provider, identityKey, array(metric.grain).map(String))\n        : emptyMappingPhysical(provider, identityKey),\n    };\n',
    '    const nextMapping = {\n      ...mapping,\n      sourceId: nextId,\n      provider,\n      capabilities: mappingCapabilities(provider),\n      physical: metric\n        ? emptyMetricPhysical(provider, identityKeys, array(metric.grain).map(String))\n        : emptyMappingPhysical(provider, identityKeys),\n    };\n',
)
replace(
    "frontend/src/MappingEditor.tsx",
    '    const identityKey = identityKeys[0] ?? "id";\n    const parameter = resource?.parameters?.[0]?.name || text(physical.identityParameter) || identityKey;\n    setPhysical(\n      openApiPhysical(physical, {\n        path: nextPath,\n        operationId: resource?.operationId || resource?.id || "",\n        identityParameter: parameter,\n      }, metricMode),\n    );\n',
    '    const identityKey = identityKeys[0] ?? "id";\n    const parameter = resource?.parameters?.[0]?.name || text(physical.identityParameter) || identityKey;\n    const previous = object(physical.identityParameters);\n    const identityParameters = Object.fromEntries(identityKeys.map((key, index) => [\n      key,\n      text(previous[key]) || resource?.parameters?.[index]?.name || key,\n    ]));\n    setPhysical(\n      openApiPhysical(physical, {\n        path: nextPath,\n        operationId: resource?.operationId || resource?.id || "",\n        identityParameter: parameter,\n        identityParameters,\n      }, metricMode),\n    );\n',
)
replace(
    "frontend/src/MappingEditor.tsx",
    '          openApiPhysical(physical, {\n            identityPointer: identityField ? value : physical.identityPointer,\n            grainPointers,\n          }, metricMode),\n',
    '          openApiPhysical(physical, {\n            identityPointer: identityField && semantic === identityKeys[0] ? value : physical.identityPointer,\n            identityPointers: identityField\n              ? { ...object(physical.identityPointers), [semantic]: value }\n              : object(physical.identityPointers),\n            grainPointers,\n          }, metricMode),\n',
)
replace(
    "frontend/src/MappingEditor.tsx",
    '          identityColumn: identityField ? value : physical.identityColumn,\n          grainColumns: { ...grain, [semantic]: value },\n',
    '          identityColumn: identityField && semantic === identityKeys[0] ? value : physical.identityColumn,\n          identityColumns: identityField\n            ? { ...object(physical.identityColumns), [semantic]: value }\n            : object(physical.identityColumns),\n          grainColumns: { ...grain, [semantic]: value },\n',
)
replace(
    "frontend/src/MappingEditor.tsx",
    '    const identityCol = text(physical.identityColumn) || columns[0]?.name;\n    const value = identityCol ? row[identityCol] : null;\n    if (value) setIdentity(String(value));\n',
    '    const next: Record<string, string> = {};\n    for (const key of identityKeys) {\n      const column = text(grain[key]) || text(object(physical.identityColumns)[key]) || (key === identityKeys[0] ? text(physical.identityColumn) : "");\n      if (column && row[column] != null) next[key] = String(row[column]);\n    }\n    if (Object.keys(next).length) setIdentity(next);\n',
)
replace(
    "frontend/src/MappingEditor.tsx",
    '          {!compact && api ? (\n            <label className="form-field">\n              <span>身份参数</span>\n              <select\n                aria-label="身份参数"\n                value={text(physical.identityParameter)}\n                onChange={(event) =>\n                  setPhysical(openApiPhysical(physical, { identityParameter: event.target.value }, metricMode))\n                }\n              >\n                {(parameters.length ? parameters : identityKeys.map((item) => ({ name: item }))).map((item) => (\n                  <option key={item.name} value={item.name}>{item.name}</option>\n                ))}\n              </select>\n            </label>\n          ) : null}\n',
    '          {!compact && api ? identityKeys.map((key) => (\n            <label className="form-field" key={`identity-param-${key}`}>\n              <span>身份参数 {key}</span>\n              <select\n                aria-label={`身份参数 ${key}`}\n                value={text(object(physical.identityParameters)[key]) || (key === identityKeys[0] ? text(physical.identityParameter) : key)}\n                onChange={(event) => {\n                  const identityParameters = { ...object(physical.identityParameters), [key]: event.target.value };\n                  setPhysical(openApiPhysical(physical, {\n                    identityParameter: key === identityKeys[0] ? event.target.value : physical.identityParameter,\n                    identityParameters,\n                  }, metricMode));\n                }}\n              >\n                {(parameters.length ? parameters : identityKeys.map((item) => ({ name: item }))).map((item) => (\n                  <option key={item.name} value={item.name}>{item.name}</option>\n                ))}\n              </select>\n            </label>\n          )) : null}\n',
)
replace(
    "frontend/src/MappingEditor.tsx",
    '      <label className="form-field">\n        <span>试读业务键</span>\n        <input value={identity} placeholder="例如 PO-001" onChange={(event) => setIdentity(event.target.value)} />\n      </label>\n',
    '      {identityKeys.map((key) => (\n        <label className="form-field" key={`preview-${key}`}>\n          <span>试读业务键 {key}</span>\n          <input\n            value={text(identity[key])}\n            placeholder={key === identityKeys[0] ? "例如 PO-001" : key}\n            onChange={(event) => setIdentity((current) => ({ ...current, [key]: event.target.value }))}\n          />\n        </label>\n      ))}\n',
)
replace(
    "frontend/src/MappingEditor.tsx",
    '          identityPointer: identityField ? column : physical.identityPointer,\n          grainPointers,\n',
    '          identityPointer: identityField && semantic === array(mapping.identityFields)[0] ? column : physical.identityPointer,\n          identityPointers: identityField\n            ? { ...object(physical.identityPointers), [semantic]: column }\n            : object(physical.identityPointers),\n          grainPointers,\n',
)
# The mapping has no identityFields field in v0.1; use legacy first identity pointer only when absent.
replace(
    "frontend/src/MappingEditor.tsx",
    'identityField && semantic === array(mapping.identityFields)[0]',
    'identityField && text(physical.identityPointer) === text(grain[semantic])',
)
replace(
    "frontend/src/MappingEditor.tsx",
    '        identityColumn: identityField ? column : physical.identityColumn,\n        grainColumns,\n',
    '        identityColumn: identityField && text(physical.identityColumn) === text(grain[semantic]) ? column : physical.identityColumn,\n        identityColumns: identityField\n          ? { ...object(physical.identityColumns), [semantic]: column }\n          : object(physical.identityColumns),\n        grainColumns,\n',
)
replace(
    "frontend/src/MappingEditor.tsx",
    '    identityColumn: patch.identityColumn !== undefined ? patch.identityColumn : physical.identityColumn,\n    grainColumns:',
    '    identityColumn: patch.identityColumn !== undefined ? patch.identityColumn : physical.identityColumn,\n    identityColumns: patch.identityColumns !== undefined ? patch.identityColumns : object(physical.identityColumns),\n    grainColumns:',
)
replace(
    "frontend/src/MappingEditor.tsx",
    '    identityPointer: patch.identityPointer !== undefined ? patch.identityPointer : physical.identityPointer,\n    grainPointers:',
    '    identityPointer: patch.identityPointer !== undefined ? patch.identityPointer : physical.identityPointer,\n    identityParameters: patch.identityParameters !== undefined ? patch.identityParameters : object(physical.identityParameters),\n    identityPointers: patch.identityPointers !== undefined ? patch.identityPointers : object(physical.identityPointers),\n    grainPointers:',
)
replace(
    "frontend/src/MappingEditor.tsx",
    '  const identityKey = String(array(objectType.identityKeys)[0] ?? "id");\n  const existing = documents.filter',
    '  const identityKeys = array(objectType.identityKeys).map(String);\n  const existing = documents.filter',
)
replace(
    "frontend/src/MappingEditor.tsx",
    '    completeness: existing.length ? "PARTIAL" : "AUTHORITATIVE",\n    physical: emptyMappingPhysical(provider, identityKey),\n',
    '    completeness: existing.length ? "PARTIAL" : "AUTHORITATIVE",\n    capabilities: mappingCapabilities(provider),\n    physical: emptyMappingPhysical(provider, identityKeys),\n',
)
replace(
    "frontend/src/MappingEditor.tsx",
    '  const identityKey = String(array(objectType.identityKeys)[0] ?? "id");\n  const grain = array(metric.grain).map(String);\n',
    '  const identityKeys = array(objectType.identityKeys).map(String);\n  const grain = array(metric.grain).map(String);\n',
)
replace(
    "frontend/src/MappingEditor.tsx",
    '    ...(perspective ? { perspective } : {}),\n    physical: emptyMetricPhysical(provider, identityKey, grain),\n',
    '    ...(perspective ? { perspective } : {}),\n    capabilities: mappingCapabilities(provider),\n    physical: emptyMetricPhysical(provider, identityKeys, grain),\n',
)

# Property Mapping Sheet is the other authoring path; keep it aligned.
replace(
    "frontend/src/PropertyMappingSheet.tsx",
    '  isOpenApi,\n  mappingResourceLabel,\n',
    '  isOpenApi,\n  mappingCapabilities,\n  mappingResourceLabel,\n',
)
replace(
    "frontend/src/PropertyMappingSheet.tsx",
    '  const [identity, setIdentity] = useState("");\n',
    '  const [identity, setIdentity] = useState<Record<string, string>>({});\n',
)
replace(
    "frontend/src/PropertyMappingSheet.tsx",
    '    setIdentity("");\n',
    '    setIdentity({});\n',
)
replace(
    "frontend/src/PropertyMappingSheet.tsx",
    '  const canPreview = saved && Boolean(identity.trim()) && hasResource;\n',
    '  const canPreview = saved && identityKeys.length > 0 && identityKeys.every((key) => Boolean(text(identity[key]).trim())) && hasResource;\n',
)
replace(
    "frontend/src/PropertyMappingSheet.tsx",
    '    const identityKey = identityKeys[0] ?? "id";\n    const next = {\n      ...focused,\n      sourceId: nextId,\n      provider,\n      physical: emptyMappingPhysical(provider, identityKey),\n    };\n',
    '    const next = {\n      ...focused,\n      sourceId: nextId,\n      provider,\n      capabilities: mappingCapabilities(provider),\n      physical: emptyMappingPhysical(provider, identityKeys),\n    };\n',
)
replace(
    "frontend/src/PropertyMappingSheet.tsx",
    '    const identityCol = text(focusedPhysical.identityColumn) || focusedColumns[0]?.name;\n    if (identityCol && row[identityCol]) setIdentity(String(row[identityCol]));\n',
    '    const next: Record<string, string> = {};\n    for (const key of identityKeys) {\n      const column = focused ? columnOf(focused, key, identityKeys) : "";\n      if (column && row[column] != null) next[key] = String(row[column]);\n    }\n    if (Object.keys(next).length) setIdentity(next);\n',
)
replace(
    "frontend/src/PropertyMappingSheet.tsx",
    '            {focusedApi ? (\n              <label className="form-field"><span>身份参数</span>\n                <select\n                  aria-label="身份参数"\n                  value={text(focusedPhysical.identityParameter)}\n                  onChange={(event) => patchFocused({\n                    ...focused,\n                    physical: { ...focusedPhysical, identityParameter: event.target.value },\n                  })}\n                >\n                  {(parameters.length ? parameters : identityKeys.map((item) => ({ name: item }))).map((item) => (\n                    <option key={item.name} value={item.name}>{item.name}</option>\n                  ))}\n                </select>\n              </label>\n            ) : null}\n',
    '            {focusedApi ? identityKeys.map((key) => (\n              <label className="form-field" key={`identity-param-${key}`}><span>身份参数 {key}</span>\n                <select\n                  aria-label={`身份参数 ${key}`}\n                  value={text(object(focusedPhysical.identityParameters)[key]) || (key === identityKeys[0] ? text(focusedPhysical.identityParameter) : key)}\n                  onChange={(event) => {\n                    const identityParameters = { ...object(focusedPhysical.identityParameters), [key]: event.target.value };\n                    patchFocused({\n                      ...focused,\n                      physical: {\n                        ...focusedPhysical,\n                        identityParameter: key === identityKeys[0] ? event.target.value : focusedPhysical.identityParameter,\n                        identityParameters,\n                      },\n                    });\n                  }}\n                >\n                  {(parameters.length ? parameters : identityKeys.map((item) => ({ name: item }))).map((item) => (\n                    <option key={item.name} value={item.name}>{item.name}</option>\n                  ))}\n                </select>\n              </label>\n            )) : null}\n',
)
replace(
    "frontend/src/PropertyMappingSheet.tsx",
    '              <label className="form-field">\n                <span>试读业务键</span>\n                <input value={identity} placeholder="例如 PO-001" onChange={(event) => setIdentity(event.target.value)} />\n              </label>\n',
    '              {identityKeys.map((key) => (\n                <label className="form-field" key={`preview-${key}`}>\n                  <span>试读业务键 {key}</span>\n                  <input\n                    value={text(identity[key])}\n                    placeholder={key === identityKeys[0] ? "例如 PO-001" : key}\n                    onChange={(event) => setIdentity((current) => ({ ...current, [key]: event.target.value }))}\n                  />\n                </label>\n              ))}\n',
)

# README should no longer claim point-query composite identities are absent.
replace(
    "README.md",
    'MCP SDK transport (`GET /v0.1/mcp/tools` is a static name list), composite-key query, BOOLEAN /\n',
    'MCP SDK transport (`GET /v0.1/mcp/tools` is a static name list), composite-key Link traversal, BOOLEAN /\n',
)

# Focused backend regression: Query + Studio + AI identity gate share the same exact identity tuple.
(ROOT / "tests/test_composite_identity_chain.py").write_text(r'''from __future__ import annotations

from typing import Any

import pytest

from semaloom.app.chat.tools import SemanticTools, _identity_tuple
from semaloom.compiler.api import compile_documents
from semaloom.core.provider import ObjectRead
from semaloom.core.results import ObjectSelect, QueryContext, QueryRequest
from semaloom.runtime.auth import RequestActor
from semaloom.runtime.discovery import SemanticDiscovery
from semaloom.runtime.query import QueryService
from semaloom.runtime.studio import studio_mapping_preview


def _bundle():
    docs: list[dict[str, Any]] = [
        {
            "apiVersion": "semaloom/v0.1", "kind": "DomainPack", "id": "finance.pack",
            "version": "1.0.0", "contractVersion": "v0.1", "namespace": "finance",
        },
        {
            "apiVersion": "semaloom/v0.1", "kind": "ObjectType", "id": "finance.CompanyLedger",
            "version": "1.0.0", "identityKeys": ["companyId", "ledger"],
            "properties": [
                {"id": "companyId", "valueType": "STRING", "required": True},
                {"id": "ledger", "valueType": "STRING", "required": True},
                {"id": "name", "valueType": "STRING"},
            ],
        },
        {
            "apiVersion": "semaloom/v0.1", "kind": "Mapping", "id": "finance.CompanyLedger.main",
            "version": "1.0.0", "target": "finance.CompanyLedger", "sourceId": "source-a",
            "provider": "postgres", "objectType": "finance.CompanyLedger",
            "expectedCardinality": "ONE", "completeness": "AUTHORITATIVE",
            "capabilities": ["POINT_READ", "COLLECTION_READ", "EQUI_JOIN"],
            "physical": {
                "table": "ledger_rows", "tenantColumn": "tenant_id",
                "identityColumn": "company_id",
                "identityColumns": {"companyId": "company_id", "ledger": "ledger"},
                "grainColumns": {"companyId": "company_id", "ledger": "ledger"},
                "propertyColumns": {"name": "name"},
            },
        },
        {
            "apiVersion": "semaloom/v0.1", "kind": "IntegrationBinding", "id": "integration.source-a",
            "version": "1.0.0", "provider": "postgres", "sourceId": "source-a",
            "mappings": ["finance.CompanyLedger.main"],
        },
    ]
    result = compile_documents(docs)
    assert result.ok, result.diagnostics
    assert result.bundle is not None
    return result.bundle


class Provider:
    def __init__(self) -> None:
        self.identities: list[dict[str, Any]] = []

    def fetch_object(self, mapping: Any, *, tenant: str, identity_value: dict[str, Any]) -> ObjectRead:
        self.identities.append(dict(identity_value))
        return ObjectRead(
            kind="PRESENT", values={**identity_value, "name": "ACME"}, mappingId=mapping.id,
            sourceId=mapping.source_id, observedAt="2026-01-01T00:00:00Z",
        )


def actor() -> RequestActor:
    return RequestActor(tenant="tenant-a", subject="alice", roles=("analyst",))


def test_object_query_carries_complete_composite_identity() -> None:
    provider = Provider()
    service = QueryService(_bundle(), provider)  # type: ignore[arg-type]
    identity = {"companyId": "C1", "ledger": "LOCAL"}
    result = service.execute(
        QueryRequest(
            apiVersion="semaloom/v0.1",
            select=(ObjectSelect(objectType="finance.CompanyLedger", identity=identity, properties=("name",)),),
            context=QueryContext(businessPeriod={"from": "2026-01-01", "to": "2027-01-01"}),
        ), actor(),
    )
    assert result.status == "SUCCEEDED"
    assert provider.identities == [identity]


def test_studio_preview_uses_same_composite_identity() -> None:
    provider = Provider()
    identity = {"companyId": "C1", "ledger": "LOCAL"}
    result = studio_mapping_preview(
        _bundle(), provider, mapping_id="finance.CompanyLedger.main", tenant="tenant-a", identity=identity,
    )
    assert result is not None
    assert result["identity"] == identity
    assert provider.identities == [identity]
    with pytest.raises(ValueError, match="COMPOSITE_IDENTITY_REQUIRED"):
        studio_mapping_preview(
            _bundle(), provider, mapping_id="finance.CompanyLedger.main", tenant="tenant-a", identity="C1",
        )


def test_ai_identity_gate_matches_complete_tuple() -> None:
    provider = Provider()
    service = QueryService(_bundle(), provider)  # type: ignore[arg-type]
    tools = SemanticTools(service, actor())
    identity = {"companyId": "C1", "ledger": "LOCAL"}
    tools.identities.add(("finance.CompanyLedger", _identity_tuple(identity)))
    tools._identity("finance.CompanyLedger", identity)
    with pytest.raises(ValueError, match="RESOLVE_IDENTITY_WITH_FIND_OBJECTS_FIRST"):
        tools._identity("finance.CompanyLedger", {"companyId": "C1", "ledger": "IFRS"})


def test_discovery_reads_neutral_capabilities_not_provider_name() -> None:
    bundle = _bundle()
    document = SemanticDiscovery(bundle).describe("finance.CompanyLedger", actor())
    # Objects are discoverable regardless of physical adapter; capability projection is on related queries/links.
    assert document["id"] == "finance.CompanyLedger"
    assert bundle.mappings[0].capabilities == ("POINT_READ", "COLLECTION_READ", "EQUI_JOIN")
''')

print("P0 full-chain patch applied")
