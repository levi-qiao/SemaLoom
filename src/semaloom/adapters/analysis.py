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

from semaloom.adapters.identifiers import require_ident
from semaloom.core.bundle import CompiledBundle
from semaloom.core.measure import aggregation_legal
from semaloom.core.model import EmbeddedProperty, LinkDef, MappingDef, MetricDef, ObjectTypeDef
from semaloom.core.semantic_query import (
    AnalysisError,
    EvidenceColumn,
    EvidenceTable,
    FilterAtom,
    FilterGroup,
    Formula,
    GroupByItem,
    MeasureTerm,
    MetricRef,
    PlanRef,
    QueryResult,
    SemanticQuery,
    SubjectSelector,
    TypedValue,
    _append_filter,
    conflicting_equalities,
    equality_value,
    without_field,
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
        "round",
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
_POSTGRES_TIME_GRAINS = frozenset({"YEAR", "QUARTER", "MONTH", "WEEK", "DAY"})


@dataclass
class _Plan:
    aggregation: str
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
        raise AnalysisError("UNKNOWN_METRIC")
    return metric


def _bare(field: str) -> str:
    return field.split(".")[-1]


def _mapping(service: _Context, target: str, *, prefer_table: str | None = None) -> MappingDef:
    matches = [
        item
        for item in service.bundle.mappings
        if item.target == target and item.provider == "postgres"
    ]
    if prefer_table:
        same = [item for item in matches if item.physical.get("table") == prefer_table]
        if len(same) == 1:
            return same[0]
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
    physical_filters: list[dict[str, Any]] = []
    rule = next((item for item in service.bundle.rules if item.output_metric == metric.id), None)
    if rule is None:
        return None
    for spec in rule.inputs:
        if spec.metric is None:
            return None
        mapping = _mapping(service, spec.metric)
        locations.add((mapping.source_id, mapping.physical.get("table")))
        physical_filters.append(dict(mapping.physical.get("filters") or {}))
        column = _projection(mapping).get("__value__")
        if column is None:
            return None
        inputs[spec.name] = column
    if len(locations) != 1:
        raise AnalysisError("LINK_ANALYSIS_UNSUPPORTED")
    # Inputs selected from different EAV rows need an explicit pivot/relationship plan.
    # Treating identical value columns as if they were columns on one row is incorrect.
    if any(physical_filters):
        raise AnalysisError("LINK_ANALYSIS_UNSUPPORTED")
    return _sql_expr(rule.expression, inputs)


def _sql_expr(expr: dict[str, Any], inputs: dict[str, str]) -> str | None:
    lowered = _sql_expr_ast(expr, inputs)
    return lowered.sql(dialect="postgres") if lowered is not None else None


def _sql_expr_ast(expr: dict[str, Any], inputs: dict[str, str]) -> exp.Expression | None:
    """Lower the closed semantic expression IR; never parse configured SQL text."""
    op = expr.get("op")
    if op == "ref":
        column = inputs.get(str(expr.get("name")))
        return exp.column(column) if column is not None else None
    if op == "decimal":
        return exp.Literal.number(str(expr.get("value")))
    if op in {"add", "sub", "mul", "div"}:
        args = [_sql_expr_ast(item, inputs) for item in expr.get("args", ())]
        if any(item is None for item in args):
            return None
        nodes = [item for item in args if item is not None]
        result: Any = nodes[0]
        operators = {"add": exp.Add, "sub": exp.Sub, "mul": exp.Mul, "div": exp.Div}
        for item in nodes[1:]:
            result = operators[op](this=result, expression=item)
        return exp.Paren(this=result)
    if op == "round" and expr.get("mode", "ROUND_HALF_UP") == "ROUND_HALF_UP":
        value = _sql_expr_ast(expr.get("value", {}), inputs)
        places = expr.get("places")
        if value is None or type(places) is not int:
            return None
        return exp.Round(this=value, decimals=exp.Literal.number(places))
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


def _single_link_pair(link: LinkDef) -> Any:
    if len(link.identity) != 1:
        raise AnalysisError("LINK_ANALYSIS_UNSUPPORTED")
    return link.identity[0]


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
        # Same-source SQL JOIN and cross-source bind-join share this gate:
        # collection analysis still requires a single identity pair.
        if len(link.identity) != 1:
            raise AnalysisError("LINK_ANALYSIS_UNSUPPORTED")
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
        local_key=_single_link_pair(resolved.link).source,
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
        key = _single_link_pair(resolved.link).source
        if key not in seen_keys:
            groups.append(GroupByItem(id=key))
            seen_keys.add(key)
    filters, extra = _strip_bind_filters(query.filters, obj, service, source_physical)
    binds.extend(extra)
    if not binds:
        return query, ()
    if query.formula or any(ref.aggregation == "AVG" for ref in query.metrics if ref.aggregation):
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
    scope_properties = metric.population.scope_properties if metric.population else ()
    if not aggregation_legal(metric.additivity or "FULL", aggregation, query, scope_properties):
        raise AnalysisError("ADDITIVITY_VIOLATION")
    if metric.value_type not in {"DECIMAL", "INTEGER"} and aggregation != "COUNT":
        raise AnalysisError("OPERATOR_NOT_SUPPORTED")
    try:
        metric_mapping = _mapping(service, metric.id)
    except AnalysisError:
        if not metric.derived_from:
            raise
        metric_mapping = _mapping(service, metric.derived_from[0])
    object_mapping = _mapping(
        service, metric.object_type, prefer_table=metric_mapping.physical.get("table")
    )
    if object_mapping.physical.get("table") != metric_mapping.physical.get("table"):
        raise AnalysisError("LINK_ANALYSIS_UNSUPPORTED")
    if query.formula and (query.group_by or query.limit or query.order_by):
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
    projection = {**_projection(object_mapping), **_projection(metric_mapping)}
    obj = next(item for item in service.bundle.object_types if item.id == metric.object_type)
    if len(obj.identity_keys) != 1:
        raise AnalysisError("UNSUPPORTED_IDENTITY")
    identity_col = projection.get(obj.identity_keys[0])
    if identity_col is None:
        raise AnalysisError("NO_MAPPING")
    subject = query.formula.subject if query.formula else None
    if subject and subject.identity and set(subject.identity) != set(obj.identity_keys):
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
            pair = _single_link_pair(link)
            source_col = projection.get(pair.source)
            target_col = target_projection.get(pair.target)
            if source_col is None or target_col is None:
                raise AnalysisError("NO_PATH")
            join_predicates = [
                f"{alias}.{require_ident(target_col, field='column')} = {source_col}"
            ]
            from_sql += (
                f" LEFT JOIN {target_table} AS {alias} ON {alias}.{target_tenant} = :tenant"
                + "".join(f" AND {predicate}" for predicate in join_predicates)
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
    where.extend(_metric_select_sql(metric, projection, params))
    if subject and subject.filters:
        subject_keys = set(subject.filters)
        overlap = subject_keys & _filter_fields(query.filters)
        scope = set(metric.population.scope_properties) if metric.population else set()
        if overlap - scope:
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
    population_columns: list[str] = []
    if metric.population:
        scope_columns = [projection.get(field) for field in metric.population.scope_properties]
        if unit_col is None or not all(scope_columns):
            raise AnalysisError("INVALID_PROPERTIES")
        population_columns = [unit_col, *(str(column) for column in scope_columns)]
    count_sql = (
        f"SELECT COUNT(*) AS population, COUNT({value_col}) AS observed, "
        f"COUNT(*) - COUNT({value_col}) AS missing"
        + (
            f", COUNT(DISTINCT ({', '.join(population_columns)})) "
            f"FILTER (WHERE {unit_col} IS NOT NULL) AS units"
            if population_columns and all(population_columns)
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


def _metric_select_sql(
    metric: MetricDef, projection: dict[str, str], params: dict[str, Any]
) -> list[str]:
    clauses: list[str] = []
    for key, value in metric.select.items():
        column = projection.get(key)
        if column is None:
            raise AnalysisError("NO_MAPPING")
        token = f"sel_{_bare(key)}"
        params[token] = value
        clauses.append(f"{column} = :{token}")
    if metric.perspective:
        column = projection.get("perspective")
        if column is not None:
            params["sel_perspective"] = metric.perspective
            clauses.append(f"{column} = :sel_perspective")
    return clauses


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
        if item.time_grain and item.time_grain.upper() not in _POSTGRES_TIME_GRAINS:
            raise AnalysisError("TIME_GRAIN_UNSUPPORTED")
        if item.time_grain and types.get(name) in {"DATE", "DATETIME"}:
            sqls.append(f"date_trunc('{item.time_grain.lower()}', {column})")
        elif item.time_grain:
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


def _distinct_dimension_values(
    service: _Context,
    metric: MetricDef,
    field: str,
    tenant: str,
) -> list[str | int | bool]:
    try:
        metric_mapping = _mapping(service, metric.id)
    except AnalysisError:
        metric_mapping = None
    mapping = metric_mapping or _mapping(service, metric.object_type)
    projection = _projection(mapping)
    if metric.population is None or field not in metric.population.scope_properties:
        raise AnalysisError("INVALID_PROPERTIES")
    obj = _object_type(service.bundle, metric.object_type)
    prop = next((item for item in obj.properties if item.id == field), None) if obj else None
    if prop is None:
        raise AnalysisError("INVALID_PROPERTIES")
    column = projection.get(field)
    if column is None:
        return []
    value_col = (
        _projection(metric_mapping).get("__value__")
        if metric_mapping is not None
        else _derived_sql(service, metric, projection)
    )
    if value_col is None:
        return []
    table = require_ident(mapping.physical.get("table"), field="table")
    tenant_col = require_ident(
        mapping.physical.get("tenantColumn", "tenant_id"), field="tenantColumn"
    )
    params: dict[str, Any] = {"tenant": tenant}
    where = [f"{tenant_col} = :tenant", f"{column} IS NOT NULL", f"{value_col} IS NOT NULL"]
    where.extend(_metric_select_sql(metric, projection, params))
    sql = text(
        f"SELECT DISTINCT {column} AS value FROM {table} WHERE {' AND '.join(where)} "
        "ORDER BY value LIMIT 30"
    )
    try:
        rows = _runner(service)(mapping.source_id, tenant, sql, params)
    except (SQLAlchemyError, KeyError) as exc:
        raise AnalysisError("PROVIDER_UNAVAILABLE") from exc
    values: list[str | int | bool] = []
    for row in rows:
        value = row.get("value")
        if value is None:
            continue
        if prop.value_type == "INTEGER":
            values.append(int(value))
        elif prop.value_type == "BOOLEAN":
            values.append(bool(value))
        else:
            values.append(value.isoformat() if hasattr(value, "isoformat") else str(value))
    return values


def _run(
    service: _Context, compiled: _Plan, tenant: str
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any] | None, list[dict[str, Any]], bool]:
    if compiled.query.formula is not None:
        return _run_formula(service, compiled, tenant)
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
    counts = {
        "population": population,
        "observed": observed,
        "missing": missing,
        "reason": reason,
    }
    if reason is not None:
        rows = []
    return rows, counts, None, evidence_rows, truncated


def _run_formula(
    service: _Context, compiled: _Plan, tenant: str
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any] | None, list[dict[str, Any]], bool]:
    """Each formula term scans itself. The evidence belongs to that scan."""

    run = _runner(service)
    calculation = _calculate(service, compiled, tenant, run)
    scan = calculation.pop("_scan", None) if calculation else None
    reason = None if calculation is None else calculation.get("reason")
    if scan is None:
        evidence_rows: list[dict[str, Any]] = []
        population = observed = missing = 0
        truncated = False
    else:
        evidence_rows = list(scan["rows"])
        population = int(scan["population"])
        observed = int(scan["observed"])
        missing = int(scan["missing"])
        truncated = bool(scan["truncated"])
        if scan.get("reason") and not reason:
            reason = scan["reason"]
    rows: list[dict[str, Any]] = []
    if reason is None and calculation and calculation.get("value") is not None:
        rows = [{"grain": {}, "value": calculation["value"]}]
    counts = {
        "population": population,
        "observed": observed,
        "missing": missing,
        "reason": reason,
    }
    return rows, counts, calculation, evidence_rows, truncated


def _calculate(service: _Context, compiled: _Plan, tenant: str, run: Any) -> dict[str, Any] | None:
    formula = compiled.query.formula
    if formula is None:
        return None
    with localcontext() as ctx:
        ctx.prec = 28
        evaluated = _eval_formula(service, compiled.query, formula, formula.subject, tenant, run)
    payload: dict[str, Any] = {
        "value": None if evaluated.value is None else format(evaluated.value, "f"),
        "numerator": None if evaluated.numerator is None else format(evaluated.numerator, "f"),
        "denominator": None
        if evaluated.denominator is None
        else format(evaluated.denominator, "f"),
        "formula": evaluated.formula,
        "reason": evaluated.reason,
        "subjectIdentity": evaluated.subject_identity,
        "mappings": list(evaluated.mappings),
    }
    if evaluated.current_period is not None or evaluated.prior_period is not None:
        payload["currentPeriod"] = evaluated.current_period
        payload["priorPeriod"] = evaluated.prior_period
    if evaluated.peer_relation:
        payload["peerRelation"] = evaluated.peer_relation
    if evaluated.executed_filters is not None:
        payload["executedFilters"] = evaluated.executed_filters
    if evaluated.population is not None:
        payload["_scan"] = {
            "population": evaluated.population,
            "observed": evaluated.observed,
            "missing": evaluated.missing,
            "rows": list(evaluated.evidence_rows),
            "truncated": evaluated.truncated,
            "reason": evaluated.reason,
        }
    return payload


@dataclass
class _Scalar:
    value: Decimal | None
    formula: str
    reason: str | None = None
    numerator: Decimal | None = None
    denominator: Decimal | None = None
    subject_identity: str | None = None
    current_period: Any = None
    prior_period: Any = None
    mappings: tuple[str, ...] = ()
    peer_relation: str | None = None
    evidence_rows: tuple[dict[str, Any], ...] = ()
    population: int | None = None
    observed: int | None = None
    missing: int | None = None
    truncated: bool = False
    executed_filters: Any = None
    scan_scope: str | None = None


def _formula_value_metadata(service: _Context, node: Formula | MeasureTerm) -> tuple[str, str]:
    if isinstance(node, MeasureTerm):
        metric = _metric(service, node.metric)
        if node.aggregation == "COUNT":
            return "count", "INTEGER"
        return (
            metric.unit or "",
            "DECIMAL" if node.aggregation == "AVG" else metric.value_type or "DECIMAL",
        )
    left_unit, left_type = _formula_value_metadata(service, node.left)
    if node.op == "VALUE":
        return left_unit, left_type
    assert node.right is not None
    right_unit, right_type = _formula_value_metadata(service, node.right)
    if node.op == "DIFFERENCE":
        if left_unit != right_unit:
            raise AnalysisError("UNIT_MISMATCH")
        return left_unit, "INTEGER" if left_type == right_type == "INTEGER" else "DECIMAL"
    unit = "" if left_unit == right_unit else f"({left_unit or '1'})/({right_unit or '1'})"
    return unit, "DECIMAL"


def _formula_text(node: Formula | MeasureTerm) -> str:
    if isinstance(node, MeasureTerm):
        text = f"{node.aggregation}({node.metric})"
        if node.previous_observed:
            text = f"previous({text})"
        if node.scope == "SUBJECT":
            text += "[subject]"
        elif node.scope == "PEERS":
            text += "[peers]"
        if node.value_relation:
            text += f" where value {node.value_relation} subject"
        return text
    if node.op == "VALUE":
        return _formula_text(node.left)
    symbol = "/" if node.op == "RATIO" else "-"
    assert node.right is not None
    return f"({_formula_text(node.left)} {symbol} {_formula_text(node.right)})"


def _eval_formula(
    service: _Context,
    query: SemanticQuery,
    node: Formula | MeasureTerm,
    subject: SubjectSelector | None,
    tenant: str,
    run: Any,
) -> _Scalar:
    if isinstance(node, MeasureTerm):
        return _eval_term(service, query, node, subject, tenant, run)
    left = _eval_formula(service, query, node.left, node.subject or subject, tenant, run)
    if node.op == "VALUE":
        return left
    assert node.right is not None
    right = _eval_formula(service, query, node.right, node.subject or subject, tenant, run)
    symbol = "/" if node.op == "RATIO" else "-"
    formula = f"({left.formula} {symbol} {right.formula})"
    mappings = tuple(dict.fromkeys((*left.mappings, *right.mappings)))
    identity = left.subject_identity or right.subject_identity
    relation = left.peer_relation or right.peer_relation
    if left.reason or right.reason or left.value is None or right.value is None:
        chosen = _choose_scan(left, right)
        return _Scalar(
            None,
            formula,
            left.reason or right.reason or "NO_OBSERVED_VALUES",
            left.value,
            right.value,
            identity,
            mappings=mappings,
            peer_relation=relation,
            evidence_rows=chosen.evidence_rows,
            population=chosen.population,
            observed=chosen.observed,
            missing=chosen.missing,
            truncated=chosen.truncated,
            executed_filters=chosen.executed_filters,
            scan_scope=chosen.scan_scope,
            current_period=chosen.current_period,
            prior_period=chosen.prior_period,
        )
    chosen = _choose_scan(left, right)
    shared = {
        "mappings": mappings,
        "peer_relation": relation,
        "evidence_rows": chosen.evidence_rows,
        "population": chosen.population,
        "observed": chosen.observed,
        "missing": chosen.missing,
        "truncated": chosen.truncated,
        "executed_filters": chosen.executed_filters,
        "scan_scope": chosen.scan_scope,
        "current_period": chosen.current_period,
        "prior_period": chosen.prior_period,
    }
    if node.op == "DIFFERENCE":
        return _Scalar(
            left.value - right.value, formula, None, left.value, right.value, identity, **shared
        )
    if right.value == 0:
        return _Scalar(
            None,
            formula,
            "ZERO_DENOMINATOR",
            left.value,
            right.value,
            identity,
            **shared,
        )
    return _Scalar(
        left.value / right.value, formula, None, left.value, right.value, identity, **shared
    )


def _eval_term(
    service: _Context,
    query: SemanticQuery,
    term: MeasureTerm,
    subject: SubjectSelector | None,
    tenant: str,
    run: Any,
) -> _Scalar:
    inner = query.model_copy(
        update={
            "metrics": (MetricRef(id=term.metric, aggregation=term.aggregation),),
            "formula": None,
            "group_by": (),
            "order_by": (),
            "limit": None,
        }
    )
    current_period = None
    prior_period = None
    if term.previous_observed:
        shifted = _shift_to_previous(service, inner, tenant)
        if shifted is None:
            field_value = _constrained_scope(service, inner)
            return _Scalar(
                None,
                _formula_text(term),
                "PRIOR_PERIOD_MISSING",
                current_period=None if field_value is None else field_value[1],
            )
        inner, current_period, prior_period = shifted
    plan = _compile(service, inner, tenant)
    guarded = _population_guard(plan, run, tenant)
    scan = _scan_fields(guarded, _filter_payload(inner.filters), term.scope)
    where = list(plan.where)
    params = dict(plan.params)
    identity = None
    if guarded.reason and term.scope != "SUBJECT":
        return _Scalar(
            None,
            _formula_text(term),
            guarded.reason,
            subject_identity=identity,
            current_period=current_period,
            prior_period=prior_period,
            mappings=(plan.metric_mapping.id,),
            **scan,
        )
    if term.scope == "SUBJECT":
        if subject is None:
            raise AnalysisError("COMPARISON_SUBJECT_REQUIRED")
        identity = _require_subject(plan, subject, where, params, run, tenant)
    elif term.scope == "PEERS" or term.value_relation is not None:
        if subject is None:
            raise AnalysisError("COMPARISON_SUBJECT_REQUIRED")
        identity = _subject_identity(plan, subject, run, tenant)
        where.append(f"{plan.identity_col} <> :excluded_identity")
        params["excluded_identity"] = identity
    if term.value_relation:
        reference = _subject_total(service, query, term, subject, tenant, run)
        if reference is None:
            return _Scalar(
                None,
                _formula_text(term),
                "SUBJECT_VALUE_MISSING",
                subject_identity=identity,
                mappings=(plan.metric_mapping.id,),
                peer_relation=term.value_relation,
                **scan,
            )
        params["subject_value"] = reference
        operator = "<" if term.value_relation == "LT" else ">"
        rows = run(
            plan.metric_mapping.source_id,
            tenant,
            text(
                f"SELECT COUNT({plan.value_col}) FILTER "
                f"(WHERE {plan.value_col} {operator} :subject_value) AS total "
                f"FROM {plan.from_sql} WHERE {' AND '.join(where)}"
            ),
            params,
        )
        return _Scalar(
            Decimal(str(rows[0]["total"] or 0)),
            _formula_text(term),
            subject_identity=identity,
            mappings=(plan.metric_mapping.id,),
            peer_relation=term.value_relation,
            **scan,
        )
    value = _scalar_aggregate(plan, where, params, run, tenant)
    if term.scope == "SUBJECT" and value is None:
        return _Scalar(
            None,
            _formula_text(term),
            "SUBJECT_VALUE_MISSING",
            subject_identity=identity,
            current_period=current_period,
            prior_period=prior_period,
            mappings=(plan.metric_mapping.id,),
            **scan,
        )
    return _Scalar(
        value,
        _formula_text(term),
        subject_identity=identity,
        current_period=current_period,
        prior_period=prior_period,
        mappings=(plan.metric_mapping.id,),
        **scan,
    )


@dataclass
class _Guard:
    reason: str | None
    population: int
    observed: int
    missing: int
    rows: tuple[dict[str, Any], ...]
    truncated: bool


def _population_guard(plan: _Plan, run: Any, tenant: str) -> _Guard:
    """Same missing-policy and duplicate-unit gate the plain aggregate uses."""

    try:
        count_row = run(plan.metric_mapping.source_id, tenant, text(plan.count_sql), plan.params)[0]
        evidence_rows = run(
            plan.metric_mapping.source_id, tenant, text(plan.evidence_sql), plan.params
        )
    except (SQLAlchemyError, KeyError, IndexError) as exc:
        raise AnalysisError("PROVIDER_UNAVAILABLE") from exc
    for row in evidence_rows:
        value = row.get("value")
        if isinstance(value, float):
            raise AnalysisError("FLOAT_ARITHMETIC")
        if isinstance(value, Decimal) and not value.is_finite():
            raise AnalysisError("NON_FINITE_VALUE")
    population = int(count_row["population"] or 0)
    observed = int(count_row["observed"] or 0)
    missing = int(count_row["missing"] or 0)
    if plan.unit_col is not None and population and int(count_row.get("units") or 0) != population:
        raise AnalysisError("DUPLICATE_OR_MISSING_STATISTICAL_UNIT")
    reason = None
    if population == 0:
        reason = "EMPTY_POPULATION"
    elif missing and plan.query.missing_policy != "exclude":
        reason = "MISSING_VALUES_REQUIRE_EXPLICIT_EXCLUSION"
    elif observed == 0:
        reason = "NO_OBSERVED_VALUES"
    return _Guard(
        reason,
        population,
        observed,
        missing,
        tuple(evidence_rows),
        population > len(evidence_rows),
    )


def _filter_payload(node: FilterAtom | FilterGroup | None) -> Any:
    if node is None:
        return None
    return node.model_dump(mode="json", by_alias=True)


def _scan_fields(guard: _Guard, filters: Any, scope: str) -> dict[str, Any]:
    return {
        "evidence_rows": guard.rows,
        "population": guard.population,
        "observed": guard.observed,
        "missing": guard.missing,
        "truncated": guard.truncated,
        "executed_filters": filters,
        "scan_scope": scope,
    }


def _choose_scan(left: _Scalar, right: _Scalar) -> _Scalar:
    """Prefer the scan that explains a refusal, otherwise the shifted or full population."""

    def rank(item: _Scalar) -> tuple[int, int, int]:
        blocking = (
            0
            if item.reason
            in {
                "MISSING_VALUES_REQUIRE_EXPLICIT_EXCLUSION",
                "EMPTY_POPULATION",
                "NO_OBSERVED_VALUES",
            }
            else 1
        )
        shifted = 0 if item.prior_period is not None else 1
        population = 0 if item.scan_scope == "QUERY" else 1
        return (blocking, shifted, population)

    return min((left, right), key=rank)


def _constrained_scope(service: _Context, query: SemanticQuery) -> tuple[str, Any] | None:
    metric = _metric(service, query.metrics[0].id)
    scope = metric.population.scope_properties if metric.population else ()
    constrained = [
        (field, equality_value(query.filters, field))
        for field in scope
        if equality_value(query.filters, field) is not None
    ]
    if len(constrained) == 1:
        return constrained[0]
    if len(scope) == 1 and constrained:
        return constrained[0]
    return None


def _shift_to_previous(
    service: _Context, query: SemanticQuery, tenant: str
) -> tuple[SemanticQuery, Any, Any] | None:
    metric = _metric(service, query.metrics[0].id)
    scope = metric.population.scope_properties if metric.population else ()
    constrained = [field for field in scope if equality_value(query.filters, field) is not None]
    if len(constrained) == 1:
        field = constrained[0]
    elif len(scope) == 1:
        field = scope[0]
    else:
        raise AnalysisError("TIME_GRAIN_UNSUPPORTED")
    current = equality_value(query.filters, field)
    if current is None:
        raise AnalysisError("COMPARISON_PERIOD_REQUIRED")
    sequence_query = query.model_copy(
        update={
            "metrics": (MetricRef(id=metric.id, aggregation="COUNT"),),
            "filters": without_field(query.filters, field),
        }
    )
    sequence_plan = _compile(service, sequence_query, tenant)
    column = sequence_plan.projection[field]
    periods = [
        row["value"]
        for row in _runner(service)(
            sequence_plan.metric_mapping.source_id,
            tenant,
            text(
                f"SELECT DISTINCT {column} AS value FROM {sequence_plan.from_sql} "
                f"WHERE {' AND '.join(sequence_plan.where)} AND {column} IS NOT NULL "
                f"AND {sequence_plan.value_col} IS NOT NULL AND {column} <= :current_period "
                "ORDER BY value DESC LIMIT 2"
            ),
            {**sequence_plan.params, "current_period": current},
        )
    ]
    periods.reverse()
    index = next((item for item, value in enumerate(periods) if str(value) == str(current)), None)
    if index is None or index == 0:
        return None
    prior = periods[index - 1]
    obj = _object_type(service.bundle, metric.object_type)
    prop = next((item for item in obj.properties if item.id == field), None) if obj else None
    if prop is None:
        raise AnalysisError("INVALID_PROPERTIES")
    shifted = query.model_copy(
        update={
            "filters": _append_filter(
                without_field(query.filters, field),
                FilterAtom(
                    field=field,
                    op="EQ",
                    value=TypedValue(value_type=prop.value_type, value=prior),
                ),
            )
        }
    )
    return shifted, current, prior


def _require_subject(
    plan: _Plan,
    subject: SubjectSelector,
    where: list[str],
    params: dict[str, Any],
    run: Any,
    tenant: str,
) -> str:
    identity = subject.identity or subject.filters or {}
    if not identity:
        raise AnalysisError("INVALID_SUBJECT_PROPERTIES")
    for key, value in identity.items():
        column = plan.projection.get(_bare(key))
        if column is None:
            if subject.identity is not None:
                column = plan.identity_col
            else:
                raise AnalysisError("INVALID_SUBJECT_PROPERTIES")
        token = f"s_{_bare(key)}"
        where.append(f"{column} = :{token}")
        params[token] = value
    rows = run(
        plan.metric_mapping.source_id,
        tenant,
        text(
            f"SELECT COUNT(*) AS members, MIN({plan.identity_col}) AS identity "
            f"FROM {plan.from_sql} WHERE {' AND '.join(where)}"
        ),
        params,
    )
    members = int(rows[0]["members"] or 0)
    if members == 0:
        raise AnalysisError("COMPARISON_SUBJECT_OUTSIDE_POPULATION")
    if members != 1:
        raise AnalysisError("AMBIGUOUS_COMPARISON_SUBJECT")
    return str(rows[0]["identity"])


def _subject_identity(plan: _Plan, subject: SubjectSelector, run: Any, tenant: str) -> str:
    """Resolve one subject without narrowing the population predicate."""

    where = list(plan.where)
    params = dict(plan.params)
    return _require_subject(plan, subject, where, params, run, tenant)


def _subject_total(
    service: _Context,
    query: SemanticQuery,
    term: MeasureTerm,
    subject: SubjectSelector | None,
    tenant: str,
    run: Any,
) -> Decimal | None:
    if subject is None:
        raise AnalysisError("COMPARISON_SUBJECT_REQUIRED")
    inner = query.model_copy(
        update={
            "metrics": (MetricRef(id=term.metric, aggregation="SUM"),),
            "formula": None,
            "group_by": (),
            "order_by": (),
            "limit": None,
        }
    )
    plan = _compile(service, inner, tenant)
    where = list(plan.where)
    params = dict(plan.params)
    _require_subject(plan, subject, where, params, run, tenant)
    return _scalar_aggregate(plan, where, params, run, tenant)


def _scalar_aggregate(
    plan: _Plan, where: list[str], params: dict[str, Any], run: Any, tenant: str
) -> Decimal | None:
    column = plan.value_col
    if plan.aggregation == "COUNT":
        select = f"SELECT COUNT({column}) AS total, COUNT({column}) AS n"
    elif plan.aggregation == "AVG":
        select = f"SELECT SUM({column}) AS total, COUNT({column}) AS n"
    else:
        select = f"SELECT {plan.aggregation}({column}) AS total, COUNT({column}) AS n"
    rows = run(
        plan.metric_mapping.source_id,
        tenant,
        text(f"{select} FROM {plan.from_sql} WHERE {' AND '.join(where)}"),
        params,
    )
    observed = int(rows[0]["n"] or 0)
    raw = rows[0]["total"]
    if plan.aggregation == "COUNT":
        return Decimal(str(raw or 0))
    if raw is None or observed == 0:
        return None
    value = Decimal(str(raw))
    if plan.aggregation == "AVG":
        value = value / observed
    return value


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
    labelable = set(obj.identity_keys)
    if obj.population is not None:
        labelable.add(obj.population.unit_property)
    for field, ids in field_ids.items():
        if _bare(field) not in labelable:
            continue
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


def _dictionary_labels(
    service: _Context,
    source: ObjectTypeDef,
    field_ids: dict[str, set[str]],
    tenant: str | None = None,
) -> dict[tuple[str, str], str]:
    objects = [source]
    linked = {
        link.target
        for link in service.bundle.links
        if link.source == source.id and link.cardinality == "ONE"
    }
    objects.extend(obj for obj in service.bundle.object_types if obj.id in linked)
    found: dict[tuple[str, str], str] = {}
    for field, ids in field_ids.items():
        bare = _bare(field)
        matches = [
            prop for obj in objects for prop in obj.properties if prop.id == bare and prop.values
        ]
        if len(matches) != 1:
            continue
        dictionary = {str(item.id): item.label or str(item.id) for item in matches[0].values}
        for value in ids:
            if value in dictionary:
                found[(field, value)] = dictionary[value]
    if tenant:
        found.update(_mapped_value_labels(service, source, tenant, field_ids))
    return found


def _mapped_value_labels(
    service: _Context,
    source: ObjectTypeDef,
    tenant: str,
    field_ids: dict[str, set[str]],
) -> dict[tuple[str, str], str]:
    """Read optional dictionary tables declared on Mapping.physical.valueLabels."""
    found: dict[tuple[str, str], str] = {}
    objects = {source.id}
    objects.update(
        link.target
        for link in service.bundle.links
        if link.source == source.id and link.cardinality == "ONE"
    )
    run = getattr(service.provider, "execute_select", None)
    if not callable(run):
        return found
    for mapping in service.bundle.mappings:
        if mapping.target not in objects or mapping.provider != "postgres":
            continue
        specs = mapping.physical.get("valueLabels")
        if not isinstance(specs, dict):
            continue
        tenant_col = require_ident(
            mapping.physical.get("tenantColumn", "tenant_id"), field="tenantColumn"
        )
        for field, spec in specs.items():
            if not isinstance(spec, dict):
                continue
            needed = field_ids.get(str(field)) or field_ids.get(_bare(str(field)))
            if not needed:
                continue
            table = require_ident(spec.get("table") or mapping.physical.get("table"), field="table")
            id_col = require_ident(spec.get("idColumn") or spec.get("id_column"), field="idColumn")
            label_col = require_ident(
                spec.get("labelColumn") or spec.get("label_column"), field="labelColumn"
            )
            params: dict[str, Any] = {"tenant": tenant}
            keys: list[str] = []
            for index, ident in enumerate(sorted(str(item) for item in needed if item)[:50]):
                token = f"lab_{index}"
                params[token] = ident
                keys.append(f":{token}")
            if not keys:
                continue
            sql = text(
                f"SELECT {id_col} AS ident, {label_col} AS label FROM {table} "
                f"WHERE {tenant_col} = :tenant AND {id_col} IN ({', '.join(keys)})"
            )
            try:
                rows = run(mapping.source_id, tenant, sql, params)
            except (SQLAlchemyError, KeyError, AnalysisError):
                continue
            for row in rows:
                ident = str(row.get("ident") or "")
                label = str(row.get("label") or "").strip()
                if ident and label:
                    found.setdefault((str(field), ident), label)
                    found.setdefault((_bare(str(field)), ident), label)
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
        if len(link.identity) != 1:
            continue
        pair = link.identity[0]
        ids = {str(item) for item in field_ids.get(pair.source, set()) if item not in {"", "None"}}
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
        identity_col = projection.get(pair.target)
        if identity_col is None:
            continue
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
                found[(pair.source, ident)] = name
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
        resolved.update(_dictionary_labels(service, obj, field_ids, tenant))
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
        EvidenceColumn(id="identity", label="对象", role="CATEGORY", value_type="STRING"),
        EvidenceColumn(
            id="value",
            label="引擎值",
            role="MEASURE",
            value_type="INTEGER" if compiled.aggregation == "COUNT" else compiled.metric.value_type,
            unit="count" if compiled.aggregation == "COUNT" else compiled.metric.unit,
        ),
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
        columns[0] = columns[0].model_copy(update={"role": "DIMENSION"})
        columns.insert(
            1,
            EvidenceColumn(id="label", label=label_title, role="CATEGORY", value_type="STRING"),
        )
        extra_ids = [item for item in extra_ids if item != "unit_id"]
        include_resolved = True
    else:
        include_resolved = False
        for key in extra_ids:
            prop = next((item for item in (obj.properties if obj else ()) if item.id == key), None)
            columns.insert(
                -1,
                EvidenceColumn(
                    id=key,
                    label=prop.label or prop.id if prop else key,
                    role="DIMENSION",
                    value_type=prop.value_type if prop else "STRING",
                    unit=prop.unit if prop else None,
                ),
            )
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
    identity = projection.get(_single_link_pair(bind.link).target)
    if identity is None:
        raise AnalysisError("NO_MAPPING")
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
    identity = projection.get(_single_link_pair(bind.link).target)
    if identity is None:
        raise AnalysisError("NO_MAPPING")
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
    rows, counts, calculation, evidence_rows, truncated = _run(service, compiled, tenant)
    unit, value_type = (
        _formula_value_metadata(service, query.formula)
        if query.formula is not None
        else (
            "count" if compiled.aggregation == "COUNT" else compiled.metric.unit,
            "INTEGER" if compiled.aggregation == "COUNT" else compiled.metric.value_type,
        )
    )
    values = tuple(
        {
            "metric": compiled.metric.id,
            "grain": row.get("grain") or {},
            "value": row["value"],
            "unit": unit,
            "valueType": value_type,
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
            _mapping(
                service,
                compiled.metric.object_type,
                prefer_table=compiled.metric_mapping.physical.get("table"),
            ),
            *(_mapping(service, dependency) for dependency in compiled.metric.derived_from),
        ]
    }
    for mapping_id in () if calculation is None else calculation.get("mappings") or []:
        found = next((item for item in service.bundle.mappings if item.id == mapping_id), None)
        if found is not None:
            used_mappings[found.id] = found
    return QueryResult(
        result_id=uuid.uuid4().hex,
        plan_id=plan.plan_id,
        release_digest=service.bundle.digest,
        values=values,
        scope={
            "populationCount": counts["population"],
            "observedCount": counts["observed"],
            "missingCount": counts["missing"],
            "denominator": None if calculation is None else calculation.get("denominator"),
            "numerator": None if calculation is None else calculation.get("numerator"),
            "calculation": calculation,
            "reason": counts.get("reason"),
            "subjectIdentity": None if calculation is None else calculation.get("subjectIdentity"),
            "executedFilters": None if calculation is None else calculation.get("executedFilters"),
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
                **(
                    {"formula": calculation["formula"]}
                    if calculation and calculation.get("formula")
                    else {}
                ),
            },
        ),
    )


def _digest(service: _Context, query: SemanticQuery, tenant: str) -> str:
    # Bind values, scope and immutable definitions, not merely the SQL shape.
    payload = [service.bundle.digest, tenant, query.model_dump(mode="json", by_alias=True)]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _formula_plans(
    context: _Context,
    query: SemanticQuery,
    node: Formula | MeasureTerm,
    tenant: str,
    subject: SubjectSelector | None = None,
) -> list[_Plan]:
    if isinstance(node, Formula):
        subject = node.subject or subject
        plans = _formula_plans(context, query, node.left, tenant, subject)
        if node.right is not None:
            plans.extend(_formula_plans(context, query, node.right, tenant, subject))
        return plans
    if node.value_relation is not None and (node.aggregation != "COUNT" or node.scope != "PEERS"):
        raise AnalysisError("OPERATOR_NOT_SUPPORTED")
    single = query.model_copy(
        update={
            "metrics": (MetricRef(id=node.metric, aggregation=node.aggregation),),
            "formula": Formula(op="VALUE", left=node, subject=subject),
        }
    )
    plan = _compile(context, single, tenant)
    if (node.scope != "QUERY" or node.value_relation is not None) and subject is None:
        raise AnalysisError("COMPARISON_SUBJECT_REQUIRED")
    return [plan]


def prepare_analysis(
    bundle: CompiledBundle, query: SemanticQuery, tenant: str, provider: Any
) -> str:
    context = _Context(bundle, provider)
    if not query.metrics:
        raise AnalysisError("METRIC_REQUIRED")
    if query.formula is not None:
        _formula_value_metadata(context, query.formula)
    if len({(ref.id, ref.aggregation) for ref in query.metrics}) != len(query.metrics):
        raise AnalysisError("DUPLICATE_METRIC_SELECTION")
    sources = set()
    for ref in query.metrics:
        single = query.model_copy(update={"metrics": (ref,)})
        compiled = _compile(context, single, tenant)
        sources.add((compiled.metric_mapping.source_id, compiled.table))
    if query.formula is not None:
        for compiled in _formula_plans(context, query, query.formula, tenant):
            sources.add((compiled.metric_mapping.source_id, compiled.table))
    if len(sources) != 1:
        raise AnalysisError("CROSS_SOURCE_SQL")
    if len(query.metrics) > 1 and (query.order_by or query.limit):
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
        metric_runs = (
            (plan.query.metrics[0],) if plan.query.formula is not None else plan.query.metrics
        )
        results = [
            _execute_one(
                context,
                plan
                if plan.query.formula is not None
                else plan.model_copy(
                    update={"query": plan.query.model_copy(update={"metrics": (ref,)})}
                ),
                tenant,
            )
            for ref in metric_runs
        ]
    except (SQLAlchemyError, KeyError, IndexError) as exc:
        raise AnalysisError("PROVIDER_UNAVAILABLE") from exc
    first = results[0]
    scopes = {ref.id: result.scope for ref, result in zip(metric_runs, results, strict=True)}
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
                columns=(
                    EvidenceColumn(
                        id="metric", label="指标", role="DIMENSION", value_type="STRING"
                    ),
                    *first.evidence.columns,
                ),
                rows=tuple(
                    (ref.id, *row)
                    for ref, result in zip(metric_runs, results, strict=True)
                    for row in result.evidence.rows
                ),
                truncated=any(result.evidence.truncated for result in results),
                row_count=sum(result.evidence.row_count or 0 for result in results),
            )
            if len(results) > 1
            else first.evidence,
        }
    )


def analysis_dimension_values(
    bundle: CompiledBundle,
    metric_id: str,
    field: str,
    tenant: str,
    provider: Any,
) -> list[str | int | bool]:
    context = _Context(bundle, provider)
    return _distinct_dimension_values(context, _metric(context, metric_id), field, tenant)


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
    subject = query.formula.subject if query.formula else None
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
