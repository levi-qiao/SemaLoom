"""Safe YAML 1.2 loading. Rejects duplicate keys, unsafe tags, and deep trees."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

MAX_DEPTH = 32
MAX_NODES = 4000


class DuplicateKeyError(ValueError):
    pass


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_mapping(
    loader: yaml.SafeLoader, node: yaml.nodes.MappingNode, deep: bool = False
) -> dict[str, Any]:
    mapping: dict[str, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise DuplicateKeyError(f"duplicate key {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


def _count_and_depth(value: object, *, depth: int = 1) -> tuple[int, int]:
    if depth > MAX_DEPTH:
        raise ValueError(f"YAML nesting exceeds {MAX_DEPTH}")
    if not isinstance(value, dict | list):
        return 1, depth
    nodes = 1
    max_depth = depth
    children = value.values() if isinstance(value, dict) else value
    for child in children:
        child_nodes, child_depth = _count_and_depth(child, depth=depth + 1)
        nodes += child_nodes
        max_depth = max(max_depth, child_depth)
        if nodes > MAX_NODES:
            raise ValueError(f"YAML node count exceeds {MAX_NODES}")
    return nodes, max_depth


def load_yaml_file(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    try:
        data = yaml.load(text, Loader=UniqueKeyLoader)
    except DuplicateKeyError as exc:
        raise ValueError(f"{path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"{path}: invalid YAML: {exc}") from exc
    _count_and_depth(data)
    return data


def load_yaml_documents(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    documents: list[tuple[Path, dict[str, Any]]] = []
    files = sorted(root.rglob("*.yaml")) + sorted(root.rglob("*.yml"))
    seen: set[Path] = set()
    for path in files:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        data = load_yaml_file(path)
        if data is None:
            continue
        if isinstance(data, list):
            for index, item in enumerate(data):
                if not isinstance(item, dict):
                    raise ValueError(f"{path}[{index}]: document must be a mapping")
                documents.append((path, item))
            continue
        if not isinstance(data, dict):
            raise ValueError(f"{path}: document must be a mapping")
        documents.append((path, data))
    return documents
