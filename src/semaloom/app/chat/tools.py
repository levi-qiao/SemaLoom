"""Trusted, per-turn semantic tool gateway and evidence submission boundary."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, Field

from semaloom.app.agent_tools import read_tools
from semaloom.app.chat.intent import TurnIntent
from semaloom.app.chat.schema import model_schema
from semaloom.app.chat.summary import evidence_summary
from semaloom.app.http import ClaimBody, reject_forbidden
from semaloom.core.results import (
    MetricSelect,
    ObjectSearchRequest,
    ObjectSelect,
    QueryRequest,
)
from semaloom.core.semantic_query import SemanticQuery
from semaloom.core.wire import wire_config
from semaloom.runtime.auth import RequestActor
from semaloom.runtime.discovery import SemanticDiscovery
from semaloom.runtime.eval import EvaluationError, evaluate_claim_with_evidence
from semaloom.runtime.query import QueryService


class Answer(BaseModel):
    model_config = wire_config(frozen=False)
    kind: Literal["answer", "explanation", "clarification", "unsupported"]
    text: str = Field(min_length=1, max_length=6000)
    evidence_ids: list[str] = Field(max_length=12)


class SemanticTools:
    def __init__(self, query: QueryService, actor: RequestActor, user_message: str = "") -> None:
        self.query, self.actor = query, actor
        self.user_message = user_message
        self.evidence: dict[str, dict[str, Any]] = {}
        self.identities: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
        self.answer: dict[str, Any] | None = None
        self.pending: dict[str, Any] | None = None
        self.calls = 0

    @property
    def intent(self) -> TurnIntent:
        return TurnIntent.read(self.user_message, self.query.bundle)

    def overview(self) -> str:
        page = SemanticDiscovery(self.query.bundle).catalog(self.actor, limit=50)
        entries = [
            {
                key: document[key]
                for key in ("id", "kind", "label", "aliases", "objectType")
                if key in document
            }
            for document in page["definitions"]
        ]
        included: list[dict[str, Any]] = []
        for entry in entries:
            if len(json.dumps([*included, entry], ensure_ascii=False)) > 12000:
                break
            included.append(entry)
        return json.dumps(
            {
                "businessCatalog": included,
                "hasMore": page["hasMore"] or len(included) < len(entries),
                "serverTurnConstraints": self.intent.guidance(),
            },
            ensure_ascii=False,
        )

    def catalog(self) -> list[dict[str, Any]]:
        http_tools = [
            tool
            for tool in read_tools(ClaimBody.model_json_schema(by_alias=True))
            if tool["name"] != "analyze_population"
        ]
        query_schema = SemanticQuery.model_json_schema(by_alias=True)
        query_schema["properties"].pop("decisions", None)
        catalog = [
            *http_tools,
            {
                "name": "list_semantics",
                "description": "Browse the current authorized ontology: objects, metrics, links "
                "and rules. Use for open questions about what can be asked. Follow nextOffset "
                "for more. Definitions describe configured meanings, NOT actual available rows. "
                "Link and Metric documents include analysisCapabilities derived from approved "
                "mapping capabilities: pointLookup requires POINT_READ, keyedFind requires "
                "COLLECTION_READ, and collectionJoin requires a declared ONE link whose mappings "
                "advertise EQUI_JOIN.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "offset": {"type": "integer", "minimum": 0},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "prepare_semantic_query",
                "description": "Prepare then execute a composable SemanticQuery. "
                "When the server returns NEEDS_INPUT, stop and wait for an option id. "
                "Omit unspecified year/aggregation; do not invent SQL or groupBy "
                "unless the user asked for a breakdown.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "query": model_schema(query_schema),
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "present_answer",
                "description": "Finish this turn. Cite evidenceId values from tools in THIS turn. "
                "Use explanation with discovery evidence for definitions and suggested questions; "
                "use answer with observations for facts; clarification or unsupported otherwise. "
                "The server supplies factual cards. Never invent numbers or claim truth.",
                "inputSchema": Answer.model_json_schema(by_alias=True),
            },
        ]

        return [{**tool, "inputSchema": model_schema(tool["inputSchema"])} for tool in catalog]

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        if self.calls > 20:
            raise ValueError("TOOL_BUDGET_EXCEEDED")
        reject_forbidden(arguments)
        if name == "present_answer":
            value = Answer.model_validate(arguments)
            if any(key not in self.evidence for key in value.evidence_ids):
                raise ValueError("UNKNOWN_EVIDENCE_REFERENCE")
            if value.kind in {"answer", "explanation"} and not value.evidence_ids:
                raise ValueError("EVIDENCE_REQUIRED")
            selected = [self.evidence[key] for key in dict.fromkeys(value.evidence_ids)]
            if (
                value.kind == "clarification"
                and self.user_message
                and (
                    self.intent.metric_ids
                    or self.intent.candidates
                    or self.intent.clarify_comparison
                    or any(item["result"].get("population") for item in self.evidence.values())
                )
            ):
                # The model may request clarification, but the server owns its options.
                from semaloom.app.chat.presentation import without_physical_metadata

                return cast(
                    dict[str, Any],
                    without_physical_metadata(self._execute("prepare_semantic_query", {})),
                )
            if self.user_message:
                if (
                    self.intent.candidates or self.intent.clarify_comparison
                ) and value.kind != "clarification":
                    raise ValueError("CLARIFICATION_REQUIRED")
                if self.intent.comparison and value.kind in {"answer", "explanation"}:
                    raise ValueError("COMPARISON_EVIDENCE_REQUIRED")
                if self.intent.operation and value.kind in {"answer", "explanation"}:
                    raise ValueError("SEMANTIC_ANALYSIS_REQUIRED")
            definitions_only = bool(selected) and all(
                item["tool"] in {"list_semantics", "search_semantics", "describe_semantic"}
                for item in selected
            )
            if value.kind == "explanation" and not definitions_only:
                raise ValueError("DEFINITION_EVIDENCE_REQUIRED")
            if value.kind == "answer" and definitions_only:
                # Older hosts can submit discovery evidence as answer; never label it ENGINE.
                value = value.model_copy(update={"kind": "explanation"})
            if value.kind == "answer":
                value = value.model_copy(update={"text": evidence_summary(selected)})
            self.answer = {
                "kind": value.kind,
                "textOrigin": "ENGINE" if value.kind == "answer" else "AI",
                "text": value.text,
                "evidence": [self.evidence[key] for key in dict.fromkeys(value.evidence_ids)],
                "releaseDigest": self.query.bundle.digest,
            }
            return {"accepted": True, "releaseDigest": self.query.bundle.digest}
        if (
            self.user_message
            and (self.intent.candidates or self.intent.clarify_comparison)
            and name
            not in {
                "list_semantics",
                "search_semantics",
                "describe_semantic",
                "prepare_semantic_query",
            }
        ):
            raise ValueError("CLARIFICATION_REQUIRED")
        payload = self._execute(name, arguments)
        if payload.get("releaseDigest") != self.query.bundle.digest:
            raise ValueError("RELEASE_MISMATCH")
        # Bounded results remain complete. Never truncate and then claim absence.
        if len(json.dumps(payload, ensure_ascii=False)) > 60000:
            raise ValueError("RESULT_TOO_LARGE_REFINE_QUERY")
        key = f"e{len(self.evidence) + 1}"
        record = {"id": key, "tool": name, "result": payload}
        self.evidence[key] = record
        from semaloom.app.chat.presentation import without_physical_metadata

        return cast(dict[str, Any], without_physical_metadata({**payload, "evidenceId": key}))

    def _execute(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        discovery = SemanticDiscovery(self.query.bundle)
        if name == "list_semantics":
            if set(args) - {"offset", "limit"} or any(
                type(value) is not int for value in args.values()
            ):
                raise ValueError("INVALID_ARGUMENTS")
            return discovery.catalog(
                self.actor, offset=args.get("offset", 0), limit=args.get("limit", 20)
            )
        if name == "search_semantics":
            if set(args) - {"q", "limit"}:
                raise ValueError("INVALID_ARGUMENTS")
            return discovery.search(str(args["q"]), self.actor, limit=int(args.get("limit", 20)))
        if name == "describe_semantic":
            if set(args) != {"semanticId"}:
                raise ValueError("INVALID_ARGUMENTS")
            return discovery.describe(str(args["semanticId"]), self.actor)
        if name == "find_objects":
            request = ObjectSearchRequest.model_validate(args)
            result = self.query.find_objects(request, self.actor)
            for obj in result["objects"]:
                identity = {str(key): str(value) for key, value in obj["identity"].items()}
                self.identities.add((request.object_type, _identity_tuple(identity)))
            return result
        if name == "prepare_semantic_query":
            from semaloom.app.chat.choices import prepare_turn, query_from_intent
            from semaloom.core.semantic_query import SemanticQuery

            if set(args) - {"question", "query"}:
                raise ValueError("INVALID_ARGUMENTS")
            message = self.user_message or str(args.get("question") or "")
            query = None
            if args.get("query"):
                query = SemanticQuery.model_validate(args["query"])
                if query.decisions:
                    raise ValueError("SERVER_OWNED_DECISIONS")
                if (
                    query.comparison
                    and query.comparison.subject
                    and query.comparison.subject.identity
                ):
                    metric = next(
                        (m for m in self.query.bundle.metrics if m.id == query.comparison.metric),
                        None,
                    )
                    if metric is None:
                        raise ValueError("UNKNOWN_METRIC")
                    self._identity(metric.object_type, query.comparison.subject.identity)
            elif self.user_message and not self.intent.candidates:
                query = query_from_intent(self.intent, self.query.bundle)
            payload = prepare_turn(self.query, self.actor, message, query)
            if payload.get("answerReady"):
                kind = "unsupported" if payload.get("status") == "UNSUPPORTED" else "answer"
                self.answer = {
                    "kind": kind,
                    "textOrigin": "ENGINE",
                    "text": payload.get("text")
                    or (
                        "当前分析能力暂不支持该请求。"
                        if kind == "unsupported"
                        else "已按发布口径完成计算。"
                    ),
                    "evidence": [
                        {
                            "id": "e1",
                            "tool": "prepare_semantic_query",
                            "result": payload.get("result")
                            or {
                                "status": payload.get("status"),
                                "errorCode": payload.get("errorCode"),
                                "capability": payload.get("capability"),
                            },
                        }
                    ],
                    "releaseDigest": self.query.bundle.digest,
                    "confidence": payload.get("confidence"),
                    "followUps": payload.get("followUps") or [],
                    "assumptions": payload.get("assumptions") or [],
                }
            if payload.get("waiting"):
                self.pending = payload
            return payload
        if name == "submit_choice":
            raise ValueError("SUBMIT_VIA_CHAT_CHOICES")
        if name == "semantic_query":
            request_query = QueryRequest.model_validate(args)
            for selection in request_query.select:
                if isinstance(selection, ObjectSelect):
                    self._identity(selection.object_type, selection.identity)
                else:
                    self._metric_identity(selection)
            result = dict(
                self.query.execute(request_query, self.actor).model_dump(mode="json", by_alias=True)
            )
            result["checks"] = self._covered_checks(request_query)
            return result
        if name == "evaluate_claim":
            body = ClaimBody.model_validate(args)
            rule = next((r for r in self.query.bundle.rules if r.claim == body.claim_id), None)
            if rule is None:
                raise ValueError("UNKNOWN_CLAIM")
            for item in rule.inputs:
                if item.metric:
                    self._metric_identity(MetricSelect(metric=item.metric, bindings=body.bindings))
                elif item.object_type:
                    self._identity_from_bindings(item.object_type, body.bindings)
            claim, observations, diagnostics, digest, activities = evaluate_claim_with_evidence(
                self.query.bundle,
                self.query,
                self.actor,
                claim_id=body.claim_id,
                bindings=body.bindings,
                period_from=body.period_from,
                period_to=body.period_to,
                dimensions=body.dimensions,
            )
            return {
                "claim": claim.model_dump(mode="json", by_alias=True),
                "observations": [o.model_dump(mode="json", by_alias=True) for o in observations],
                "diagnostics": [d.model_dump(mode="json") for d in diagnostics],
                "sourceActivities": [a.model_dump(mode="json", by_alias=True) for a in activities],
                "releaseDigest": digest,
            }
        raise ValueError("TOOL_NOT_ALLOWED")

    def _covered_checks(self, request: QueryRequest) -> list[dict[str, Any]]:
        """Run declared numeric Claims whose inputs are covered by this query's metric group.

        This hook never infers a formula from prose. Policy selection and execution remain
        in the existing evaluator; unsupported policy scope is an explicit failed check.
        """
        groups: dict[str, tuple[dict[str, str | int], set[str]]] = {}
        definitions = {m.id: m for m in self.query.bundle.metrics}
        for item in request.select:
            if not isinstance(item, MetricSelect):
                continue
            bindings = dict(item.bindings)
            bindings.pop("perspective", None)
            key = json.dumps(bindings, sort_keys=True)
            _, covered = groups.setdefault(key, (bindings, set()))
            pending = [item.metric]
            while pending:
                metric_id = pending.pop()
                if metric_id in covered:
                    continue
                covered.add(metric_id)
                metric = definitions.get(metric_id)
                if metric:
                    pending.extend(metric.derived_from)
        candidates = [
            (rule, bindings)
            for bindings, covered in groups.values()
            for rule in self.query.bundle.rules
            if rule.claim and rule.inputs and all(i.metric in covered for i in rule.inputs)
        ]
        if len(candidates) > 4:
            raise ValueError("TOO_MANY_RULE_CHECKS_REFINE_QUERY")
        checks = []
        for rule, bindings in candidates:
            try:
                checks.append(
                    self._execute(
                        "evaluate_claim",
                        {
                            "claimId": rule.claim,
                            "bindings": bindings,
                            "periodFrom": request.context.business_period["from"],
                            "periodTo": request.context.business_period["to"],
                            "dimensions": request.context.scope,
                        },
                    )
                )
            except EvaluationError as exc:
                checks.append(
                    {
                        "claimId": rule.claim,
                        "error": exc.code,
                        "releaseDigest": self.query.bundle.digest,
                    }
                )
        return checks

    def _metric_identity(self, selection: MetricSelect) -> None:
        metric = next((m for m in self.query.bundle.metrics if m.id == selection.metric), None)
        if metric is None:
            raise ValueError("UNKNOWN_METRIC")
        self._identity_from_bindings(metric.object_type, selection.bindings)

    def _identity_from_bindings(self, object_type: str, bindings: dict[str, Any]) -> None:
        obj = next((o for o in self.query.bundle.object_types if o.id == object_type), None)
        if obj is None or not obj.identity_keys or not set(obj.identity_keys) <= set(bindings):
            raise ValueError("UNSUPPORTED_IDENTITY")
        self._identity(object_type, {key: bindings[key] for key in obj.identity_keys})

    def _identity(self, object_type: str, bindings: dict[str, Any]) -> None:
        obj = next((o for o in self.query.bundle.object_types if o.id == object_type), None)
        if obj is None or not obj.identity_keys or set(bindings) != set(obj.identity_keys):
            raise ValueError("UNSUPPORTED_IDENTITY")
        identity = {key: str(bindings[key]) for key in obj.identity_keys}
        if (object_type, _identity_tuple(identity)) not in self.identities:
            raise ValueError("RESOLVE_IDENTITY_WITH_FIND_OBJECTS_FIRST")


def _identity_tuple(identity: dict[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted(identity.items()))


SYSTEM_PROMPT = Path(__file__).with_name("system_prompt.txt").read_text()
