"""Read-only catalogs of connected source resources. No business row data."""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from semaloom.adapters.postgres import engine_from_url, require_ident

MAX_TABLES = 80
MAX_COLUMNS_PER_TABLE = 48
MAX_PREVIEW_ROWS = 20
MAX_PREVIEW_COLUMNS = 24


def peek_source_rows(
    provider: str,
    url: str,
    table: str,
    schema: str | None,
    tenant: str,
    limit: int = 20,
) -> dict[str, Any]:
    """Bounded tenant-scoped row peek for mapping UI. Identifiers must match the catalog."""
    catalog = introspect_source(provider, url)
    resources = catalog.get("resources") if isinstance(catalog.get("resources"), list) else []
    table_name = require_ident(table, field="table")
    schema_name = require_ident(schema, field="schema") if schema else None
    match = next(
        (
            item
            for item in resources
            if isinstance(item, dict)
            and item.get("name") == table_name
            and (schema_name is None or item.get("schema") == schema_name)
        ),
        None,
    )
    if match is None:
        return {"columns": [], "rows": [], "reason": "TABLE_NOT_IN_CATALOG"}
    column_names = [
        require_ident(item.get("name"), field="column")
        for item in (match.get("columns") or [])[:MAX_PREVIEW_COLUMNS]
        if isinstance(item, dict)
    ]
    if not column_names or provider != "postgres":
        return {
            "columns": column_names,
            "rows": [],
            "reason": None if column_names else "NO_COLUMNS",
        }
    qualified = (
        f"{schema_name}.{table_name}" if schema_name and schema_name != "public" else table_name
    )
    where = ""
    params: dict[str, Any] = {}
    if "tenant_id" in column_names:
        where = " WHERE tenant_id = :tenant"
        params["tenant"] = tenant
    capped = min(limit, MAX_PREVIEW_ROWS)
    sql = text(f"SELECT {', '.join(column_names)} FROM {qualified}{where} LIMIT {capped}")
    engine = engine_from_url(url)
    try:
        with engine.connect() as conn, conn.begin():
            conn.execute(text("SET TRANSACTION READ ONLY"))
            conn.execute(text("SET LOCAL statement_timeout = 5000"))
            fetched = list(conn.execute(sql, params).mappings())
    except (SQLAlchemyError, OSError, ValueError):
        return {"columns": column_names, "rows": [], "reason": "SOURCE_UNAVAILABLE"}
    finally:
        engine.dispose()
    rows = [
        {key: None if row[key] is None else str(row[key]) for key in column_names}
        for row in fetched
    ]
    return {"columns": column_names, "rows": rows, "reason": None}


def introspect_source(provider: str, url: str) -> dict[str, Any]:
    if provider == "postgres":
        return _postgres(url)
    if provider == "openapi":
        return _openapi(url)
    return {"provider": provider, "resources": [], "reason": "UNSUPPORTED_PROVIDER"}


def _postgres(url: str) -> dict[str, Any]:
    engine = engine_from_url(url)
    try:
        with engine.connect() as conn, conn.begin():
            conn.execute(text("SET TRANSACTION READ ONLY"))
            conn.execute(text("SET LOCAL statement_timeout = 5000"))
            rows = list(
                conn.execute(
                    text(
                        """
                        SELECT table_schema, table_name, column_name, data_type
                        FROM information_schema.columns
                        WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                        ORDER BY table_schema, table_name, ordinal_position
                        """
                    )
                )
            )
    except (SQLAlchemyError, OSError):
        return {"provider": "postgres", "resources": [], "reason": "SOURCE_UNAVAILABLE"}
    finally:
        engine.dispose()

    grouped: dict[tuple[str, str], list[dict[str, str]]] = {}
    for schema, table, column, data_type in rows:
        key = (str(schema), str(table))
        columns = grouped.setdefault(key, [])
        if len(columns) >= MAX_COLUMNS_PER_TABLE:
            continue
        columns.append({"name": str(column), "type": str(data_type)})
    resources = [
        {
            "id": f"{schema}.{table}",
            "schema": schema,
            "name": table,
            "kind": "table",
            "columns": columns,
        }
        for (schema, table), columns in list(grouped.items())[:MAX_TABLES]
    ]
    return {"provider": "postgres", "resources": resources, "reason": None}


