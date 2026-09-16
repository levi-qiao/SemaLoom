"""Business-only discovery over one pinned semantic release."""

from __future__ import annotations

import unicodedata
from typing import Any

from semaloom.core.bundle import CompiledBundle
from semaloom.core.model import MappingCapability
from semaloom.runtime.auth import RequestActor, authorize_query


class SemanticDiscovery:
    def __init__(self, bundle: CompiledBundle) -> None:
        self.bundle = bundle

    def _documents(self, actor: RequestActor) -> list[dict[str, Any]]:
        if not authorize_query(actor, "discover").allowed:
            raise PermissionError("FORBIDDEN")
        # An explicit business collection allowlist: never expose physical bindings,
        # connection settings or access policy documents through agent discovery.
        return [
            _with_analysis_capabilities(
                doc.model_dump(mode="json", by_alias=True, exclude_none=True),
                self.bundle,
            )
            for collection in (
                self.bundle.object_types,
                self.bundle.metrics,
                self.bundle.links,
                self.bundle.rules,
                self.bundle.policies,
                self.bundle.actions,
            )
            for doc in collection
        ]

    def describe(self, semantic_id: str, actor: RequestActor) -> dict[str, Any]:
        for document in self._documents(actor):
            if document["id"] == semantic_id:
                return {**document, "releaseDigest": self.bundle.digest}
        raise KeyError(semantic_id)

    def catalog(self, actor: RequestActor, *, offset: int = 0, limit: int = 20) -> dict[str, Any]:
        """Enumerate declared meanings, without claiming source availability or row counts."""
        if offset < 0 or not 1 <= limit <= 50:
            raise ValueError("INVALID_CATALOG_PAGE")
        documents = sorted(self._documents(actor), key=lambda document: document["id"])
        end = offset + limit
        return {
            "definitions": documents[offset:end],
            "offset": offset,
            "hasMore": end < len(documents),
            "nextOffset": end if end < len(documents) else None,
            "scope": "DECLARED_MODEL_NOT_SOURCE_OBSERVATIONS",
            "releaseDigest": self.bundle.digest,
        }

    def search(self, query: str, actor: RequestActor, *, limit: int = 20) -> dict[str, Any]:
        if not 1 <= limit <= 50 or not query.strip() or len(query) > 200:
            raise ValueError("INVALID_SEARCH")
        tokens = _normalize(query).split()
        matches = []
        for document in self._documents(actor):
            searchable = _normalize(
                " ".join(
                    str(document.get(k, "")) for k in ("id", "label", "aliases", "description")
                )
            )
            if all(token in searchable for token in tokens):
                matches.append(document)
        matches.sort(key=lambda doc: (doc["id"] != query.strip(), doc["id"]))
        return {
            "candidates": matches[:limit],
            "requiresSelection": len(matches) > 1,
            "hasMore": len(matches) > limit,
            "releaseDigest": self.bundle.digest,
        }


def _object_has_capability(
    bundle: CompiledBundle, object_type_id: str, capability: MappingCapability
) -> bool:
    return any(
        item.target == object_type_id and capability in item.capabilities
        for item in bundle.mappings
    )


def _link_collection_join(
    bundle: CompiledBundle, source: str, target: str, cardinality: str
) -> bool:
    return (
        cardinality == "ONE"
        and _object_has_capability(bundle, source, "EQUI_JOIN")
        and _object_has_capability(bundle, target, "EQUI_JOIN")
    )


def _with_analysis_capabilities(document: dict[str, Any], bundle: CompiledBundle) -> dict[str, Any]:
    """Project the current collection-analysis boundary onto discovery documents."""
    kind = document.get("kind")
    if kind == "Link":
        source = str(document.get("source") or "")
        target = str(document.get("target") or "")
        return {
            **document,
            "analysisCapabilities": {
                "pointLookup": _object_has_capability(bundle, source, "POINT_READ")
                and _object_has_capability(bundle, target, "POINT_READ"),
                "keyedFind": _object_has_capability(bundle, target, "COLLECTION_READ"),
                "collectionJoin": _link_collection_join(
                    bundle,
                    source,
                    target,
                    str(document.get("cardinality") or ""),
                ),
            },
        }
    if kind == "Metric":
        object_type = str(document.get("objectType") or "")
        return {
            **document,
            "analysisCapabilities": {
                "sameTableCollection": document.get("population") is not None
                and _object_has_capability(bundle, object_type, "COLLECTION_READ"),
                "collectionJoin": any(
                    _link_collection_join(bundle, link.source, link.target, link.cardinality)
                    for link in bundle.links
                    if link.source == object_type
                ),
            },
        }
    return document


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()
