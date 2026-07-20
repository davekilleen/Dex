"""Bounded YAML authority that rejects duplicate keys and graph features."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

DEFAULT_MAX_YAML_BYTES = 1024 * 1024


class StrictYamlLoader(yaml.SafeLoader):
    """Safe loader with a closed, tree-only mapping model."""


def _construct_unique_mapping(
    loader: StrictYamlLoader,
    node: yaml.nodes.MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    result: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in result
        except TypeError as error:
            raise ValueError("YAML mapping keys must be scalar") from error
        if duplicate:
            raise ValueError("YAML contains a duplicate key")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


StrictYamlLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def load_yaml_bytes(raw: bytes, *, max_bytes: int = DEFAULT_MAX_YAML_BYTES) -> Any:
    """Load one bounded UTF-8 YAML document without aliases, anchors, or merges."""
    if len(raw) > max_bytes:
        raise ValueError("YAML exceeds the configured byte bound")
    text = raw.decode("utf-8")
    for event in yaml.parse(text, Loader=yaml.SafeLoader):
        if isinstance(event, yaml.events.AliasEvent) or getattr(event, "anchor", None) is not None:
            raise ValueError("YAML aliases and anchors are not supported")
    node = yaml.compose(text, Loader=yaml.SafeLoader)
    if node is not None:
        pending = [node]
        while pending:
            current = pending.pop()
            if isinstance(current, yaml.nodes.MappingNode):
                for key, value in current.value:
                    if isinstance(key, yaml.nodes.ScalarNode) and key.value == "<<":
                        raise ValueError("YAML merge mappings are not supported")
                    pending.extend((key, value))
            elif isinstance(current, yaml.nodes.SequenceNode):
                pending.extend(current.value)
    return yaml.load(text, Loader=StrictYamlLoader)


def load_yaml_path(path: Path, *, max_bytes: int = DEFAULT_MAX_YAML_BYTES) -> Any:
    """Read and parse a bounded YAML file."""
    raw = path.read_bytes()
    return load_yaml_bytes(raw, max_bytes=max_bytes)
