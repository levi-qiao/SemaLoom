from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def patch(path: str, old: str, new: str, *, count: int = 1) -> None:
    target = ROOT / path
    text = target.read_text()
    actual = text.count(old)
    if actual < count:
        raise SystemExit(f"{path}: expected >= {count} occurrences, found {actual}: {old[:100]!r}")
    target.write_text(text.replace(old, new, count))


editor = "frontend/src/MappingEditor.tsx"

patch(
    editor,
    '  const [identity, setIdentity] = useState("");\n',
    '  const [identity, setIdentity] = useState<Record<string, string>>({});\n',
)
patch(editor, '  const primaryIdentity = identityKeys[0] ?? "id";\n', "")
patch(editor, '    setIdentity("");\n', "    setIdentity({});\n")
patch(
    editor,
    '  }, [grain, propertyBindings, physical.identityColumns, physical.identityColumn, physical.valueColumn]);\n',
    '  }, [grain, propertyBindings, physical.valueColumn]);\n',
)
patch(
    editor,
    '  const canPreview = saved && Boolean(identity.trim()) && hasResource && extrasFilled;\n',
    '  const identityFilled = identityKeys.length > 0 && identityKeys.every((key) => Boolean(text(identity[key]).trim()));\n'
    '  const canPreview = saved && identityFilled && hasResource && extrasFilled;\n',
)
patch(
    editor,
    '''  function selectOperation(nextPath: string) {
    const resource = operations.find((item) => item.name === nextPath);
    const parameter = resource?.parameters?.[0]?.name || text(physical.identityParameter) || primaryIdentity;
    const parameterBindings = { ...object(physical.parameterBindings), [primaryIdentity]: parameter };
    setPhysical(
      openApiPhysical(physical, {
        path: nextPath,
        operationId: resource?.operationId || resource?.id || "",
        parameterBindings,
      }, metricMode),
    );
  }
''',
    '''  function selectOperation(nextPath: string) {
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
''',
)
patch(
    editor,
    '''      if (identityField || grain[semantic] !== undefined) {
        grainPointers[semantic] = value;
        const identityPointers = { ...object(physical.identityPointers) };
        if (identityField) identityPointers[semantic] = value;
        setPhysical(
          openApiPhysical(physical, {
            identityPointer: identityField && semantic === primaryIdentity ? value : physical.identityPointer,
            identityPointers,
            grainPointers,
          }, metricMode),
        );
        return;
      }
''',
    '''      if (identityField || grain[semantic] !== undefined) {
        if (value) grainPointers[semantic] = value;
        else delete grainPointers[semantic];
        setPhysical(openApiPhysical(physical, { grainPointers }, metricMode));
        return;
      }
''',
)
patch(
    editor,
    '''    if (identityField || grain[semantic] !== undefined) {
      const identityColumns = { ...object(physical.identityColumns) };
      if (identityField) identityColumns[semantic] = value;
      setPhysical(
        postgresPhysical(physical, {
          identityColumn: identityField && semantic === primaryIdentity ? value : physical.identityColumn,
          identityColumns,
          grainColumns: { ...grain, [semantic]: value },
        }, metricMode),
      );
      return;
    }
''',
    '''    if (identityField || grain[semantic] !== undefined) {
      const grainColumns = { ...grain };
      if (value) grainColumns[semantic] = value;
      else delete grainColumns[semantic];
      setPhysical(postgresPhysical(physical, { grainColumns }, metricMode));
      return;
    }
''',
)
patch(
    editor,
    '''  function pickRow(index: number, row: Record<string, string | null>) {
    setPickedRow(index);
    const nextBindings: Record<string, string> = { ...bindings };
    for (const key of identityKeys) {
      const column = text(grain[key]) || text(object(physical.identityColumns)[key]);
      const value = column ? row[column] : null;
      if (value == null) continue;
      if (key === primaryIdentity) setIdentity(String(value));
      else nextBindings[key] = String(value);
    }
    setBindings(nextBindings);
  }
''',
    '''  function pickRow(index: number, row: Record<string, string | null>) {
    setPickedRow(index);
    const nextIdentity: Record<string, string> = { ...identity };
    for (const key of identityKeys) {
      const column = text(grain[key]);
      const value = column ? row[column] : null;
      if (value != null) nextIdentity[key] = String(value);
    }
    setIdentity(nextIdentity);
  }
''',
)
patch(
    editor,
    '''          {!compact && api ? (
            <label className="form-field">
              <span>主身份参数</span>
              <select
                aria-label="主身份参数"
                value={text(physical.identityParameter)}
                onChange={(event) => {
                  const parameterBindings = {
                    ...object(physical.parameterBindings),
                    [primaryIdentity]: event.target.value,
                  };
                  setPhysical(openApiPhysical(physical, {
                    identityParameter: event.target.value,
                    parameterBindings,
                  }, metricMode));
                }}
              >
                {(parameters.length ? parameters : identityKeys.map((item) => ({ name: item }))).map((item) => (
                  <option key={item.name} value={item.name}>{item.name}</option>
                ))}
              </select>
            </label>
          ) : null}
''',
    '''          {!compact && api ? identityKeys.map((key) => (
            <label className="form-field" key={key}>
              <span>请求参数 {key}</span>
              <select
                aria-label={`请求参数 ${key}`}
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
''',
)
patch(
    editor,
    '            const value = text(grain[semantic]) || (identityField ? text(object(physical.identityColumns)[semantic]) || text(physical.identityColumn) : "");\n',
    '            const value = text(grain[semantic]);\n',
)
patch(
    editor,
    '''      <label className="form-field">
        <span>试读 {primaryIdentity}</span>
        <input value={identity} placeholder="输入主业务键" onChange={(event) => setIdentity(event.target.value)} />
      </label>
      {extraBindings.map((dim) => (
''',
    '''      {identityKeys.map((key) => (
        <label className="form-field" key={key}>
          <span>试读 {key}</span>
          <input
            aria-label={`试读 ${key}`}
            value={text(identity[key])}
            placeholder={`输入 ${key}`}
            onChange={(event) => setIdentity((current) => ({ ...current, [key]: event.target.value }))}
          />
        </label>
      ))}
      {extraBindings.map((dim) => (
''',
)
patch(
    editor,
    '''      const identityPointers = { ...object(physical.identityPointers) };
      if (identityField) {
        if (column) identityPointers[semantic] = column;
        else delete identityPointers[semantic];
      }
      return {
        ...mapping,
        physical: openApiPhysical(physical, {
          identityPointers,
          grainPointers,
        }, false),
      };
''',
    '''      return {
        ...mapping,
        physical: openApiPhysical(physical, { grainPointers }, false),
      };
''',
)
patch(
    editor,
    '''    const identityColumns = { ...object(physical.identityColumns) };
    if (identityField) {
      if (column) identityColumns[semantic] = column;
      else delete identityColumns[semantic];
    }
    return {
      ...mapping,
      physical: postgresPhysical(physical, {
        identityColumns,
        grainColumns,
      }, false),
    };
''',
    '''    return {
      ...mapping,
      physical: postgresPhysical(physical, { grainColumns }, false),
    };
''',
)
patch(
    editor,
    '    identityParameter: patch.identityParameter !== undefined ? patch.identityParameter : physical.identityParameter,\n',
    "",
)
patch(
    editor,
    '  const required = identityKeys.slice(1);\n',
    '  const required: string[] = [];\n',
)
patch(
    editor,
    '  const grain = object(physical.grainColumns);\n  for (const [semantic, column] of Object.entries(grain)) {\n',
    '  const grain = { ...object(physical.grainColumns), ...object(physical.grainPointers) };\n  for (const [semantic, column] of Object.entries(grain)) {\n',
    count=1,
)

patch(
    "frontend/tests/studio.spec.ts",
    '  await page.getByPlaceholder("例如 PO-001").first().fill("PO-001");\n',
    '  await page.getByLabel("试读 orderId").first().fill("PO-001");\n',
)

test_path = ROOT / "tests/test_composite_identity_chain.py"
test_text = test_path.read_text()
if "test_frontend_editor_has_no_legacy_identity_mapping_fields" not in test_text:
    test_text += '''\n\ndef test_frontend_editor_has_no_legacy_identity_mapping_fields() -> None:\n    editor = (ROOT / "frontend/src/MappingEditor.tsx").read_text()\n    forbidden = (\n        "identityColumn",\n        "identityColumns",\n        "identityPointer",\n        "identityPointers",\n        "identityParameter",\n    )\n    assert all(token not in editor for token in forbidden)\n'''
    test_path.write_text(test_text)

editor_text = (ROOT / editor).read_text()
for token in (
    "identityColumn",
    "identityColumns",
    "identityPointer",
    "identityPointers",
    "identityParameter",
):
    if token in editor_text:
        raise SystemExit(f"legacy identity token remains in MappingEditor: {token}")
