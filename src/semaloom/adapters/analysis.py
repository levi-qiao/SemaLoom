"""PostgreSQL physical analysis implementation; public inputs remain semantic."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, replace
from decimal import Decimal, localcontext
from typing import Any

import sqlglot
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlglot import exp

from semaloom.adapters.postgres import require_ident
from semaloom.core.bundle import CompiledBundle
from semaloom.core.model import EmbeddedProperty, LinkDef, MappingDef, MetricDef, ObjectTypeDef
from semaloom.core.semantic_query import (
    AnalysisError,
    ComparisonExpr,
    EvidenceColumn,
    EvidenceTable,
    FilterAtom,
    FilterGroup,
    GroupByItem,
    PlanRef,
    QueryResult,
    SemanticQuery,
    TypedValue,
    conflicting_equalities,
)


@dataclass
class _Context:
    bundle: CompiledBundle
    provider: Any
    bind_provider: Any | None = None


_ALLOWED_FUNCS = frozenset(
    {
        "cast",
        "sum",
        "min",
        "max",
        "count",
        "avg",
        "nullif",
        "date_trunc",
        "and",
        "or",
        "not",
        "eq",
        "neq",
        "gt",
        "lt",
        "gte",
        "lte",
        "in",
        "between",
        "is",
        "like",
    }
)
_OP_SQL = {"EQ": "=", "NE": "<>", "LT": "<", "LE": "<=", "GT": ">", "GE": ">="}

_CMP_BACK = {
    "SHARE_OF_TOTAL": "shareOfTotal",
    "RELATIVE_TO_MEAN": "percentAboveMean",
    "STRICT_PEER": "outperforms",
}


@dataclass
class _Plan:
    aggregation: str
    comparison: ComparisonExpr | None
    count_sql: str
    evidence_sql: str
    identity_col: str
    metric: MetricDef
    metric_mapping: MappingDef
    params: dict[str, Any]
    projection: dict[str, str]
    query: SemanticQuery
    sql: str
    table: str
    from_sql: str
    tenant_col: str
    unit_col: str | None
    value_col: str
    where: list[str]
    bind_joins: tuple[_BindJoin, ...] = ()


def _metric(service: _Context, metric_id: str) -> MetricDef:
    metric = next((item for item in service.bundle.metrics if item.id == metric_id), None)
    if metric is None:
        raise AnalysisError("POPULATION_NOT_DECLARED")
    return metric


def _bare(field: str) -> str:
    return field.split(".")[-1]


def _mapping(service: _Context, target: str) -> MappingDef:
    matches = [
        item
        for item in service.bundle.mappings
        if item.target == target and item.provider == "postgres"
    ]
    if not matches:
        raise AnalysisError("NO_MAPPING")
    if len({item.source_id for item in matches}) > 1:
        raise AnalysisError("CROSS_SOURCE_SQL")
    if len(matches) != 1:
        raise AnalysisError("AMBIGUOUS_MAPPING")
    return matches[0]


def _derived_sql(service: _Context, metric: MetricDef, projection: dict[str, str]) -> str | None:
    if not metric.derived_from:
        return None
    inputs: dict[str, str] = {}
    locations = set()
    rule = next((item for item in service.bundle.rules if item.output_metric == metric.id), None)
    if rule is None:
        return None
    for spec in rule.inputs:
        if spec.metric is None:
            return None
        mapping = _mapping(service, spec.metric)
        locations.add((mapping.source_id, mapping.physical.get("table")))
        column = _projection(mapping).get("__value__")
        if column is None:
            return None
        inputs[spec.name] = column
    if len(locations) != 1:
        raise AnalysisError("LINK_ANALYSIS_UNSUPPORTED")
    return _sql_expr(rule.expression, inputs)


def _sql_expr(expr: dict[str, Any], inputs: dict[str, str]) -> str | None:
    op = expr.get("op")
    if op == "ref":
        return inputs.get(str(expr.get("name")))
    if op in {"add", "sub", "mul", "div"}:
        args = [_sql_expr(item, inputs) for item in expr.get("args", ())]
        if any(item is None for item in args):
            return None
        joiner = {"add": "+", "sub": "-", "mul": "*", "div": "/"}[op]
        return "(" + f" {joiner} ".join(args) + ")"  # type: ignore[arg-type]
    return None


def _projection(mapping: MappingDef) -> dict[str, str]:
    projection: dict[str, str] = {}
    for field in ("grainColumns", "propertyColumns"):
        raw = mapping.physical.get(field)
        if isinstance(raw, dict):
            for semantic, column in raw.items():
                projection[require_ident(semantic, field="semantic")] = require_ident(
                    str(column), field="column"
                )
    value = mapping.physical.get("valueColumn")
    if isinstance(value, str):
        projection["__value__"] = require_ident(value, field="valueColumn")
    return projection


def _property_ids(obj: ObjectTypeDef) -> set[str]:
    return {prop.id for prop in obj.properties} | set(obj.identity_keys)


def _referenced_fields(query: SemanticQuery) -> tuple[str, ...]:
    names: list[str] = []

    def walk(node: FilterAtom | FilterGroup | None) -> None:
        if isinstance(node, FilterAtom):
            names.append(node.field)
        elif isinstance(node, FilterGroup):
            for arg in node.args:
                walk(arg)

    walk(query.filters)
    names.extend(item.id for item in query.group_by)
    reserved = {"value", "total"}
    if query.metrics:
        reserved.add(query.metrics[0].id)
    names.extend(item.field for item in query.order_by if item.field not in reserved)
    return tuple(dict.fromkeys(names))


def _is_local_field(obj: ObjectTypeDef, field: str) -> bool:
    name = _bare(field)
    return name in _property_ids(obj) and field in {name, f"{obj.id}.{name}"}


@dataclass(frozen=True)
class _ResolvedLink:
    link: LinkDef
    target: ObjectTypeDef
    mapping: MappingDef
    field: str
    same_source: bool


@dataclass(frozen=True)
class _BindJoin:
    link: LinkDef
    target: ObjectTypeDef
    mapping: MappingDef
    local_key: str
    remote_field: str
    query_field: str
    filter_atom: FilterAtom | None = None


_BIND_KEY_LIMIT = 1000
_BIND_BATCH = 50


def _one_link_join(
    service: _Context, source_id: str, field: str, source_physical: str
) -> _ResolvedLink | None:
    name = _bare(field)
    qualified = field[: -len(name) - 1] if "." in field and field.endswith("." + name) else None
    found: list[_ResolvedLink] = []
    for link in service.bundle.links:
        if link.source != source_id or link.traversal != "FORWARD":
            continue
        target = _object_type(service.bundle, link.target)
        if target is None or name not in _property_ids(target):
            continue
        if qualified not in {None, target.id}:
            continue
        if link.cardinality != "ONE":
            raise AnalysisError("UNBOUNDED_MANY_TO_MANY")
        mapping = _mapping(service, target.id)
        if mapping.provider != "postgres":
            raise AnalysisError("CROSS_SOURCE_SQL")
        found.append(
            _ResolvedLink(
                link=link,
                target=target,
                mapping=mapping,
                field=name,
                same_source=mapping.source_id == source_physical,
            )
        )
    if len(found) > 1:
        raise AnalysisError("AMBIGUOUS_MAPPING")
    return found[0] if found else None


def _qualify_simple(column: str, alias: str) -> str:
    if not column or "." in column or "(" in column or " " in column:
        return column
    return f"{alias}.{column}"


def _bind_from_resolved(resolved: _ResolvedLink, query_field: str) -> _BindJoin:
    return _BindJoin(
        link=resolved.link,
        target=resolved.target,
        mapping=resolved.mapping,
        local_key=resolved.link.identity.source,
        remote_field=resolved.field,
        query_field=query_field,
    )


def _strip_bind_filters(
    node: FilterAtom | FilterGroup | None,
    obj: ObjectTypeDef,
    service: _Context,
    source_physical: str,
) -> tuple[FilterAtom | FilterGroup | None, list[_BindJoin]]:
    if node is None:
        return None, []
    if isinstance(node, FilterAtom):
        if _is_local_field(obj, node.field):
            return node, []
        resolved = _one_link_join(service, obj.id, node.field, source_physical)
        if resolved is None:
            raise AnalysisError("INVALID_PROPERTIES")
        if resolved.same_source:
            return node, []
        if node.op not in {"EQ", "IN"}:
            raise AnalysisError("OPERATOR_NOT_SUPPORTED")
        return None, [replace(_bind_from_resolved(resolved, node.field), filter_atom=node)]
    if node.kind in {"OR", "NOT"}:
        for arg in node.args:
            _, extra = _strip_bind_filters(arg, obj, service, source_physical)
            if extra:
                raise AnalysisError("OPERATOR_NOT_SUPPORTED")
        return node, []
    kept: list[FilterAtom | FilterGroup] = []
    binds: list[_BindJoin] = []
    for arg in node.args:
        part, extra = _strip_bind_filters(arg, obj, service, source_physical)
        binds.extend(extra)
        if part is not None:
            kept.append(part)
    if not kept:
        return None, binds
    if len(kept) == 1:
        return kept[0], binds
    return FilterGroup(kind="AND", args=tuple(kept)), binds


def _rewrite_bind_joins(
    service: _Context, query: SemanticQuery, obj: ObjectTypeDef, source_physical: str
) -> tuple[SemanticQuery, tuple[_BindJoin, ...]]:
    binds: list[_BindJoin] = []
    groups: list[GroupByItem] = []
    seen_keys: set[str] = set()
    for item in query.group_by:
        if _is_local_field(obj, item.id):
            groups.append(item)
            continue
        resolved = _one_link_join(service, obj.id, item.id, source_physical)
        if resolved is None:
            raise AnalysisError("INVALID_PROPERTIES")
        if resolved.same_source:
            groups.append(item)
            continue
        binds.append(_bind_from_resolved(resolved, item.id))
        key = resolved.link.identity.source
        if key not in seen_keys:
            groups.append(GroupByItem(id=key))
            seen_keys.add(key)
    filters, extra = _strip_bind_filters(query.filters, obj, service, source_physical)
    binds.extend(extra)
    if not binds:
        return query, ()
    if query.comparison or any(
        ref.aggregation == "AVG" for ref in query.metrics if ref.aggregation
    ):
        raise AnalysisError("OPERATOR_NOT_SUPPORTED")
    return query.model_copy(update={"group_by": tuple(groups), "filters": filters}), tuple(binds)


def _compile(service: _Context, query: SemanticQuery, tenant: str) -> _Plan:
    def _metric_table(metric_id: str) -> object:
        metric_def = _metric(service, metric_id)
        try:
            return _mapping(service, metric_def.id).physical.get("table")
        except AnalysisError:
            if metric_def.derived_from:
                return _mapping(service, metric_def.derived_from[0]).physical.get("table")
            raise

    tables = {_metric_table(ref.id) for ref in query.metrics}
    if len(tables) > 1:
        raise AnalysisError("OPERATOR_NOT_SUPPORTED")
    metric = _metric(service, query.metrics[0].id)
    if conflicting_equalities(query.filters):
        raise AnalysisError("CONFLICTING_FILTERS")
    aggregation = query.metrics[0].aggregation
    if aggregation is None:
        raise AnalysisError("AGGREGATION_REQUIRED")
    if aggregation not in {"SUM", "MIN", "MAX", "COUNT", "AVG"}:
        raise AnalysisError("OPERATOR_NOT_SUPPORTED")
    if metric.value_type not in {"DECIMAL", "INTEGER"} and aggregation != "COUNT":
        raise AnalysisError("OPERATOR_NOT_SUPPORTED")
    for item in query.group_by:
        if (
            item.time_grain == "MONTH"
            and metric.population is not None
            and _bare(item.id) == metric.population.year_property
        ):
            raise AnalysisError("TIME_GRAIN_UNSUPPORTED")
    try:
        metric_mapping = _mapping(service, metric.id)
    except AnalysisError:
        if not metric.derived_from:
            raise
        metric_mapping = _mapping(service, metric.derived_from[0])
    object_mapping = _mapping(service, metric.object_type)
    if object_mapping.physical.get("table") != metric_mapping.physical.get("table"):
        raise AnalysisError("LINK_ANALYSIS_UNSUPPORTED")
    if query.comparison:
        if query.comparison.metric != metric.id:
            raise AnalysisError("COMPARISON_METRIC_MISMATCH")
        if query.group_by or query.limit:
            raise AnalysisError("OPERATOR_NOT_SUPPORTED")
    if (
        metric_mapping.source_id != object_mapping.source_id
        or metric_mapping.provider != "postgres"
    ):
        raise AnalysisError("CROSS_SOURCE_SQL")
    table = require_ident(metric_mapping.physical.get("table"), field="table")
    tenant_col = require_ident(
        metric_mapping.physical.get("tenantColumn", "tenant_id"), field="tenantColumn"
    )
    identity_col = require_ident(
        metric_mapping.physical.get("identityColumn"), field="identityColumn"
    )
    projection = {**_projection(object_mapping), **_projection(metric_mapping)}
    obj = next(item for item in service.bundle.object_types if item.id == metric.object_type)
    if len(obj.identity_keys) != 1:
        raise AnalysisError("UNSUPPORTED_IDENTITY")
    if query.comparison and query.comparison.subject and query.comparison.subject.identity:
        if set(query.comparison.subject.identity) != set(obj.identity_keys):
            raise AnalysisError("INVALID_SUBJECT_PROPERTIES")
    value_col = (
        _derived_sql(service, metric, projection)
        if metric.derived_from
        else projection.get("__value__")
    )
    if value_col is None:
        raise AnalysisError("NO_MAPPING")
    types: dict[str, str] = {prop.id: prop.value_type for prop in obj.properties}
    for key in obj.identity_keys:
        types.setdefault(key, "STRING")
    query, bind_joins = _rewrite_bind_joins(service, query, obj, metric_mapping.source_id)
    join_tables: set[str] = set()
    used_links: dict[str, tuple[LinkDef, ObjectTypeDef, MappingDef]] = {}
    for field in _referenced_fields(query):
        if _is_local_field(obj, field):
            continue
        resolved = _one_link_join(service, obj.id, field, metric_mapping.source_id)
        if resolved is None:
            raise AnalysisError("INVALID_PROPERTIES")
        if not resolved.same_source:
            raise AnalysisError("CROSS_SOURCE_SQL")
        used_links[resolved.link.id] = (resolved.link, resolved.target, resolved.mapping)
    if (used_links or bind_joins) and metric.derived_from:
        raise AnalysisError("LINK_ANALYSIS_UNSUPPORTED")
    if used_links:
        fact = require_ident("fact", field="alias")
        from_sql = f"{table} AS {fact}"
        projection = {key: _qualify_simple(column, fact) for key, column in projection.items()}
        identity_col = _qualify_simple(identity_col, fact)
        value_col = _qualify_simple(value_col, fact)
        tenant_pred = f"{fact}.{tenant_col} = :tenant"
        for index, (link, target, target_mapping) in enumerate(used_links.values()):
            alias = require_ident(f"link_{index}", field="alias")
            target_table = require_ident(target_mapping.physical.get("table"), field="table")
            target_tenant = require_ident(
                target_mapping.physical.get("tenantColumn", "tenant_id"), field="tenantColumn"
            )
            target_projection = _projection(target_mapping)
            source_col = projection.get(link.identity.source)
            target_col = target_projection.get(link.identity.target)
            if source_col is None or target_col is None:
                raise AnalysisError("NO_PATH")
            from_sql += (
                f" LEFT JOIN {target_table} AS {alias} ON {alias}.{target_tenant} = :tenant"
                f" AND {alias}.{require_ident(target_col, field='column')} = {source_col}"
            )
            join_tables.add(target_table)
            target_types = {prop.id: prop.value_type for prop in target.properties}
            for key in target.identity_keys:
                target_types.setdefault(key, "STRING")
            for semantic, column in target_projection.items():
                qualified_col = f"{alias}.{column}"
                projection[f"{target.id}.{semantic}"] = qualified_col
                projection.setdefault(semantic, qualified_col)
            for semantic, value_type in target_types.items():
                types[f"{target.id}.{semantic}"] = value_type
                types.setdefault(semantic, value_type)
    else:
        from_sql = table
        tenant_pred = f"{tenant_col} = :tenant"

    def validate_filter(node: FilterAtom | FilterGroup | None) -> None:
        if isinstance(node, FilterGroup):
            for arg in node.args:
                validate_filter(arg)
        elif isinstance(node, FilterAtom):
            key = node.field if node.field in types else _bare(node.field)
            if key not in types:
                raise AnalysisError("INVALID_PROPERTIES")
            if types[key] != node.value.value_type:
                raise AnalysisError("FILTER_TYPE_MISMATCH")

    validate_filter(query.filters)
    params: dict[str, Any] = {"tenant": tenant}
    where = [tenant_pred]
    where.extend(_filter_sql(query.filters, projection, params))
    if query.comparison and query.comparison.subject and query.comparison.subject.filters:
        subject_keys = set(query.comparison.subject.filters)
        overlap = subject_keys & _filter_fields(query.filters)
        year = metric.population.year_property if metric.population else ""
        if overlap - {year}:
            raise AnalysisError("SUBJECT_FILTER_MUST_NOT_RESTRICT_POPULATION")
    groups, aliases = _group_sql(query, projection, types)
    select_groups = ", ".join(
        f'{sql} AS "{alias}"' for sql, alias in zip(groups, aliases, strict=True)
    )
    if aggregation == "AVG":
        agg = f"SUM({value_col}) AS total, COUNT({value_col}) AS n"
    elif aggregation == "COUNT":
        agg = f"COUNT({value_col}) AS value"
    else:
        agg = f"{aggregation}({value_col}) AS value"
    select_list = f"{select_groups}, {agg}" if select_groups else agg
    group_clause = f" GROUP BY {', '.join(groups)}" if groups else ""
    order_clause = _order_sql(query, aliases).replace("__AVG_COLUMN__", value_col)
    limit_clause = f" LIMIT {int(query.limit or 1001)}"
    sql = (
        f"SELECT {select_list} FROM {from_sql} WHERE {' AND '.join(where)}"
        f"{group_clause}{order_clause}{limit_clause}"
    )
    _assert_sql(sql, {table, *join_tables})
    unit_col = None
    if metric.population is not None:
        unit_col = projection.get(metric.population.unit_property)
    count_sql = (
        f"SELECT COUNT(*) AS population, COUNT({value_col}) AS observed, "
        f"COUNT(*) - COUNT({value_col}) AS missing"
        + (
            f", COUNT(DISTINCT ({unit_col}, {projection[metric.population.year_property]})) "
            f"FILTER (WHERE {unit_col} IS NOT NULL) AS units"
            if unit_col and metric.population
            else ""
        )
        + f" FROM {from_sql} WHERE {' AND '.join(where)}"
    )
    extra_sql = ""
    if unit_col and unit_col != identity_col:
        extra_sql += f", {unit_col} AS unit_id"
    for prop in _display_name_fields(obj):
        label_col = projection.get(prop.id)
        if label_col and label_col not in {identity_col, value_col, unit_col}:
            extra_sql += f', {label_col} AS "{prop.id}"'
    evidence_sql = (
        f"SELECT {identity_col} AS identity, {value_col} AS value{extra_sql} FROM {from_sql} "
        f"WHERE {' AND '.join(where)} ORDER BY {identity_col} LIMIT {int(query.evidence_limit)}"
    )
    return _Plan(
        aggregation=aggregation,
        comparison=query.comparison,
        count_sql=count_sql,
        evidence_sql=evidence_sql,
        identity_col=identity_col,
        metric=metric,
        metric_mapping=metric_mapping,
        params=params,
        projection=projection,
        query=query,
        sql=sql,
        table=table,
        from_sql=from_sql,
        tenant_col=tenant_col,
        unit_col=unit_col,
        value_col=value_col,
        where=where,
        bind_joins=bind_joins,
    )


def _filter_fields(node: FilterAtom | FilterGroup | None) -> set[str]:
    if isinstance(node, FilterAtom):
        return {_bare(node.field)}
    if isinstance(node, FilterGroup):
        names: set[str] = set()
        for arg in node.args:
            names |= _filter_fields(arg)
        return names
    return set()


def _filter_sql(
    node: FilterAtom | FilterGroup | None, projection: dict[str, str], params: dict[str, Any]
) -> list[str]:
    if node is None:
        return []
    if isinstance(node, FilterGroup):
        parts: list[str] = []
        for arg in node.args:
            inner = _filter_sql(arg, projection, params)
            if not inner:
                continue
            parts.append(inner[0] if len(inner) == 1 else "(" + " AND ".join(inner) + ")")
        if not parts:
            return []
        if node.kind == "NOT":
            return [f"NOT ({parts[0]})"]
        if node.kind == "OR":
            return ["(" + " OR ".join(parts) + ")"]
        return ["(" + " AND ".join(parts) + ")"]
    column = projection.get(node.field) or projection.get(_bare(node.field))
    if column is None:
        raise AnalysisError("INVALID_PROPERTIES")
    key = f"p{len(params)}"
    if node.op == "IN":
        values = node.value.value
        assert isinstance(values, tuple)
        keys = []
        for index, item in enumerate(values):
            item_key = f"{key}_{index}"
            params[item_key] = item
            keys.append(f":{item_key}")
        return [f"{column} IN ({', '.join(keys)})"]
    if node.op == "BETWEEN":
        bounds = node.value.value
        if not isinstance(bounds, tuple) or len(bounds) != 2:
            raise AnalysisError("INVALID_PROPERTIES")
        params[f"{key}_a"] = bounds[0]
        params[f"{key}_b"] = bounds[1]
        return [f"{column} BETWEEN :{key}_a AND :{key}_b"]
    params[key] = node.value.value
    return [f"{column} {_OP_SQL[node.op]} :{key}"]


def _group_sql(
    query: SemanticQuery, projection: dict[str, str], types: dict[str, str]
) -> tuple[list[str], list[str]]:
    sqls: list[str] = []
    aliases: list[str] = []
    for item in query.group_by:
        name = _bare(item.id)
        column = projection.get(item.id) or projection.get(name)
        if column is None:
            raise AnalysisError("INVALID_PROPERTIES")
        if item.time_grain and types.get(name) in {"DATE", "DATETIME"}:
            sqls.append(f"date_trunc('{item.time_grain.lower()}', {column})")
        elif item.time_grain == "MONTH":
            raise AnalysisError("TIME_GRAIN_UNSUPPORTED")
        else:
            sqls.append(column)
        aliases.append(name)
    return sqls, aliases


def _order_sql(query: SemanticQuery, group_aliases: list[str]) -> str:
    parts = []
    for item in query.order_by:
        name = _bare(item.field)
        if name in group_aliases:
            expr = f'"{name}"'
        elif item.field in {query.metrics[0].id, "value", "total"}:
            expr = (
                "value"
                if query.metrics[0].aggregation != "AVG"
                else "(CAST(SUM(__AVG_COLUMN__) AS NUMERIC) / NULLIF(COUNT(__AVG_COLUMN__), 0))"
            )
        else:
            raise AnalysisError("INVALID_PROPERTIES")
        parts.append(f"{expr} {'DESC' if item.direction == 'DESC' else 'ASC'}")
    ordered = {_bare(item.field) for item in query.order_by}
    parts.extend(f'"{alias}" ASC' for alias in group_aliases if alias not in ordered)
    return " ORDER BY " + ", ".join(parts) if parts else ""


def _assert_sql(sql: str, tables: set[str]) -> None:
    sanitized = re.sub(r":[A-Za-z_][A-Za-z0-9_]*", "NULL", sql)
    parsed = sqlglot.parse_one(sanitized, dialect="postgres")
    found = {table.name for table in parsed.find_all(exp.Table)}
    if not found <= tables:
        raise AnalysisError("RAW_SQL")
    for func in parsed.find_all(exp.Func):
        if func.sql_name().lower() not in _ALLOWED_FUNCS:
            raise AnalysisError("UDF")
    if parsed.find(exp.Window):
        raise AnalysisError("CUSTOM_WINDOW_FRAME")
    if parsed.find(exp.Delete) or parsed.find(exp.Insert) or parsed.find(exp.Update):
        raise AnalysisError("RAW_SQL")


def _runner(service: _Context) -> Any:
    run = getattr(service.provider, "execute_select", None)
    if callable(run):
        return run
    raise AnalysisError("CROSS_SOURCE_SQL")


def _distinct_years(service: _Context, metric: MetricDef, tenant: str) -> list[int]:
    mapping = _mapping(service, metric.object_type)
    projection = _projection(mapping)
    assert metric.population is not None
    column = projection.get(metric.population.year_property)
    if column is None:
        return []
    table = require_ident(mapping.physical.get("table"), field="table")
    tenant_col = require_ident(
        mapping.physical.get("tenantColumn", "tenant_id"), field="tenantColumn"
    )
    sql = text(
        f"SELECT DISTINCT {column} AS year FROM {table} WHERE {tenant_col} = :tenant "
        f"AND {column} IS NOT NULL ORDER BY year LIMIT 4"
    )
    try:
        rows = _runner(service)(mapping.source_id, tenant, sql, {"tenant": tenant})
    except (SQLAlchemyError, KeyError) as exc:
        raise AnalysisError("PROVIDER_UNAVAILABLE") from exc
    return [int(row["year"]) for row in rows if row.get("year") is not None]


def _run(
    service: _Context, compiled: _Plan, tenant: str
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any] | None, list[dict[str, Any]], bool]:
    run = _runner(service)
    source = compiled.metric_mapping.source_id
    try:
        count_row = run(source, tenant, text(compiled.count_sql), compiled.params)[0]
        evidence_rows = run(source, tenant, text(compiled.evidence_sql), compiled.params)
        grouped = run(source, tenant, text(compiled.sql), compiled.params)
    except (SQLAlchemyError, KeyError, IndexError) as exc:
        raise AnalysisError("PROVIDER_UNAVAILABLE") from exc
    if len(grouped) > 1000:
        raise AnalysisError("RESULT_TOO_LARGE_REFINE_QUERY")
    for row in [*grouped, *evidence_rows]:
        for key in ("value", "total"):
            value = row.get(key)
            if isinstance(value, float):
                raise AnalysisError("FLOAT_ARITHMETIC")
            if isinstance(value, Decimal) and not value.is_finite():
                raise AnalysisError("NON_FINITE_VALUE")
    population = int(count_row["population"] or 0)
    observed = int(count_row["observed"] or 0)
    missing = int(count_row["missing"] or 0)
    if (
        compiled.unit_col is not None
        and population
        and int(count_row.get("units") or 0) != population
    ):
        raise AnalysisError("DUPLICATE_OR_MISSING_STATISTICAL_UNIT")
    reason = None
    if population == 0:
        reason = "EMPTY_POPULATION"
    elif missing and compiled.query.missing_policy != "exclude":
        reason = "MISSING_VALUES_REQUIRE_EXPLICIT_EXCLUSION"
    elif observed == 0:
        reason = "NO_OBSERVED_VALUES"
    truncated = population > len(evidence_rows)
    rows: list[dict[str, Any]] = []
    if reason is None:
        with localcontext() as ctx:
            ctx.prec = 28
            for row in grouped:
                grain = {key: row[key] for key in row if key not in {"value", "total", "n"}}
                if compiled.aggregation == "AVG":
                    total, count = row["total"], int(row["n"] or 0)
                    value = (
                        str(Decimal(str(total)) / count) if total is not None and count else None
                    )
                else:
                    raw = row.get("value")
                    value = None if raw is None else str(raw)
                rows.append({"grain": grain, "value": value})
    comparison = _comparison(compiled, tenant, run, reason)
    counts = {
        "population": population,
        "observed": observed,
        "missing": missing,
        "reason": reason,
    }
    if reason is not None:
        rows = []
    return rows, counts, comparison, evidence_rows, truncated


def _comparison(
    compiled: _Plan, tenant: str, run: Any, reason: str | None
) -> dict[str, Any] | None:
    comparison = compiled.comparison
    if comparison is None:
        return None
    if comparison.subject is None:
        raise AnalysisError("COMPARISON_SUBJECT_REQUIRED")
    params = dict(compiled.params)
    subject_where = list(compiled.where)
    identity = comparison.subject.identity or comparison.subject.filters or {}
    if not identity:
        raise AnalysisError("INVALID_SUBJECT_PROPERTIES")
    for key, value in identity.items():
        column = compiled.projection.get(_bare(key))
        if column is None:
            if comparison.subject.identity is not None:
                column = compiled.identity_col
            else:
                raise AnalysisError("INVALID_SUBJECT_PROPERTIES")
        token = f"s_{_bare(key)}"
        subject_where.append(f"{column} = :{token}")
        params[token] = value
    source = compiled.metric_mapping.source_id
    subject_rows = run(
        source,
        tenant,
        text(
            f"SELECT SUM({compiled.value_col}) AS value, "
            f"COUNT({compiled.value_col}) AS n, COUNT(*) AS members "
            f"FROM {compiled.from_sql} WHERE {' AND '.join(subject_where)}"
        ),
        params,
    )
    pop_rows = run(
        source,
        tenant,
        text(
            f"SELECT SUM({compiled.value_col}) AS total, COUNT({compiled.value_col}) AS observed "
            f"FROM {compiled.from_sql} WHERE {' AND '.join(compiled.where)}"
        ),
        compiled.params,
    )
    subject_count = int(subject_rows[0]["members"] or 0)
    if subject_count == 0:
        raise AnalysisError("COMPARISON_SUBJECT_OUTSIDE_POPULATION")
    if subject_count != 1:
        raise AnalysisError("AMBIGUOUS_COMPARISON_SUBJECT")
    identity_rows = run(
        source,
        tenant,
        text(
            f"SELECT {compiled.identity_col} AS identity FROM {compiled.from_sql} "
            f"WHERE {' AND '.join(subject_where)} LIMIT 2"
        ),
        params,
    )
    subject_identity = str(identity_rows[0]["identity"]) if identity_rows else None
    exclude_where = [*compiled.where, f"{compiled.identity_col} <> :excluded_identity"]
    params["excluded_identity"] = subject_identity
    if subject_rows[0]["value"] is None:
        reason = "SUBJECT_VALUE_MISSING"
    if reason:
        return {
            "operation": _CMP_BACK[comparison.op],
            "value": None,
            "reason": reason,
            "subjectIdentity": subject_identity,
        }
    if subject_rows[0]["value"] is None:
        return {
            "operation": _CMP_BACK[comparison.op],
            "value": None,
            "reason": "SUBJECT_VALUE_MISSING",
            "subjectIdentity": subject_identity,
        }
    with localcontext() as ctx:
        ctx.prec = 28
        subject_d = Decimal(str(subject_rows[0]["value"]))
        total = (
            Decimal(str(pop_rows[0]["total"])) if pop_rows[0]["total"] is not None else Decimal(0)
        )
        observed = int(pop_rows[0]["observed"] or 0)
        mean = total / observed if observed else None
        if comparison.op == "SHARE_OF_TOTAL":
            neg = run(
                source,
                tenant,
                text(
                    f"SELECT COUNT(*) FILTER (WHERE {compiled.value_col} < 0) AS n "
                    f"FROM {compiled.from_sql} WHERE {' AND '.join(compiled.where)}"
                ),
                compiled.params,
            )
            if int(neg[0]["n"] or 0):
                return {
                    "operation": "shareOfTotal",
                    "value": None,
                    "reason": "NEGATIVE_VALUES_NOT_A_SHARE",
                    "subjectIdentity": subject_identity,
                }
            if total == 0:
                return {
                    "operation": "shareOfTotal",
                    "value": None,
                    "reason": "ZERO_DENOMINATOR",
                    "subjectIdentity": subject_identity,
                }
            return {
                "operation": "shareOfTotal",
                "value": str(subject_d / total * 100),
                "numerator": str(subject_d),
                "denominator": str(total),
                "formula": "subject / population sum * 100",
                "reason": None,
                "subjectIdentity": subject_identity,
            }
        if comparison.op == "RELATIVE_TO_MEAN":
            if mean is None or mean <= 0:
                return {
                    "operation": "percentAboveMean",
                    "value": None,
                    "reason": "NON_POSITIVE_MEAN",
                    "subjectIdentity": subject_identity,
                }
            return {
                "operation": "percentAboveMean",
                "value": str((subject_d - mean) / mean * 100),
                "numerator": str(subject_d - mean),
                "denominator": str(mean),
                "formula": "(subject - population mean) / population mean * 100",
                "reason": None,
                "subjectIdentity": subject_identity,
            }
        params["subject_value"] = subject_d
        op = "<" if comparison.direction == "higher" else ">"
        peer_rows = run(
            source,
            tenant,
            text(
                f"SELECT COUNT({compiled.value_col}) "
                f"FILTER (WHERE {compiled.value_col} {op} :subject_value) "
                f"AS wins, COUNT({compiled.value_col}) AS peers FROM {compiled.from_sql} "
                f"WHERE {' AND '.join(exclude_where)}"
            ),
            params,
        )
        wins = Decimal(str(peer_rows[0]["wins"] or 0))
        peers = Decimal(str(peer_rows[0]["peers"] or 0))
        if peers == 0:
            return {
                "operation": "outperforms",
                "value": None,
                "reason": "ZERO_DENOMINATOR",
                "subjectIdentity": subject_identity,
            }
        return {
            "operation": "outperforms",
            "value": str(wins / peers * 100),
            "numerator": str(wins),
            "denominator": str(peers),
            "formula": (
                "strictly outperformed peers / all observed peers * 100 "
                f"({comparison.direction}; ties count in denominator)"
            ),
            "reason": None,
            "subjectIdentity": subject_identity,
        }


_LABEL_MARKERS = ("name", "title", "label", "名称", "姓名")


def _display_name_fields(obj: ObjectTypeDef) -> tuple[EmbeddedProperty, ...]:
    strings = [
        prop
        for prop in obj.properties
        if prop.value_type == "STRING" and prop.id not in obj.identity_keys
    ]
    named = [
        prop
        for prop in strings
        if any(marker in f"{prop.id} {prop.label or ''}".casefold() for marker in _LABEL_MARKERS)
    ]
    return tuple((named or strings)[:2])


def _object_type(bundle: CompiledBundle, object_id: str) -> ObjectTypeDef | None:
    return next((item for item in bundle.object_types if item.id == object_id), None)


def _same_table_labels(
    service: _Context,
    obj: ObjectTypeDef,
    mapping: MappingDef,
    tenant: str,
    field_ids: dict[str, set[str]],
) -> dict[tuple[str, str], str]:
    found: dict[tuple[str, str], str] = {}
    labels = _display_name_fields(obj)
    if not labels:
        return found
    projection = _projection(mapping)
    table = require_ident(mapping.physical.get("table"), field="table")
    tenant_col = require_ident(
        mapping.physical.get("tenantColumn", "tenant_id"), field="tenantColumn"
    )
    for field, ids in field_ids.items():
        key_col = projection.get(field)
        values = {str(item) for item in ids if item not in {"", "None"}}
        if not key_col or not values:
            continue
        select_parts = [f"{key_col} AS ident"]
        aliases: list[str] = []
        for prop in labels:
            column = projection.get(prop.id)
            if not column or column == key_col:
                continue
            select_parts.append(f'{column} AS "{prop.id}"')
            aliases.append(prop.id)
        if not aliases:
            continue
        params: dict[str, Any] = {"tenant": tenant}
        keys: list[str] = []
        for index, ident in enumerate(sorted(values)[:50]):
            token = f"id_{index}"
            params[token] = ident
            keys.append(f":{token}")
        sql = text(
            f"SELECT {', '.join(select_parts)} FROM {table} "
            f"WHERE {tenant_col} = :tenant AND {key_col} IN ({', '.join(keys)})"
        )
        try:
            rows = _runner(service)(mapping.source_id, tenant, sql, params)
        except (SQLAlchemyError, KeyError, AnalysisError):
            continue
        for row in rows:
            ident = str(row.get("ident") or "")
            name = " ".join(
                str(row[alias]) for alias in aliases if row.get(alias) not in {None, ""}
            ).strip()
            if ident and name:
                found[(field, ident)] = name
    return found


def _link_labels(
    service: _Context, source: ObjectTypeDef, tenant: str, field_ids: dict[str, set[str]]
) -> dict[tuple[str, str], str]:
    found: dict[tuple[str, str], str] = {}
    try:
        source_mapping = _mapping(service, source.id)
    except AnalysisError:
        return found
    for link in service.bundle.links:
        if link.source != source.id or link.cardinality != "ONE":
            continue
        ids = {
            str(item)
            for item in field_ids.get(link.identity.source, set())
            if item not in {"", "None"}
        }
        if not ids:
            continue
        target = _object_type(service.bundle, link.target)
        if target is None:
            continue
        labels = _display_name_fields(target)
        if not labels:
            continue
        try:
            target_mapping = _mapping(service, target.id)
        except AnalysisError:
            continue
        if target_mapping.source_id != source_mapping.source_id:
            continue
        projection = _projection(target_mapping)
        identity_col = require_ident(
            target_mapping.physical.get("identityColumn") or projection.get(link.identity.target),
            field="identityColumn",
        )
        tenant_col = require_ident(
            target_mapping.physical.get("tenantColumn", "tenant_id"), field="tenantColumn"
        )
        table = require_ident(target_mapping.physical.get("table"), field="table")
        select_parts = [f"{identity_col} AS identity"]
        aliases: list[str] = []
        for prop in labels:
            column = projection.get(prop.id)
            if not column:
                continue
            select_parts.append(f'{column} AS "{prop.id}"')
            aliases.append(prop.id)
        if not aliases:
            continue
        params: dict[str, Any] = {"tenant": tenant}
        keys: list[str] = []
        for index, ident in enumerate(sorted(ids)[:50]):
            token = f"id_{index}"
            params[token] = ident
            keys.append(f":{token}")
        sql = text(
            f"SELECT {', '.join(select_parts)} FROM {table} "
            f"WHERE {tenant_col} = :tenant AND {identity_col} IN ({', '.join(keys)})"
        )
        try:
            rows = _runner(service)(target_mapping.source_id, tenant, sql, params)
        except (SQLAlchemyError, KeyError, AnalysisError):
            continue
        for row in rows:
            ident = str(row.get("identity") or "")
            name = " ".join(
                str(row[alias]) for alias in aliases if row.get(alias) not in {None, ""}
            ).strip()
            if ident and name:
                found[(link.identity.source, ident)] = name
    return found


def _decorate_labels(
    service: _Context,
    compiled: _Plan,
    tenant: str,
    values: tuple[dict[str, Any], ...],
    evidence_rows: list[dict[str, Any]],
) -> tuple[tuple[dict[str, Any], ...], EvidenceTable]:
    obj = _object_type(service.bundle, compiled.metric.object_type)
    field_ids: dict[str, set[str]] = {}
    for row in values:
        for key, item in (row.get("grain") or {}).items():
            field_ids.setdefault(str(key), set()).add(str(item))
    for row in evidence_rows:
        if row.get("unit_id") is not None:
            unit = (
                compiled.metric.population.unit_property if compiled.metric.population else "unit"
            )
            field_ids.setdefault(unit, set()).add(str(row["unit_id"]))
        for key, item in row.items():
            if key in {"identity", "value"} or item is None:
                continue
            field_ids.setdefault(str(key), set()).add(str(item))
    resolved: dict[tuple[str, str], str] = {}
    if obj is not None:
        try:
            resolved.update(
                _same_table_labels(service, obj, _mapping(service, obj.id), tenant, field_ids)
            )
        except AnalysisError:
            pass
        resolved.update(_link_labels(service, obj, tenant, field_ids))
    decorated = []
    for row in values:
        grain = dict(row.get("grain") or {})
        labels = {}
        for key, item in grain.items():
            name = resolved.get((str(key), str(item)))
            if name:
                labels[str(key)] = name
        decorated.append({**row, "labels": labels} if labels else row)
    columns = [
        EvidenceColumn(id="identity", label="对象"),
        EvidenceColumn(id="value", label="引擎值"),
    ]
    extra_ids = [
        key
        for key in (evidence_rows[0].keys() if evidence_rows else [])
        if key not in {"identity", "value"}
    ]
    label_title = (
        next((prop.label or prop.id for prop in _display_name_fields(obj)), "名称")
        if obj
        else "名称"
    )
    unit_field = compiled.metric.population.unit_property if compiled.metric.population else None
    if any(
        resolved.get((unit_field or "", str(row.get("unit_id") or ""))) for row in evidence_rows
    ):
        columns.insert(1, EvidenceColumn(id="label", label=label_title))
        extra_ids = [item for item in extra_ids if item != "unit_id"]
        include_resolved = True
    else:
        include_resolved = False
        for key in extra_ids:
            columns.insert(-1, EvidenceColumn(id=key, label=key))
    built: list[tuple[str, ...]] = []
    for row in evidence_rows:
        cells = [str(row.get("identity") or "—")]
        if include_resolved:
            cells.append(
                resolved.get((unit_field or "", str(row.get("unit_id") or "")))
                or str(row.get("unit_id") or "—")
            )
        else:
            cells.extend("—" if row.get(key) is None else str(row[key]) for key in extra_ids)
        cells.append("—" if row.get("value") is None else str(row["value"]))
        built.append(tuple(cells))
    table = EvidenceTable(
        columns=tuple(columns),
        rows=tuple(built),
        truncated=False,
        row_count=len(built),
    )
    return tuple(decorated), table


def _bind_select(service: _Context) -> Any:
    provider = service.bind_provider or service.provider
    run = getattr(provider, "execute_select", None)
    if not callable(run):
        raise AnalysisError("CROSS_SOURCE_SQL")
    return run


def _materialize_bind_filters(
    service: _Context, query: SemanticQuery, tenant: str
) -> SemanticQuery | None:
    """Resolve remote EQ/IN filters to local keys. None means empty match."""
    metric = _metric(service, query.metrics[0].id)
    obj = next(item for item in service.bundle.object_types if item.id == metric.object_type)
    try:
        source_id = _mapping(service, metric.id).source_id
    except AnalysisError:
        source_id = _mapping(service, metric.object_type).source_id
    _rewritten, binds = _rewrite_bind_joins(service, query, obj, source_id)
    extra: list[FilterAtom] = []
    for bind in binds:
        if bind.filter_atom is None:
            continue
        keys = _lookup_bind_identities(service, bind, tenant)
        if not keys:
            return None
        extra.append(
            FilterAtom(
                field=bind.local_key,
                op="IN",
                value=TypedValue(value_type="STRING", value=tuple(keys)),
            )
        )
    if not extra:
        return query
    filters = query.filters
    for atom in extra:
        filters = atom if filters is None else FilterGroup(kind="AND", args=(filters, atom))
    return query.model_copy(update={"filters": filters})


def _lookup_bind_identities(service: _Context, bind: _BindJoin, tenant: str) -> list[str]:
    assert bind.filter_atom is not None
    projection = _projection(bind.mapping)
    column = projection.get(bind.remote_field)
    if column is None:
        raise AnalysisError("NO_MAPPING")
    identity = require_ident(bind.mapping.physical.get("identityColumn"), field="identityColumn")
    tenant_col = require_ident(
        bind.mapping.physical.get("tenantColumn", "tenant_id"), field="tenantColumn"
    )
    table = require_ident(bind.mapping.physical.get("table"), field="table")
    params: dict[str, Any] = {"tenant": tenant}
    atom = bind.filter_atom
    if atom.op == "EQ":
        params["v"] = atom.value.value
        predicate = f"{column} = :v"
    else:
        values = atom.value.value
        assert isinstance(values, tuple)
        keys = []
        for index, item in enumerate(values):
            token = f"v_{index}"
            params[token] = item
            keys.append(f":{token}")
        predicate = f"{column} IN ({', '.join(keys)})"
    sql = text(
        f"SELECT {identity} AS identity FROM {table} "
        f"WHERE {tenant_col} = :tenant AND {predicate} LIMIT {_BIND_KEY_LIMIT + 1}"
    )
    try:
        rows = _bind_select(service)(bind.mapping.source_id, tenant, sql, params)
    except (SQLAlchemyError, KeyError) as exc:
        raise AnalysisError("PROVIDER_UNAVAILABLE") from exc
    if len(rows) > _BIND_KEY_LIMIT:
        raise AnalysisError("BUDGET_EXCEEDED")
    return [str(row["identity"]) for row in rows]


def _lookup_bind_properties(
    service: _Context, bind: _BindJoin, keys: list[str], tenant: str
) -> dict[str, str | None]:
    found: dict[str, str | None] = {key: None for key in keys}
    if not keys:
        return found
    projection = _projection(bind.mapping)
    column = projection.get(bind.remote_field)
    identity = require_ident(bind.mapping.physical.get("identityColumn"), field="identityColumn")
    tenant_col = require_ident(
        bind.mapping.physical.get("tenantColumn", "tenant_id"), field="tenantColumn"
    )
    table = require_ident(bind.mapping.physical.get("table"), field="table")
    if column is None:
        raise AnalysisError("NO_MAPPING")
    for start in range(0, len(keys), _BIND_BATCH):
        chunk = keys[start : start + _BIND_BATCH]
        params: dict[str, Any] = {"tenant": tenant}
        tokens = []
        for index, key in enumerate(chunk):
            token = f"id_{index}"
            params[token] = key
            tokens.append(f":{token}")
        sql = text(
            f'SELECT {identity} AS identity, {column} AS "value" FROM {table} '
            f"WHERE {tenant_col} = :tenant AND {identity} IN ({', '.join(tokens)})"
        )
        try:
            rows = _bind_select(service)(bind.mapping.source_id, tenant, sql, params)
        except (SQLAlchemyError, KeyError) as exc:
            raise AnalysisError("PROVIDER_UNAVAILABLE") from exc
        for row in rows:
            ident = str(row.get("identity") or "")
            raw = row.get("value")
            found[ident] = None if raw in {None, ""} else str(raw)
    return found


def _apply_bind_groups(
    compiled: _Plan, values: tuple[dict[str, Any], ...], labels: dict[str, str | None]
) -> tuple[dict[str, Any], ...]:
    group_binds = [item for item in compiled.bind_joins if item.filter_atom is None]
    if not group_binds:
        return values
    buckets: dict[tuple[tuple[str, Any], ...], list[dict[str, Any]]] = {}
    for row in values:
        grain = dict(row.get("grain") or {})
        for bind in group_binds:
            key = grain.pop(bind.local_key, None)
            grain[_bare(bind.query_field)] = labels.get(str(key)) if key not in {None, ""} else None
        bucket = tuple(sorted(grain.items()))
        buckets.setdefault(bucket, []).append({**row, "grain": grain})
    merged: list[dict[str, Any]] = []
    for rows in buckets.values():
        nums = [Decimal(str(item["value"])) for item in rows if item.get("value") is not None]
        aggregation = compiled.aggregation
        if not nums:
            value = None
        elif aggregation in {"SUM", "COUNT"}:
            value = sum(nums, Decimal(0))
        elif aggregation == "MIN":
            value = min(nums)
        elif aggregation == "MAX":
            value = max(nums)
        else:
            raise AnalysisError("OPERATOR_NOT_SUPPORTED")
        merged.append(
            {
                **rows[0],
                "value": None if value is None else format(value, "f"),
            }
        )
    return tuple(merged)


def _empty_result(plan: PlanRef, digest: str) -> QueryResult:
    return QueryResult(
        result_id=uuid.uuid4().hex,
        plan_id=plan.plan_id,
        release_digest=digest,
        values=(),
        scope={
            "populationCount": 0,
            "observedCount": 0,
            "missingCount": 0,
            "complete": True,
            "reason": "EMPTY_POPULATION",
        },
        mapping_fields=(),
        evidence=EvidenceTable(columns=(), rows=()),
    )


def _execute_one(service: _Context, plan: PlanRef, tenant: str) -> QueryResult:
    query = _materialize_bind_filters(service, plan.query, tenant)
    if query is None:
        return _empty_result(plan, service.bundle.digest)
    compiled = _compile(service, query, tenant)
    rows, counts, comparison, evidence_rows, truncated = _run(service, compiled, tenant)
    values = tuple(
        {
            "metric": compiled.metric.id,
            "grain": row.get("grain") or {},
            "value": row["value"],
            "unit": "count" if compiled.aggregation == "COUNT" else compiled.metric.unit,
            "valueType": "INTEGER"
            if compiled.aggregation == "COUNT"
            else compiled.metric.value_type,
            "aggregation": compiled.aggregation,
        }
        for row in rows
    )
    group_binds = [item for item in compiled.bind_joins if item.filter_atom is None]
    if group_binds:
        keys: list[str] = []
        for row in values:
            for bind in group_binds:
                ident = (row.get("grain") or {}).get(bind.local_key)
                if ident not in {None, ""}:
                    keys.append(str(ident))
        labels: dict[str, str | None] = {}
        for bind in group_binds:
            labels.update(_lookup_bind_properties(service, bind, sorted(set(keys)), tenant))
        values = _apply_bind_groups(compiled, values, labels)
    values, evidence = _decorate_labels(service, compiled, tenant, values, evidence_rows)
    evidence = evidence.model_copy(
        update={"truncated": truncated, "row_count": counts["population"]}
    )
    used_mappings = {
        mapping.id: mapping
        for mapping in [
            compiled.metric_mapping,
            _mapping(service, compiled.metric.object_type),
            *(_mapping(service, dependency) for dependency in compiled.metric.derived_from),
        ]
    }
    return QueryResult(
        result_id=uuid.uuid4().hex,
        plan_id=plan.plan_id,
        release_digest=service.bundle.digest,
        values=values,
        scope={
            "populationCount": counts["population"],
            "observedCount": counts["observed"],
            "missingCount": counts["missing"],
            "denominator": None if comparison is None else comparison.get("denominator"),
            "numerator": None if comparison is None else comparison.get("numerator"),
            "comparison": comparison,
            "reason": counts.get("reason"),
            "subjectIdentity": None if comparison is None else comparison.get("subjectIdentity"),
            "complete": True,
        },
        mapping_fields=tuple(
            {
                "mappingId": mapping.id,
                "sourceId": mapping.source_id,
                "table": mapping.physical["table"],
                "columns": sorted(
                    set(_projection(mapping).values())
                    | {compiled.tenant_col, compiled.identity_col}
                ),
            }
            for mapping in used_mappings.values()
        ),
        evidence=evidence,
        source_activities=(
            {
                "activityId": uuid.uuid4().hex,
                "mappingId": compiled.metric_mapping.id,
                "sourceId": compiled.metric_mapping.source_id,
                "queryDigest": hashlib.sha256(compiled.sql.encode()).hexdigest(),
            },
        ),
    )


def _digest(service: _Context, query: SemanticQuery, tenant: str) -> str:
    # Bind values, scope and immutable definitions, not merely the SQL shape.
    payload = [service.bundle.digest, tenant, query.model_dump(mode="json", by_alias=True)]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def prepare_analysis(
    bundle: CompiledBundle, query: SemanticQuery, tenant: str, provider: Any
) -> str:
    context = _Context(bundle, provider)
    if not query.metrics:
        raise AnalysisError("METRIC_REQUIRED")
    if len({(ref.id, ref.aggregation) for ref in query.metrics}) != len(query.metrics):
        raise AnalysisError("DUPLICATE_METRIC_SELECTION")
    sources = set()
    for ref in query.metrics:
        single = query.model_copy(update={"metrics": (ref,)})
        compiled = _compile(context, single, tenant)
        sources.add((compiled.metric_mapping.source_id, compiled.table))
    if len(sources) != 1:
        raise AnalysisError("CROSS_SOURCE_SQL")
    if len(query.metrics) > 1 and (query.order_by or query.limit or query.comparison):
        raise AnalysisError("MULTI_METRIC_ORDER_COMPARISON_UNSUPPORTED")
    return _digest(context, query, tenant)


def execute_analysis(
    bundle: CompiledBundle,
    plan: PlanRef,
    tenant: str,
    provider: Any,
    bind_provider: Any | None = None,
) -> QueryResult:
    expected = prepare_analysis(bundle, plan.query, tenant, provider)
    if plan.release_digest != bundle.digest or expected != plan.compiled_digest:
        raise AnalysisError("PLAN_INVALID")
    context = _Context(bundle, provider, bind_provider or provider)
    try:
        results = [
            _execute_one(
                context,
                plan.model_copy(
                    update={"query": plan.query.model_copy(update={"metrics": (ref,)})}
                ),
                tenant,
            )
            for ref in plan.query.metrics
        ]
    except (SQLAlchemyError, KeyError, IndexError) as exc:
        raise AnalysisError("PROVIDER_UNAVAILABLE") from exc
    first = results[0]
    scopes = {ref.id: result.scope for ref, result in zip(plan.query.metrics, results, strict=True)}
    incomplete = any(scope.get("reason") for scope in scopes.values())
    return first.model_copy(
        update={
            "values": ()
            if incomplete
            else tuple(value for result in results for value in result.values),
            "scope": {
                **first.scope,
                "metrics": scopes,
                "consistency": "SOURCE_REPEATABLE_READ",
                "reason": first.scope.get("reason")
                or ("INCOMPLETE_METRIC_SET" if incomplete else None),
            },
            "mapping_fields": tuple(field for result in results for field in result.mapping_fields),
            "source_activities": tuple(a for result in results for a in result.source_activities),
            "evidence": EvidenceTable(
                columns=(EvidenceColumn(id="metric", label="指标"), *first.evidence.columns),
                rows=tuple(
                    (ref.id, *row)
                    for ref, result in zip(plan.query.metrics, results, strict=True)
                    for row in result.evidence.rows
                ),
                truncated=any(result.evidence.truncated for result in results),
                row_count=sum(result.evidence.row_count or 0 for result in results),
            )
            if len(results) > 1
            else first.evidence,
        }
    )


def analysis_years(bundle: CompiledBundle, metric_id: str, tenant: str, provider: Any) -> list[int]:
    context = _Context(bundle, provider)
    return _distinct_years(context, _metric(context, metric_id), tenant)


def analysis_source(
    bundle: CompiledBundle, query: SemanticQuery, tenant: str, provider: Any
) -> str:
    prepare_analysis(bundle, query, tenant, provider)
    return _compile(_Context(bundle, provider), query, tenant).metric_mapping.source_id


def analysis_subjects(
    bundle: CompiledBundle, query: SemanticQuery, tenant: str, provider: Any
) -> list[tuple[str, str, str]]:
    compiled = _compile(_Context(bundle, provider), query, tenant)
    obj = next(item for item in bundle.object_types if item.id == compiled.metric.object_type)
    params = dict(compiled.params)
    where = list(compiled.where)
    subject = query.comparison.subject if query.comparison else None
    if subject:
        for key, value in (subject.identity or subject.filters or {}).items():
            col = compiled.projection.get(_bare(key))
            if col is None:
                raise AnalysisError("INVALID_SUBJECT_PROPERTIES")
            token = "subject_" + _bare(key)
            where.append(f"{col} = :{token}")
            params[token] = value
    label_fields = [
        (prop.label or prop.id, compiled.projection[prop.id])
        for prop in obj.properties
        if prop.value_type == "STRING" and prop.id in compiled.projection
    ][:3]
    projection = ", ".join(
        f'{column} AS "label{index}"' for index, (_, column) in enumerate(label_fields)
    )
    sql = f"SELECT {compiled.identity_col} AS identity" + (", " + projection if projection else "")
    sql += (
        f" FROM {compiled.from_sql} WHERE {' AND '.join(where)} "
        f"ORDER BY {compiled.identity_col} LIMIT 5"
    )
    try:
        rows = provider.execute_select(compiled.metric_mapping.source_id, tenant, text(sql), params)
    except (SQLAlchemyError, KeyError) as exc:
        raise AnalysisError("PROVIDER_UNAVAILABLE") from exc
    return [
        (
            obj.identity_keys[0],
            str(row["identity"]),
            str(row["identity"])
            + " · "
            + "; ".join(
                f"{label}: {row.get('label' + str(index))}"
                for index, (label, _) in enumerate(label_fields)
            ),
        )
        for row in rows
    ]
