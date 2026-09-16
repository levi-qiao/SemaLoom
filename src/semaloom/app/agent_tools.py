"""Transport-neutral read-only tool catalog for an AI host's HTTP dispatcher."""

from __future__ import annotations

from typing import Any

from semaloom.core.results import ObjectSearchRequest, PopulationRequest, QueryRequest


def read_tools(claim_schema: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "name": "analyze_population",
            "description": "Compute annual statistics for a declared Metric.population. "
            "Use mean/sum/min/max/count; comparisons: shareOfTotal, percentAboveMean, outperforms. "
            "Clarify ambiguous advantage wording; never calculate from a truncated search page. "
            "Missing exclusion requires consent; limit 50 objects, otherwise refine filters.",
            "method": "POST",
            "path": "/v0.1/analyze",
            "inputSchema": PopulationRequest.model_json_schema(by_alias=True),
        },
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
