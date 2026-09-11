"""PostgreSQL read adapter. Identifiers come from approved mappings only."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from semaloom.core.model import MappingDef
from semaloom.core.results import Observation

IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def require_ident(value: object, *, field: str) -> str:
    if not isinstance(value, str) or IDENT_RE.fullmatch(value) is None:
        raise ValueError(f"illegal identifier for {field}")
    return value


class PostgresReadProvider:
    def __init__(self, engines: dict[str, Engine]) -> None:
        self._engines = engines

    def fetch_metric(
        self,
        mapping: MappingDef,
        *,
        tenant: str,
        identity_value: str,
        extra_filters: dict[str, str] | None = None,
    ) -> Observation:
        physical = mapping.physical
        observed = datetime.now(UTC).isoformat()
        try:
            engine = self._engine(mapping.source_id)
            table = require_ident(physical.get("table"), field="table")
            identity_col = require_ident(physical.get("identityColumn"), field="identityColumn")
            value_col = require_ident(physical.get("valueColumn"), field="valueColumn")
            params: dict[str, Any] = {"tenant": tenant, "identity": identity_value}
            clauses = [f"{identity_col} = :identity", "tenant_id = :tenant"]
            filters = physical.get("filters")
            if isinstance(filters, dict):
                for key, value in filters.items():
                    column = require_ident(
                        key if key != "metric" else "metric", field=f"filter.{key}"
                    )
                    pname = f"f_{column}"
                    clauses.append(f"{column} = :{pname}")
                    params[pname] = value
            if extra_filters:
                for key, value in extra_filters.items():
                    column = require_ident(key, field=f"binding.{key}")
                    pname = f"b_{column}"
                    clauses.append(f"{column} = :{pname}")
                    params[pname] = value
            sql = text(
                f"SELECT {value_col} AS value FROM {table} WHERE {' AND '.join(clauses)} LIMIT 2"
            )
            with engine.connect() as conn:
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
        identity_value: str,
    ) -> dict[str, Any] | None:
        try:
            engine = self._engine(mapping.source_id)
            table = require_ident(mapping.physical.get("table"), field="table")
            identity_col = require_ident(
                mapping.physical.get("identityColumn"), field="identityColumn"
            )
            sql = text(
                f"SELECT * FROM {table} WHERE {identity_col} = :identity "
                "AND tenant_id = :tenant LIMIT 2"
            )
            with engine.connect() as conn:
                rows = (
                    conn.execute(sql, {"identity": identity_value, "tenant": tenant})
                    .mappings()
                    .all()
                )
        except (SQLAlchemyError, KeyError, ValueError):
            return None
        if len(rows) != 1:
            return None
        return dict(rows[0])

    def fetch_keys(
        self,
        mapping: MappingDef,
        *,
        tenant: str,
        identity_value: str,
        key_column: str,
    ) -> list[str]:
        row = self.fetch_object(mapping, tenant=tenant, identity_value=identity_value)
        if row is None:
            return []
        column = require_ident(key_column, field="key_column")
        value = row.get(column) or row.get(key_column)
        if value is None:
            return []
        return [str(value)]

    def _engine(self, source_id: str) -> Engine:
        try:
            return self._engines[source_id]
        except KeyError as exc:
            raise KeyError(f"unknown source {source_id}") from exc


def engine_from_url(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True, pool_size=4, max_overflow=0)