def _openapi(url: str) -> dict[str, Any]:
    base = url.rstrip("/")
    payload: dict[str, Any] | None = None
    try:
        response = httpx.get(f"{base}/openapi.json", timeout=5.0)
        if 200 <= response.status_code < 300:
            body = response.json()
            if isinstance(body, dict):
                payload = body
    except (httpx.HTTPError, ValueError):
        payload = None
    if payload is None:
        return {"provider": "openapi", "resources": [], "reason": "SPEC_UNAVAILABLE"}
    paths = payload.get("paths")
    if not isinstance(paths, dict):
        return {"provider": "openapi", "resources": [], "reason": "SPEC_UNAVAILABLE"}
    components = payload.get("components")
    raw_schemas = components.get("schemas") if isinstance(components, dict) else None
    schemas = raw_schemas if isinstance(raw_schemas, dict) else {}
    resources: list[dict[str, Any]] = []
    for path, item in list(paths.items())[:MAX_TABLES]:
        if not isinstance(item, dict):
            continue
        path_params = item.get("parameters") if isinstance(item.get("parameters"), list) else []
        for method, operation in item.items():
            if method.lower() != "get" or not isinstance(operation, dict):
                continue
            operation_id = operation.get("operationId")
            parameters = _openapi_parameters(path_params, operation.get("parameters"))
            resources.append(
                {
                    "id": str(operation_id or f"GET {path}"),
                    "schema": None,
                    "name": str(path),
                    "kind": "operation",
                    "columns": _openapi_response_fields(operation, schemas),
                    "method": "GET",
                    "operationId": None if operation_id is None else str(operation_id),
                    "parameters": parameters,
                }
            )
    return {"provider": "openapi", "resources": resources, "reason": None}


def _openapi_parameters(path_params: object, operation_params: object) -> list[dict[str, str]]:
    collected: list[dict[str, str]] = []
    seen: set[str] = set()
    for source in (path_params, operation_params):
        if not isinstance(source, list):
            continue
        for item in source:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not isinstance(name, str) or name in seen or name == "tenant":
                continue
            seen.add(name)
            collected.append({"name": name, "in": str(item.get("in") or "query")})
    return collected


def _openapi_response_fields(
    operation: dict[str, Any], schemas: dict[str, Any]
) -> list[dict[str, str]]:
    responses = operation.get("responses")
    if not isinstance(responses, dict):
        return []
    success = responses.get("200") or responses.get("201") or responses.get("default")
    if not isinstance(success, dict):
        return []
    content = success.get("content")
    if not isinstance(content, dict):
        return []
    json_body = content.get("application/json")
    if not isinstance(json_body, dict):
        json_body = next((item for item in content.values() if isinstance(item, dict)), None)
    if not isinstance(json_body, dict):
        return []
    schema = _resolve_schema(json_body.get("schema"), schemas)
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return []
    fields: list[dict[str, str]] = []
    for name, spec in list(properties.items())[:MAX_COLUMNS_PER_TABLE]:
        declared = spec.get("type") if isinstance(spec, dict) else None
        fields.append({"name": f"/{name}", "type": str(declared or "string")})
    return fields


def _resolve_schema(schema: object, schemas: dict[str, Any], depth: int = 0) -> dict[str, Any]:
    if not isinstance(schema, dict) or depth > 6:
        return {}
    ref = schema.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
        return _resolve_schema(schemas.get(ref.rsplit("/", 1)[-1]), schemas, depth + 1)
    if "allOf" in schema and isinstance(schema["allOf"], list):
        merged: dict[str, Any] = {"properties": {}}
        for item in schema["allOf"]:
            part = _resolve_schema(item, schemas, depth + 1)
            properties = part.get("properties")
            if isinstance(properties, dict):
                merged["properties"].update(properties)
        return merged
    return schema
