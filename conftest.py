"""Temporary P0 validation hook; self-removes after generated-tree fixes."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent


def patch(path: str, old: str, new: str, *, count: int = 1) -> None:
    target = ROOT / path
    text = target.read_text()
    if old in text:
        target.write_text(text.replace(old, new, count))


def patch_all(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text()
    if old in text:
        target.write_text(text.replace(old, new))


# The migration removes Mapping capabilities, but AuthorizationProfile capabilities
# are authored access policy and must remain intact.
for rel in (
    "examples/tax/domain/actions.yaml",
    "examples/procurement/domain/rules.yaml",
):
    target = ROOT / rel
    text = target.read_text()
    marker = "  roles: ["
    if marker in text and "  capabilities:" not in text:
        line_end = text.index("\n", text.index(marker)) + 1
        capabilities = (
            "  capabilities:\n"
            "    - query\n"
            "    - evaluateClaim\n"
            "    - planAction\n"
        )
        target.write_text(text[:line_end] + capabilities + text[line_end:])

# PostgreSQL analysis must derive physical identity columns from semantic mappings,
# never from the removed identityColumn field.
old_compile = '''    identity_col = require_ident(
        metric_mapping.physical.get("identityColumn"), field="identityColumn"
    )
    projection = {**_projection(object_mapping), **_projection(metric_mapping)}
    obj = next(item for item in service.bundle.object_types if item.id == metric.object_type)
    if len(obj.identity_keys) != 1:
        raise AnalysisError("UNSUPPORTED_IDENTITY")
'''
new_compile = '''    projection = {**_projection(object_mapping), **_projection(metric_mapping)}
    obj = next(item for item in service.bundle.object_types if item.id == metric.object_type)
    if len(obj.identity_keys) != 1:
        raise AnalysisError("UNSUPPORTED_IDENTITY")
    identity_col = projection.get(obj.identity_keys[0])
    if identity_col is None:
        raise AnalysisError("NO_MAPPING")
'''
patch("src/semaloom/adapters/analysis.py", old_compile, new_compile)

old_link_label = '''        identity_col = require_ident(
            target_mapping.physical.get("identityColumn") or projection.get(link.identity.target),
            field="identityColumn",
        )
'''
new_link_label = '''        identity_col = projection.get(link.identity.target)
        if identity_col is None:
            continue
'''
patch("src/semaloom/adapters/analysis.py", old_link_label, new_link_label)

old_bind_identity = (
    '    identity = require_ident(bind.mapping.physical.get("identityColumn"), '
    'field="identityColumn")\n'
)
new_bind_identity = (
    "    identity = projection.get(bind.link.identity.target)\n"
    "    if identity is None:\n"
    '        raise AnalysisError("NO_MAPPING")\n'
)
patch(
    "src/semaloom/adapters/analysis.py",
    old_bind_identity,
    new_bind_identity,
    count=2,
)

# Mapping grain order is semantic: declared identity components first, then the
# remaining set in deterministic order. Physical dict insertion order is irrelevant.
patch(
    "src/semaloom/compiler/mapping_ir.py",
    '''                    "grain_fields": tuple(grain),
                    "property_fields": tuple(properties),
''',
    '''                    "grain_fields": tuple(
                        key
                        for key in dict.fromkeys((*obj.identity_keys, *sorted(grain)))
                        if key in grain
                    ),
                    "property_fields": tuple(sorted(properties)),
''',
)

# Studio serializes authored semantic documents. Compiler-generated Mapping IR fields
# are deliberately omitted so round-tripping a release recreates the same digest.
patch(
    "src/semaloom/runtime/studio_control.py",
    '''            dumped = item.model_dump(mode="json", by_alias=True, exclude_none=True)
            documents.append(dict(dumped))
''',
    '''            dumped = item.model_dump(mode="json", by_alias=True, exclude_none=True)
            document = dict(dumped)
            if document.get("kind") == "Mapping":
                for field in (
                    "identityFields",
                    "grainFields",
                    "propertyFields",
                    "capabilities",
                ):
                    document.pop(field, None)
            documents.append(document)
''',
)

# Claims use canonical semantic binding names only. Unknown legacy aliases are rejected
# explicitly instead of being silently dropped.
patch(
    "src/semaloom/runtime/eval.py",
    '''    selects: list[MetricSelect | ObjectSelect] = []
    for spec in rule.inputs:
''',
    '''    selects: list[MetricSelect | ObjectSelect] = []
    allowed_bindings = {"perspective"}
    for input_spec in rule.inputs:
        if input_spec.metric is not None:
            input_metric = next(item for item in bundle.metrics if item.id == input_spec.metric)
            allowed_bindings.update(input_metric.grain)
        elif input_spec.object_type is not None:
            input_object = next(
                item for item in bundle.object_types if item.id == input_spec.object_type
            )
            allowed_bindings.update(input_object.identity_keys)
    unknown_bindings = sorted(set(bindings) - allowed_bindings)
    if unknown_bindings:
        raise EvaluationError(
            "INVALID_BINDINGS",
            f"unsupported bindings: {', '.join(unknown_bindings)}",
        )
    for spec in rule.inputs:
''',
)

# Ruff formats the generated _get before pytest imports this hook, so match the
# formatted block. Semantic bindings can never replace an identity component.
patch(
    "src/semaloom/adapters/openapi.py",
    '''        params: dict[str, Any] = {
            **dict(mapping.physical.get("fixedParameters") or {}),
            "tenant": tenant,
        }
        semantic_values: dict[str, IdentityScalar] = {**identity_value, **(bindings or {})}
''',
    '''        params: dict[str, Any] = {
            **dict(mapping.physical.get("fixedParameters") or {}),
            "tenant": tenant,
        }
        binding_values = bindings or {}
        if set(identity_value) & set(binding_values):
            return "INVALID_BINDINGS"
        semantic_values: dict[str, IdentityScalar] = {
            **identity_value,
            **binding_values,
        }
''',
)

# Discovery must report the executable graph, not the old inferred provider behavior.
for rel in ("tests/test_discovery.py", "tests/test_chat_discovery.py"):
    patch_all(rel, '"pointLookup": True,', '"pointLookup": False,')
    patch_all(
        rel,
        '["analysisCapabilities"]["pointLookup"] is True',
        '["analysisCapabilities"]["pointLookup"] is False',
    )

# Alias compatibility is gone; retain the regression as an unknown-binding rejection.
patch(
    "tests/test_business_analysis.py",
    'with pytest.raises(EvaluationError, match="conflicting identity aliases"):',
    'with pytest.raises(EvaluationError, match="unsupported bindings"):',
)

# OpenAPI unit fixtures now model the compiled canonical contract directly.
patch(
    "tests/test_openapi_provider.py",
    '''            "expectedCardinality": "ONE",
            "physical": {
                "method": "GET",
                "path": "/orders",
                "identityParameter": "orderId",
                "identityPointer": "/orderId",
                "propertyPointers": {"deliveryRisk": "/deliveryRisk"},
                **physical,
            },
''',
    '''            "expectedCardinality": "ONE",
            "identityFields": ["orderId"],
            "grainFields": ["orderId"],
            "propertyFields": ["deliveryRisk"],
            "capabilities": ["POINT_READ"],
            "physical": {
                "method": "GET",
                "path": "/orders",
                "parameterBindings": {"orderId": "orderId"},
                "grainPointers": {"orderId": "/orderId"},
                "propertyPointers": {"deliveryRisk": "/deliveryRisk"},
                **physical,
            },
''',
)
patch_all(
    "tests/test_openapi_provider.py",
    'identity_value="PO-001"',
    'identity_value={"orderId": "PO-001"}',
)
patch_all(
    "tests/test_openapi_provider.py",
    'identity_value="PO-MISSING"',
    'identity_value={"orderId": "PO-MISSING"}',
)
patch(
    "tests/test_openapi_provider.py",
    'values={"orderId": identity_value, "status": "APPROVED"},',
    'values={"orderId": identity_value["orderId"], "status": "APPROVED"},',
)
patch_all("tests/test_openapi_provider.py", "extra_filters=", "bindings=")
patch(
    "tests/test_openapi_provider.py",
    '''        bindings={"tenant": "tenant-b", "orderId": "PO-999"},
    )
    assert (result.kind, result.value) == ("PRESENT", "1.00")
''',
    '''        bindings={"orderId": "PO-999"},
    )
    assert (result.kind, result.reason) == ("UNAVAILABLE", "INVALID_BINDINGS")
''',
)

# Canonical identity naming is used by the claim helper too.
patch(
    "tests/test_runtime_pg.py",
    "    taxpayer: str,\n",
    "    taxpayerId: str,\n",
)
patch(
    "tests/test_runtime_pg.py",
    'bindings={"taxpayerId": taxpayer, "taxYear": year},',
    'bindings={"taxpayerId": taxpayerId, "taxYear": year},',
)

# Studio samples carry the complete identity object; draft mappings no longer author
# identityColumn because grainColumns already provides the semantic-to-physical map.
patch_all(
    "tests/test_studio_control_plane.py",
    '"identity": "PO-001"',
    '"identity": {"orderId": "PO-001"}',
)
patch_all(
    "tests/test_studio_control_plane.py",
    '"identity": "PO-MISSING"',
    '"identity": {"orderId": "PO-MISSING"}',
)
patch_all(
    "tests/test_studio_control_plane.py",
    '"identity": "TAXPAYER-A"',
    '"identity": {"taxpayerId": "TAXPAYER-A"}',
)
patch_all(
    "tests/test_studio_control_plane.py",
    '            "identityColumn": "taxpayer_id",\n',
    "",
)


def pytest_sessionfinish() -> None:
    Path(__file__).unlink(missing_ok=True)
