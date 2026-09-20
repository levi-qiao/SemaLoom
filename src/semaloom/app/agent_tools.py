"""Transport-neutral read-only tool catalog for an AI host's HTTP dispatcher."""

from __future__ import annotations

from typing import Any

from semaloom.core.results import ObjectSearchRequest, QueryRequest
from semaloom.core.semantic_query import PlanRef, SemanticQuery


def read_tools(claim_schema: dict[str, Any]) -> list[dict[str, Any]]:
    query_schema = SemanticQuery.model_json_schema(by_alias=True)
    query_schema["properties"].pop("decisions", None)
    return [
        {
            "name": "search_semantics",
            "description": (
                "Find business definitions by ID/label/description; select a perspective before "
                "querying. "
            ),
            "method": "GET",
            "path": "/v0.1/search",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "q": {"type": "string", "minLength": 1, "maxLength": 200},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                "required": ["q"],
                "additionalProperties": False,
            },
        },
        {
            "name": "describe_semantic",
            "description": (
                "Read a business definition including identity, units, grain and caveats. "
            ),
            "method": "GET",
            "path": "/v0.1/describe",
            "inputSchema": {
                "type": "object",
                "properties": {"semanticId": {"type": "string"}},
                "required": ["semanticId"],
                "additionalProperties": False,
            },
        },
        {
            "name": "find_objects",
            "description": (
                "Find actual business instances using exact typed property filters; never guess "
                "an internal ID. hasMore means incomplete results, not a complete company "
                "population. "
            ),
            "method": "POST",
            "path": "/v0.1/objects/search",
            "inputSchema": ObjectSearchRequest.model_json_schema(by_alias=True),
        },
        {
            "name": "semantic_query",
            "description": (
                "Read declared objects or metrics using resolved identities; monetary values "
                "are exact strings with units. Missing/unavailable values are not zero. "
            ),
            "method": "POST",
            "path": "/v0.1/query",
            "inputSchema": QueryRequest.model_json_schema(by_alias=True),
        },
        {
            "name": "semantic_prepare",
            "description": (
                "Prepare a composable collection analysis. Metrics, filters and aggregations "
                "are semantic identifiers only. Omit year/aggregation to receive a choice. "
                "Evidence detail pages are capped at 50 rows per metric. "
            ),
            "method": "POST",
            "path": "/v0.1/semantic/prepare",
            "inputSchema": query_schema,
        },
        {
            "name": "semantic_execute",
            "description": "Execute a plan returned by semantic_prepare.",
            "method": "POST",
            "path": "/v0.1/semantic/execute",
            "inputSchema": PlanRef.model_json_schema(by_alias=True),
        },
        {
            "name": "evaluate_claim",
            "description": (
                "Execute a named deterministic business rule. TRUE means only that rule holds "
                "for its inputs; UNKNOWN is not FALSE. Report diagnostics, source review state "
                "and sample-selection caveats. "
            ),
            "method": "POST",
            "path": "/v0.1/claims/evaluate",
            "inputSchema": claim_schema,
        },
    ]
