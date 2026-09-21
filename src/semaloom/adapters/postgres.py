"""PostgreSQL read adapter. Identifiers come from approved mappings only."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError

from semaloom.adapters.identifiers import require_ident
from semaloom.core.bundle import CompiledBundle
from semaloom.core.model import MappingDef
from semaloom.core.provider import IdentityScalar, IdentityValue, ObjectRead, ObjectSearch
from semaloom.core.results import Observation
from semaloom.core.semantic_query import AnalysisError, PlanRef, QueryResult, SemanticQuery


class PostgresReadProvider:
    def __init__(
        self,
        engines: dict[str, Engine],
        url_resolver: Callable[[str, str], str | None] | None = None,
    ) -> None:
        self._engines = engines
        self._url_resolver = url_resolver
        self._dynamic_engines: dict[tuple[str, str, str], Engine] = {}

    def fetch_metric(
        self,
        mapping: MappingDef,
        *,
        tenant: str,
        identity_value: IdentityValue,
        bindings: dict[str, IdentityScalar] | None = None,
    ) -> Observation:
        physical = mapping.physical
        observed = datetime.now(UTC).isoformat()
        try:
            engine = self._engine(mapping.source_id, tenant)
            table = require_ident(physical.get("table"), field="table")
            value_col = require_ident(physical.get("valueColumn"), field="valueColumn")
            tenant_col = require_ident(
                physical.get("tenantColumn", "tenant_id"), field="tenantColumn"
            )
            identity_columns = _identity_columns(mapping, identity_value)
            params: dict[str, Any] = {"tenant": tenant}
            clauses = [f"{tenant_col} = :tenant"]
            for index, (semantic, value) in enumerate(identity_value.items()):
                column = identity_columns[semantic]
                pname = f"i_{index}"
                clauses.append(f"{column} = :{pname}")
                params[pname] = value
            filters = physical.get("filters")
            if isinstance(filters, dict):
                for key, value in filters.items():
                    column = require_ident(
                        key if key != "metric" else "metric", field=f"filter.{key}"
                    )
                    pname = f"f_{column}"
                    clauses.append(f"{column} = :{pname}")
                    params[pname] = value
            if bindings:
                grain = mapping.physical.get("grainColumns")
                if not isinstance(grain, dict):
                    raise ValueError("grainColumns must be an object")
                for index, (semantic, value) in enumerate(bindings.items()):
                    column = require_ident(grain.get(semantic), field=f"binding.{semantic}")
                    pname = f"b_{index}"
                    clauses.append(f"{column} = :{pname}")
                    params[pname] = value
            sql = text(
                f"SELECT {value_col} AS value FROM {table} WHERE {' AND '.join(clauses)} LIMIT 2"
            )
            with _read_transaction(engine) as conn:
                rows = list(conn.execute(sql, params))
        except (SQLAlchemyError, KeyError, ValueError):
            return Observation(
                kind="UNAVAILABLE",
                target=mapping.target,
                reason="PROVIDER_ERROR",
                mapping_id=mapping.id,
                source_id=mapping.source_id,
                observed_at=observed,
            )
        if len(rows) > 1:
            return Observation(
                kind="UNAVAILABLE",
                target=mapping.target,
                reason="CARDINALITY_VIOLATION",
                mapping_id=mapping.id,
                source_id=mapping.source_id,
                observed_at=observed,
            )
        if not rows:
            return Observation(
                kind="MISSING",
                target=mapping.target,
                mapping_id=mapping.id,
                source_id=mapping.source_id,
                observed_at=observed,
                reason="NO_ROW",
            )
        raw = rows[0][0]
        if raw is None:
            return Observation(
                kind="NULL",
                target=mapping.target,
                mapping_id=mapping.id,
                source_id=mapping.source_id,
                observed_at=observed,
                reason="NULL_INPUT",
            )
        if isinstance(raw, Decimal):
            value = format(raw, "f")
        else:
            value = str(raw)
        return Observation(
            kind="PRESENT",
            target=mapping.target,
            value=value,
            value_type="DECIMAL",
            unit=None,
            mapping_id=mapping.id,
            source_id=mapping.source_id,
            observed_at=observed,
        )

    def fetch_object(
        self,
        mapping: MappingDef,
        *,
        tenant: str,
        identity_value: IdentityValue,
    ) -> ObjectRead:
        observed = datetime.now(UTC).isoformat()
        try:
            engine = self._engine(mapping.source_id, tenant)
            table = require_ident(mapping.physical.get("table"), field="table")
            tenant_col = require_ident(
                mapping.physical.get("tenantColumn", "tenant_id"), field="tenantColumn"
            )
            identity_columns = _identity_columns(mapping, identity_value)
            projection = _object_projection(mapping)
            if not projection:
                raise ValueError("object mapping has no approved projection")
            selected = ", ".join(
                f'{column} AS "{semantic}"' for semantic, column in projection.items()
            )
            params: dict[str, Any] = {"tenant": tenant}
            clauses = [f"{tenant_col} = :tenant"]
            for index, (semantic, value) in enumerate(identity_value.items()):
                pname = f"i_{index}"
                clauses.append(f"{identity_columns[semantic]} = :{pname}")
                params[pname] = value
            sql = text(f"SELECT {selected} FROM {table} WHERE {' AND '.join(clauses)} LIMIT 2")
            with _read_transaction(engine) as conn:
                rows = conn.execute(sql, params).mappings().all()
        except (SQLAlchemyError, KeyError, ValueError):
            return ObjectRead(
                kind="UNAVAILABLE",
                reason="PROVIDER_ERROR",
                mapping_id=mapping.id,
                source_id=mapping.source_id,
                observed_at=observed,
            )
        if len(rows) > 1:
            return ObjectRead(
                kind="UNAVAILABLE",
                reason="CARDINALITY_VIOLATION",
                mapping_id=mapping.id,
                source_id=mapping.source_id,
                observed_at=observed,
            )
        if not rows:
            return ObjectRead(
                kind="MISSING",
                reason="NO_ROW",
                mapping_id=mapping.id,
                source_id=mapping.source_id,
                observed_at=observed,
            )
        return ObjectRead(
            kind="PRESENT",
            values=dict(rows[0]),
            mapping_id=mapping.id,
            source_id=mapping.source_id,
            observed_at=observed,
        )

    def search_objects(
        self,
        mapping: MappingDef,
        *,
        tenant: str,
        filters: dict[str, Any],
        properties: tuple[str, ...],
        limit: int,
    ) -> ObjectSearch:
        observed = datetime.now(UTC).isoformat()
        try:
            if not 1 <= limit <= 50:
                raise ValueError("invalid limit")
            projection = _object_projection(mapping)
            table = require_ident(mapping.physical.get("table"), field="table")
            tenant_col = require_ident(
                mapping.physical.get("tenantColumn", "tenant_id"), field="tenantColumn"
            )
            if not properties or (set(properties) | set(filters)) - set(projection):
                raise ValueError("unmapped property")
            params: dict[str, Any] = {"tenant": tenant, "limit": limit + 1}
            clauses = [f"{tenant_col} = :tenant"]
            for index, (key, value) in enumerate(filters.items()):
                clauses.append(f"{projection[key]} = :p{index}")
                params[f"p{index}"] = value
            fixed = mapping.physical.get("filters", {})
            if isinstance(fixed, dict):
                for index, (key, value) in enumerate(fixed.items()):
                    col = require_ident(key, field="filter")
                    clauses.append(f"{col} = :f{index}")
                    params[f"f{index}"] = value
            selected = ", ".join(f'{projection[key]} AS "{key}"' for key in properties)
            order_columns = [projection[key] for key in mapping.identity_fields]
            order_by = ", ".join(order_columns)
            statement = text(
                f"SELECT {selected} FROM {table} WHERE {' AND '.join(clauses)} "
                f"ORDER BY {order_by} LIMIT :limit"
            )
            with _read_transaction(self._engine(mapping.source_id, tenant)) as conn:
                rows = conn.execute(statement, params).mappings().all()
            return ObjectSearch(
                kind="PRESENT",
                rows=tuple(dict(row) for row in rows[:limit]),
                has_more=len(rows) > limit,
                observed_at=observed,
            )
        except (SQLAlchemyError, KeyError, ValueError):
            return ObjectSearch(kind="UNAVAILABLE", reason="PROVIDER_ERROR", observed_at=observed)

    def _engine(self, source_id: str, tenant: str) -> Engine:
        if self._url_resolver is not None:
            url = self._url_resolver(tenant, source_id)
            if url is not None:
                key = (tenant, source_id, url)
                engine = self._dynamic_engines.get(key)
                if engine is None:
                    for stale in [
                        item
                        for item in self._dynamic_engines
                        if item[:2] == (tenant, source_id) and item != key
                    ]:
                        self._dynamic_engines.pop(stale).dispose()
                    engine = engine_from_url(url)
                    self._dynamic_engines[key] = engine
                return engine
        try:
            return self._engines[source_id]
        except KeyError as exc:
            raise KeyError(f"unknown source {source_id}") from exc

    def prepare_analysis(self, bundle: CompiledBundle, query: SemanticQuery, tenant: str) -> str:
        from semaloom.adapters.analysis import prepare_analysis

        return prepare_analysis(bundle, query, tenant, self)

    def analysis_dimension_values(
        self, bundle: CompiledBundle, metric_id: str, field: str, tenant: str
    ) -> list[str | int | bool]:
        from semaloom.adapters.analysis import analysis_dimension_values

        return analysis_dimension_values(bundle, metric_id, field, tenant, self)

    def analysis_subjects(
        self, bundle: CompiledBundle, query: SemanticQuery, tenant: str
    ) -> list[tuple[str, str, str]]:
        from semaloom.adapters.analysis import analysis_subjects

        return analysis_subjects(bundle, query, tenant, self)

    def execute_analysis(self, bundle: CompiledBundle, plan: PlanRef, tenant: str) -> QueryResult:
        from semaloom.adapters.analysis import analysis_source, execute_analysis

        source = analysis_source(bundle, plan.query, tenant, self)
        try:
            with _read_transaction(self._engine(source, tenant)) as conn:
                conn.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
                return execute_analysis(
                    bundle,
                    plan,
                    tenant,
                    _AnalysisConnection(conn, source, tenant),
                    bind_provider=self,
                )
        except (SQLAlchemyError, KeyError) as exc:
            raise AnalysisError("PROVIDER_UNAVAILABLE") from exc

    def execute_select(
        self,
        source_id: str,
        tenant: str,
        statement: Any,
        params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        with _read_transaction(self._engine(source_id, tenant)) as conn:
            return [dict(row) for row in conn.execute(statement, params).mappings().all()]

    def close(self) -> None:
        for engine in {*self._engines.values(), *self._dynamic_engines.values()}:
            engine.dispose()
        self._dynamic_engines.clear()


def engine_from_url(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True, pool_size=4, max_overflow=0)


@contextmanager
def _read_transaction(engine: Engine) -> Iterator[Connection]:
    with engine.connect() as conn, conn.begin():
        conn.execute(text("SET TRANSACTION READ ONLY"))
        conn.execute(text("SET LOCAL statement_timeout = 5000"))
        yield conn


def _object_projection(mapping: MappingDef) -> dict[str, str]:
    projection: dict[str, str] = {}
    for field in ("grainColumns", "propertyColumns"):
        raw = mapping.physical.get(field)
        if not isinstance(raw, dict):
            continue
        for semantic, physical in raw.items():
            alias = require_ident(semantic, field=f"{field}.semantic")
            projection[alias] = require_ident(physical, field=f"{field}.{semantic}")
    return projection


def _identity_columns(mapping: MappingDef, identity_value: IdentityValue) -> dict[str, str]:
    if set(identity_value) != set(mapping.identity_fields):
        raise ValueError("identity does not match compiled mapping")
    grain = mapping.physical.get("grainColumns")
    if not isinstance(grain, dict):
        raise ValueError("grainColumns must be an object")
    columns = {
        semantic: require_ident(grain.get(semantic), field=f"identity.{semantic}")
        for semantic in mapping.identity_fields
    }
    if len(set(columns.values())) != len(columns):
        raise ValueError("identity keys must map to distinct physical columns")
    return columns


class _AnalysisConnection:
    """All reads for one semantic result share one read-only source snapshot."""

    def __init__(self, connection: Connection, source: str, tenant: str) -> None:
        self.connection, self.source, self.tenant = connection, source, tenant

    def execute_select(
        self, source_id: str, tenant: str, statement: Any, params: dict[str, Any]
    ) -> list[dict[str, Any]]:
        if (source_id, tenant) != (self.source, self.tenant):
            raise AnalysisError("CROSS_SOURCE_SQL")
        self.connection.execute(text("SAVEPOINT semaloom_stmt"))
        try:
            rows = [
                dict(row) for row in self.connection.execute(statement, params).mappings().all()
            ]
            self.connection.execute(text("RELEASE SAVEPOINT semaloom_stmt"))
            return rows
        except Exception:
            self.connection.execute(text("ROLLBACK TO SAVEPOINT semaloom_stmt"))
            raise
