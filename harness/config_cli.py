"""CLI helpers for YAML config overrides (``--set KEY=VALUE``)."""

from __future__ import annotations

import argparse
from typing import Any, MutableMapping, Sequence

import yaml


def add_set_argument(parser: argparse.ArgumentParser) -> None:
    """Register repeatable ``--set KEY=VALUE`` on *parser*."""
    parser.add_argument(
        "--set",
        dest="set_overrides",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help=(
            "Override a config key (repeatable). VALUE is YAML-parsed, e.g. "
            "--set device=cuda:0 --set timesteps=20 --set skip_existing=true "
            "--set 'resolution=[480, 832]'"
        ),
    )


def parse_set_value(raw: str) -> Any:
    """Parse a ``--set`` value with YAML typing, keeping ``cuda:0``-style strings."""
    try:
        parsed = yaml.safe_load(raw)
    except yaml.YAMLError:
        return raw
    # Bare tokens like ``cuda:0`` become mappings under YAML 1.1; keep the string.
    if isinstance(parsed, dict):
        return raw
    if parsed is None and raw.strip().lower() not in {"null", "~", ""}:
        return raw
    return parsed


def parse_set_item(item: str) -> tuple[str, Any]:
    """Split one ``KEY=VALUE`` override. KEY may use dots for nested maps."""
    if "=" not in item:
        raise ValueError(
            f"Invalid --set {item!r}: expected KEY=VALUE (e.g. device=cuda:0)"
        )
    key, raw_value = item.split("=", 1)
    key = key.strip()
    if not key:
        raise ValueError(f"Invalid --set {item!r}: empty KEY")
    return key, parse_set_value(raw_value)


def _assign_nested(cfg: MutableMapping[str, Any], key: str, value: Any) -> None:
    parts = [p for p in key.split(".") if p]
    if not parts:
        raise ValueError(f"Invalid --set key {key!r}")
    cur: MutableMapping[str, Any] = cfg
    for part in parts[:-1]:
        existing = cur.get(part)
        if existing is None:
            nxt: dict[str, Any] = {}
            cur[part] = nxt
            cur = nxt
        elif isinstance(existing, MutableMapping):
            cur = existing
        else:
            raise ValueError(
                f"Cannot override {key!r}: {part!r} is not a mapping "
                f"(got {type(existing).__name__})"
            )
    cur[parts[-1]] = value


def apply_set_overrides(
    cfg: MutableMapping[str, Any],
    items: Sequence[str] | None,
) -> MutableMapping[str, Any]:
    """
    Apply ``--set`` overrides onto *cfg* in order.

    Keys may be dotted (``a.b=1``) to write nested maps. Later ``--set`` flags
    win for the same key.
    """
    if not items:
        return cfg
    applied: list[str] = []
    for item in items:
        key, value = parse_set_item(item)
        _assign_nested(cfg, key, value)
        applied.append(f"{key}={value!r}")
    print("Config overrides (--set): " + ", ".join(applied))
    return cfg


def load_yaml_config(
    path: str,
    overrides: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Load a YAML mapping and apply optional ``--set`` overrides."""
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if cfg is None:
        cfg = {}
    if not isinstance(cfg, dict):
        raise ValueError(f"Config root must be a mapping, got {type(cfg).__name__}")
    apply_set_overrides(cfg, overrides)
    return cfg
