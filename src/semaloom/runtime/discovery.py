"""Business-only discovery over one pinned semantic release."""

from __future__ import annotations

import unicodedata
from typing import Any

from semaloom.core.bundle import CompiledBundle
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
            doc.model_dump(mode="json", by_alias=True, exclude_none=True)
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


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()
