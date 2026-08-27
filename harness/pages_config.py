"""Load the rater-pages YAML that maps URL paths to generation configs."""

from __future__ import annotations

import glob
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# Streamlit url_path cannot contain slashes or be empty (default page uses "").
_PATH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


@dataclass(frozen=True)
class RatingPage:
    path: str
    title: str
    configs: tuple[Path, ...]
    output_folder: Path


def _as_str(value: Any, *, field: str, page_index: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"pages[{page_index}].{field} must be a non-empty string")
    return value.strip()


def _expand_config_pattern(
    raw: str, pages_dir: Path, *, exclude: Path | None = None
) -> list[Path]:
    path = Path(raw)
    if not path.is_absolute():
        path = pages_dir / path
    pattern = str(path)
    if any(ch in pattern for ch in "*?["):
        matches = sorted(Path(m).resolve() for m in glob.glob(pattern))
        files = [p for p in matches if p.is_file() and p != exclude]
        if not files:
            raise FileNotFoundError(f"No config files matched {raw!r} ({pattern})")
        return files
    resolved = path.resolve()
    if exclude is not None and resolved == exclude:
        raise ValueError(f"Config path {raw!r} must not be the pages YAML itself")
    if not resolved.is_file():
        raise FileNotFoundError(f"Config file not found: {resolved} (from {raw!r})")
    return [resolved]


def _parse_page(
    raw: Any, *, page_index: int, pages_dir: Path, pages_config_path: Path
) -> RatingPage:
    if not isinstance(raw, dict):
        raise ValueError(f"pages[{page_index}] must be a mapping")

    path = _as_str(raw.get("path"), field="path", page_index=page_index)
    if not _PATH_RE.fullmatch(path):
        raise ValueError(
            f"pages[{page_index}].path {path!r} is invalid; use letters, digits, "
            f"hyphens, and underscores only (no slashes)"
        )

    title_raw = raw.get("title")
    if title_raw is None:
        title = path
    else:
        title = _as_str(title_raw, field="title", page_index=page_index)

    configs_raw = raw.get("configs")
    if not isinstance(configs_raw, list) or not configs_raw:
        raise ValueError(f"pages[{page_index}].configs must be a non-empty list")

    configs: list[Path] = []
    seen: set[Path] = set()
    for item in configs_raw:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(
                f"pages[{page_index}].configs entries must be non-empty strings"
            )
        for config_path in _expand_config_pattern(
            item.strip(), pages_dir, exclude=pages_config_path
        ):
            if config_path not in seen:
                seen.add(config_path)
                configs.append(config_path)

    if not configs:
        raise ValueError(f"pages[{page_index}].configs matched no generation YAML files")

    output_raw = _as_str(
        raw.get("output_folder"), field="output_folder", page_index=page_index
    )
    output_folder = Path(output_raw)
    if not output_folder.is_absolute():
        output_folder = (pages_dir / output_folder).resolve()
    else:
        output_folder = output_folder.resolve()

    return RatingPage(
        path=path,
        title=title,
        configs=tuple(configs),
        output_folder=output_folder,
    )


def load_pages_config(path: str | Path) -> list[RatingPage]:
    config_path = Path(path).resolve()
    if not config_path.is_file():
        raise FileNotFoundError(f"Pages config not found: {config_path}")

    with config_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{config_path}: root must be a mapping")

    pages_raw = data.get("pages")
    if not isinstance(pages_raw, list) or not pages_raw:
        raise ValueError(f"{config_path}: pages must be a non-empty list")

    pages_dir = config_path.parent
    pages: list[RatingPage] = []
    seen_paths: dict[str, int] = {}
    for i, item in enumerate(pages_raw):
        page = _parse_page(
            item,
            page_index=i,
            pages_dir=pages_dir,
            pages_config_path=config_path,
        )
        previous = seen_paths.get(page.path)
        if previous is not None:
            raise ValueError(
                f"Duplicate pages path {page.path!r} at indexes {previous} and {i}"
            )
        seen_paths[page.path] = i
        pages.append(page)
    return pages
