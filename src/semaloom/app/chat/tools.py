"""Trusted, per-turn semantic tool gateway and evidence submission boundary."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, Field

from semaloom.app.agent_tools import read_tools
from semaloom.app.chat.i18n import localize_question, normalize_locale, text
from semaloom.app.chat.intent import TurnIntent
from semaloom.app.chat.presentation import ViewSelection
from semaloom.app.chat.schema import model_schema
from semaloom.app.chat.summary import evidence_summary
from semaloom.app.http import ClaimBody, reject_forbidden
from semaloom.core.results import (
    MetricSelect,
    ObjectSearchRequest,
    ObjectSelect,
    QueryRequest,
)
from semaloom.core.semantic_query import (
    ChoiceOption,
    ChoiceQuestion,
    SemanticChoice,
    SemanticQuery,
    abort_option,
    field_constrained,
    with_choice_exits,
)
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
    views: list[ViewSelection] = Field(default_factory=list, max_length=12)


class SemanticTools:
    def __init__(
        self,
        query: QueryService,
        actor: RequestActor,
        user_message: str = "",
        confirmed_query: dict[str, Any] | None = None,
        locale: str = "zh-CN",
    ) -> None:
        self.query, self.actor = query, actor
        self.user_message = user_message
        self.locale = normalize_locale(locale)
        self.confirmed_query = (
            SemanticQuery.model_validate(confirmed_query) if confirmed_query else None
        )
        self.evidence: dict[str, dict[str, Any]] = {}
        self.identities: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
        self.answer: dict[str, Any] | None = None
        self.pending: dict[str, Any] | None = None
        # A broad object search is a scope-discovery step, never a deliverable.
        # Once this flag is set the model cannot bypass the server-owned card by
        # submitting a later answer in the same turn.
        self.object_scope_required = False
        self.object_scope_type: str | None = None
        self.calls = 0

    @property
    def intent(self) -> TurnIntent:
        return TurnIntent.read(self.user_message, self.query.bundle)

    def overview(self) -> str:
        page = SemanticDiscovery(self.query.bundle).catalog(self.actor, limit=50)
        entries = [
            {
                key: document[key]
                for key in (
                    "id",
                    "kind",
                    "label",
                    "aliases",
                    "objectType",
                    "rule",
                    "dimensions",
                )
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
            if tool["name"] not in {"semantic_prepare", "semantic_execute"}
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
                "Omit unspecified scope properties and aggregation; do not invent SQL or groupBy "
                "unless the user asked for a breakdown. groupBy ids must be declared "
                "ObjectType property ids (qualified as ObjectType.property when needed), "
                "never Link ids.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "query": model_schema(query_schema),
                        "view": {
                            "type": "string",
                            "enum": ["auto", "none", "table", "bar", "line", "relationships"],
                        },
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "present_answer",
                "description": "Finish this turn. Cite evidenceId values from tools in THIS turn. "
                "Use explanation with discovery evidence for definitions and suggested questions; "
                "use answer with observations for facts; clarification or unsupported otherwise. "
                "The server supplies factual cards. Never invent numbers or claim truth. "
                "Optionally select views by evidenceId: table for precise lookup, bar for "
                "category comparison, line for a time series, none when prose suffices. "
                "relationships for declared ObjectType/Link definitions. "
                "Only compatible views will be used; omit views for automatic presentation.",
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
            if any(view.evidence_id not in value.evidence_ids for view in value.views):
                raise ValueError("UNKNOWN_PRESENTATION_REFERENCE")
            if value.kind in {"answer", "explanation"} and not value.evidence_ids:
                raise ValueError("EVIDENCE_REQUIRED")
            selected = [self.evidence[key] for key in dict.fromkeys(value.evidence_ids)]
            if self.object_scope_required:
                # Do not let a model turn a broad object listing into an answer,
                # even when it has already received the search result.  The user
                # must provide a business scope from the active ontology first.
                return self._object_scope_pending()
            if (
                value.kind == "clarification"
                and self.user_message
                and (
                    self.intent.metric_ids
                    or self.intent.candidates
                    or self.intent.clarify_formula
                    or self.intent.clarify_grouping
                    or any(item["result"].get("population") for item in self.evidence.values())
                )
            ):
                # The model may request clarification, but the server owns its options.
                from semaloom.app.chat.presentation import without_physical_metadata

                return cast(
                    dict[str, Any],
                    without_physical_metadata(self._execute("prepare_semantic_query", {})),
                )
            if value.kind == "clarification" and self.user_message:
                question = ChoiceQuestion(
                    question_id="q-context-" + uuid.uuid4().hex,
                    revision=1,
                    slot="context",
                    prompt=value.text,
                    reason=text(self.locale, "clarification.reason"),
                    options=with_choice_exits([]),
                )
                self.pending = {
                    "status": "NEEDS_INPUT",
                    "waiting": True,
                    "question": question.model_dump(mode="json", by_alias=True),
                    "query_state": {"mode": "clarification"},
                    "originalQuestion": self.user_message,
                    "releaseDigest": self.query.bundle.digest,
                }
                return self.pending
            if self.user_message:
                if (
                    self.intent.candidates
                    or self.intent.clarify_formula
                    or self.intent.clarify_grouping
                ) and value.kind != "clarification":
                    raise ValueError("CLARIFICATION_REQUIRED")
                if self.intent.formula_shape and value.kind in {"answer", "explanation"}:
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
                value = value.model_copy(
                    update={
                        "text": evidence_summary(
                            selected, bundle=self.query.bundle, locale=self.locale
                        )
                    }
                )
            follow_ups: list[dict[str, str]] = []
            seen_chips: set[str] = set()
            for item in selected:
                res = item.get("result") or {}
                for check in res.get("checks") or []:
                    if check.get("error") == "NO_APPLICABLE_POLICY":
                        sample_dims = check.get("sampleDimensions") or {}
                        claim_id = check.get("claimId")
                        if "jurisdiction" in sample_dims and claim_id:
                            val = sample_dims["jurisdiction"]
                            chip_label = f"按属地 {val} 重新核验"
                            if chip_label not in seen_chips:
                                seen_chips.add(chip_label)
                                follow_ups.append(
                                    {
                                        "label": chip_label,
                                        "message": f"按属地 {val} 重新核验 {claim_id} 规则",
                                    }
                                )
            self.answer = {
                "kind": value.kind,
                "textOrigin": "ENGINE" if value.kind == "answer" else "AI",
                "text": value.text,
                "evidence": [self.evidence[key] for key in dict.fromkeys(value.evidence_ids)],
                "releaseDigest": self.query.bundle.digest,
                "followUps": follow_ups,
                "views": [view.model_dump(by_alias=True) for view in value.views],
                "originalQuestion": self.user_message,
            }
            return {"accepted": True, "releaseDigest": self.query.bundle.digest}
        if (
            self.user_message
            and (
                self.intent.candidates
                or self.intent.clarify_formula
                or self.intent.clarify_grouping
            )
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

        if name == "find_objects":
            request = ObjectSearchRequest.model_validate(arguments)
            if _requires_object_scope(request, payload):
                self.object_scope_required = True
                self.object_scope_type = request.object_type
                self._object_scope_pending()
                # Keep raw records in the server-side evidence envelope only. The
                # model receives the count and next step, never business IDs it
                # could accidentally repeat in human-facing prose.
                return {
                    "objectType": payload.get("objectType", request.object_type),
                    "objectCount": len(payload.get("objects") or []),
                    "hasMore": bool(payload.get("hasMore")),
                    "requiresSelection": True,
                    "drilldownRequired": True,
                    "message": text(self.locale, "objectScope.modelMessage"),
                    "releaseDigest": payload["releaseDigest"],
                    "evidenceId": key,
                }
        return cast(dict[str, Any], without_physical_metadata({**payload, "evidenceId": key}))

    def _object_scope_pending(self) -> dict[str, Any]:
        if (
            self.pending is not None
            and self.pending.get("query_state", {}).get("mode") == "object_scope"
        ):
            return self.pending
        obj = next(
            (item for item in self.query.bundle.object_types if item.id == self.object_scope_type),
            None,
        )
        object_label = (obj.label or obj.id) if obj is not None else "Object"
        property_labels = self._object_scope_property_labels()
        properties = (
            "、".join(property_labels) if self.locale == "zh-CN" else ", ".join(property_labels)
        )
        if not properties:
            properties = text(self.locale, "objectScope.propertiesFallback")
        question = ChoiceQuestion(
            question_id="q-object-scope-" + uuid.uuid4().hex,
            revision=1,
            slot="objectScope",
            prompt=text(self.locale, "objectScope.prompt", object=object_label),
            reason=text(self.locale, "objectScope.reason", properties=properties),
            options=(
                ChoiceOption(
                    id="opt_object_scope_input",
                    label=text(self.locale, "objectScope.option"),
                    explanation=text(
                        self.locale,
                        "objectScope.optionExplanation",
                        properties=properties,
                    ),
                    choice=SemanticChoice(kind="OTHER", id="object_scope"),
                ),
                abort_option(
                    label=text(self.locale, "objectScope.abort"),
                    explanation=text(self.locale, "objectScope.abortExplanation"),
                ),
            ),
        )
        self.pending = {
            "status": "NEEDS_INPUT",
            "waiting": True,
            "question": question.model_dump(mode="json", by_alias=True),
            "query_state": {"mode": "object_scope"},
            "originalQuestion": self.user_message,
            "releaseDigest": self.query.bundle.digest,
        }
        return self.pending

    def _object_scope_property_labels(self) -> list[str]:
        obj = next(
            (item for item in self.query.bundle.object_types if item.id == self.object_scope_type),
            None,
        )
        if obj is None:
            return []
        identity_fields = set(obj.identity_keys)
        for link in self.query.bundle.links:
            if link.source == obj.id:
                identity_fields.update(pair.source for pair in link.identity)
        scope_properties = set(obj.population.scope_properties) if obj.population else set()
        candidates = [prop for prop in obj.properties if prop.id not in identity_fields]
        candidates.sort(
            key=lambda prop: (
                0 if prop.id in scope_properties else 1,
                0 if prop.values else 1,
                0 if prop.label else 1,
                prop.id,
            )
        )
        return [prop.label or prop.id for prop in candidates[:4]]

    def _without_unconfirmed_defaults(self, query: SemanticQuery) -> SemanticQuery:
        intent = self.intent
        previous = self.confirmed_query
        same_metrics = previous is not None and {ref.id for ref in previous.metrics} == {
            ref.id for ref in query.metrics
        }
        if not intent.role_constraints and not intent.grouping_role:
            for ref in query.metrics:
                metric = next((m for m in self.query.bundle.metrics if m.id == ref.id), None)
                if metric and metric.population:
                    from semaloom.core.semantic_query import equality_value

                    for field in metric.population.scope_properties:
                        if not field_constrained(query.filters, field):
                            continue
                        if (
                            not same_metrics
                            or previous is None
                            or equality_value(previous.filters, field)
                            != equality_value(query.filters, field)
                            or equality_value(query.filters, field) is None
                        ):
                            raise ValueError("UNCONFIRMED_SCOPE_OMIT_FILTER_TO_ASK_USER")
        if intent.operation is None and not intent.formula_shape:
            confirmed = (
                {ref.id: ref.aggregation for ref in previous.metrics}
                if same_metrics and previous
                else {}
            )
            return query.model_copy(
                update={
                    "metrics": tuple(
                        ref.model_copy(update={"aggregation": confirmed.get(ref.id)})
                        for ref in query.metrics
                    )
                }
            )
        return query

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

            if set(args) - {"question", "query", "view"}:
                raise ValueError("INVALID_ARGUMENTS")
            message = self.user_message or str(args.get("question") or "")
            view_selection = ViewSelection(evidence_id="e1", view=args.get("view", "auto"))
            query = None
            if args.get("query"):
                query = SemanticQuery.model_validate(args["query"])
                if query.decisions:
                    raise ValueError("SERVER_OWNED_DECISIONS")
                _validate_query_shape(self.query.bundle, query)
                # Model-supplied defaults are not user confirmation. Preserve explicit
                # filters, but do not allow invented scope or aggregation to skip cards.
                if self.user_message:
                    query = self._without_unconfirmed_defaults(query)
                if query.formula and query.formula.subject and query.formula.subject.identity:
                    from semaloom.core.semantic_query import formula_metric_ids

                    metric_id = next(iter(formula_metric_ids(query.formula)), None)
                    metric = next(
                        (m for m in self.query.bundle.metrics if m.id == metric_id),
                        None,
                    )
                    if metric is None:
                        raise ValueError("UNKNOWN_METRIC")
                    self._identity(metric.object_type, query.formula.subject.identity)
            elif self.user_message and not self.intent.candidates:
                query = query_from_intent(self.intent, self.query.bundle)
            payload = prepare_turn(self.query, self.actor, message, query, locale=self.locale)
            payload["question"] = localize_question(payload.get("question"), self.locale)
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
                    "followUps": payload.get("followUps") or [],
                    "assumptions": payload.get("assumptions") or [],
                    "query": payload.get("query"),
                    "views": [view_selection.model_dump(by_alias=True)],
                    "originalQuestion": message,
                }
            if payload.get("waiting"):
                payload["query_state"] = {
                    "query": payload.get("query"),
                    "view": view_selection.view,
                    "locale": self.locale,
                }
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
                required_dims: set[str] = set()
                sample_dims: dict[str, str] = {}
                rule_policies = [p for p in self.query.bundle.policies if p.rule == rule.id]
                for p in rule_policies:
                    required_dims.update(p.dimensions.keys())
                    sample_dims.update(p.dimensions)
                checks.append(
                    {
                        "claimId": rule.claim,
                        "ruleId": rule.id,
                        "error": exc.code,
                        "requiredDimensions": sorted(required_dims),
                        "sampleDimensions": sample_dims,
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


def _validate_query_shape(bundle: Any, query: SemanticQuery) -> None:
    """Reject model-only shape mistakes before a user choice card is issued.

    A Link is a traversal declaration, not a groupable property. Keeping this
    check at the chat gateway gives the model a repairable, typed tool error and
    keeps the compiler/runtime responsible for the actual execution semantics.
    """
    property_ids = {prop.id for obj in bundle.object_types for prop in obj.properties}
    property_ids.update(key for obj in bundle.object_types for key in obj.identity_keys)
    qualified_property_ids = {
        f"{obj.id}.{prop.id}" for obj in bundle.object_types for prop in obj.properties
    }
    qualified_property_ids.update(
        f"{obj.id}.{key}" for obj in bundle.object_types for key in obj.identity_keys
    )
    link_ids = {link.id for link in bundle.links}
    for item in query.group_by:
        if item.id in link_ids:
            raise ValueError("GROUP_BY_REQUIRES_PROPERTY_NOT_LINK_ID")
        if item.id not in property_ids and item.id not in qualified_property_ids:
            raise ValueError("INVALID_GROUP_BY_FIELD")


def _identity_tuple(identity: dict[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted(identity.items()))


def _requires_object_scope(request: ObjectSearchRequest, result: dict[str, Any]) -> bool:
    """Return whether an object search is still a discovery set.

    A point lookup is safe to render after an exact identity or a sufficiently
    selective business filter.  Empty filters, a provider page, or multiple
    matches are a scope-selection step and must go back to the user as a card.
    """

    objects = result.get("objects") or []
    return (
        not request.filters
        or bool(result.get("hasMore"))
        or bool(result.get("requiresSelection"))
        or len(objects) > 1
    )


SYSTEM_PROMPT = Path(__file__).with_name("system_prompt.txt").read_text()
