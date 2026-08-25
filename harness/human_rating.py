"""Discover generation clips and persist human ratings (per rater, per config)."""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness.config_cli import load_yaml_config

SCORE_KEYS = ("query_followed", "tool_consistency", "anatomy_natural")
SUCCESS_SCORE_THRESHOLD = 3
ACROSS_RATERS_FILENAME = "aggregate_across_raters.json"
RESERVED_RATER_IDS = {ACROSS_RATERS_FILENAME.removesuffix(".json")}
QUERY_SUFFIX = "_query.txt"
REFINED_FOLDER_SUFFIXES = ("_refined_cosmos", "_refined_mm")


def _log(msg: str) -> None:
    print(msg, flush=True)


@dataclass(frozen=True)
class GenerationSource:
    config_path: Path
    config_name: str
    folder_path: Path | None
    output_folder: Path
    folder_name: str


@dataclass(frozen=True)
class Clip:
    clip_id: str
    output_stem: str
    video_path: Path
    prompt_path: Path
    metadata_path: Path | None
    query: str
    query_path: Path | None
    source_prompt: str
    source_prompt_path: Path | None
    source: GenerationSource


def sanitize_rater_id(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        raise ValueError("Rater ID is empty.")
    if value in RESERVED_RATER_IDS:
        raise ValueError(f"Rater ID {value!r} is reserved.")
    if value in {".", ".."} or ".." in value:
        raise ValueError(f"Invalid rater ID: {value!r}")
    if any(c in value for c in "/\\:\0"):
        raise ValueError(f"Rater ID must not contain path separators: {value!r}")
    return value


def resolve_config_data_path(raw: str | Path, config_path: Path) -> Path:
    """Resolve ``folder_path`` / ``output_folder`` against the YAML directory when relative."""
    path = Path(raw)
    if path.is_absolute():
        return path
    return (config_path.parent / path).resolve()


def load_generation_sources(config_paths: list[str | Path]) -> list[GenerationSource]:
    sources: list[GenerationSource] = []
    seen_folders: dict[str, Path] = {}
    _log(f"Loading {len(config_paths)} generation config(s)…")
    for raw in config_paths:
        config_path = Path(raw).resolve()
        _log(f"  config {config_path.name}")
        cfg = load_yaml_config(str(config_path))
        output_folder = cfg.get("output_folder")
        if not output_folder:
            raise ValueError(f"{config_path} is missing output_folder")
        output_path = resolve_config_data_path(output_folder, config_path)
        folder_name = output_path.name
        if not folder_name:
            raise ValueError(f"{config_path}: output_folder has no directory name")
        previous = seen_folders.get(folder_name)
        if previous is not None:
            if previous.resolve() != output_path.resolve():
                raise ValueError(
                    f"Duplicate rating subfolder {folder_name!r} from "
                    f"{previous} and {output_path}"
                )
            _log(f"    skip duplicate output folder {folder_name}")
            continue
        seen_folders[folder_name] = output_path
        folder_path_raw = cfg.get("folder_path")
        folder_path = (
            resolve_config_data_path(folder_path_raw, config_path)
            if folder_path_raw
            else None
        )
        sources.append(
            GenerationSource(
                config_path=config_path,
                config_name=config_path.name,
                folder_path=folder_path,
                output_folder=output_path,
                folder_name=folder_name,
            )
        )
        _log(f"    videos: {output_path}")
        if folder_path is not None:
            _log(f"    prompts: {folder_path}")
    return sources


def original_prompt_root(folder_path: Path) -> Path:
    """``control_prompts_refined_cosmos`` → ``control_prompts`` (original .txt + _query.txt)."""
    name = folder_path.name
    for suffix in REFINED_FOLDER_SUFFIXES:
        if name.endswith(suffix):
            return folder_path.with_name(name[: -len(suffix)])
    return folder_path


def _looks_like_model_json(text: str) -> bool:
    stripped = text.lstrip()
    return stripped.startswith("{") or stripped.startswith("[")


def index_prompt_tree(folder_path: Path) -> tuple[dict[str, Path], dict[str, Path]]:
    """Map generation ``output_stem`` → ``{stem}_query.txt`` and original ``{stem}.txt``."""
    queries: dict[str, Path] = {}
    texts: dict[str, Path] = {}
    if not folder_path.is_dir():
        _log(f"  prompt folder missing: {folder_path}")
        return queries, texts
    _log(f"  indexing {folder_path} …")
    for path in folder_path.glob("*/*/*.txt"):
        dataset = path.parent.parent.name
        index_name = path.parent.name
        name = path.name
        key_stem: str
        if name.endswith(QUERY_SUFFIX):
            key_stem = name[: -len(QUERY_SUFFIX)]
            queries[f"{dataset}_{index_name}_{key_stem}"] = path
            continue
        if name.endswith("_negative.txt"):
            continue
        key = f"{dataset}_{index_name}_{path.stem}"
        texts[key] = path
    _log(f"  indexed {len(queries)} query file(s), {len(texts)} txt file(s)")
    return queries, texts


def _load_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else None


def discover_clips(sources: list[GenerationSource]) -> list[Clip]:
    clips: list[Clip] = []
    missing_query = 0
    for source in sources:
        _log(f"Scanning videos in {source.folder_name} …")
        if not source.output_folder.is_dir():
            raise FileNotFoundError(
                f"Generation output folder not found: {source.output_folder} "
                f"(from {source.config_path})"
            )
        videos = sorted(source.output_folder.glob("*.mp4"))
        _log(f"  {len(videos)} mp4 file(s)")
        if not videos:
            raise RuntimeError(f"No .mp4 files in {source.output_folder}")
        if source.folder_path is None:
            query_index, text_index = {}, {}
        else:
            original_root = original_prompt_root(source.folder_path)
            _log(f"  original prompt tree: {original_root}")
            query_index, text_index = index_prompt_tree(original_root)
            if source.folder_path.resolve() != original_root.resolve():
                extra_queries, _ = index_prompt_tree(source.folder_path)
                for key, path in extra_queries.items():
                    query_index.setdefault(key, path)
        matched = 0
        for i, video_path in enumerate(videos, start=1):
            if i == 1 or i % 50 == 0 or i == len(videos):
                _log(f"  matching {i}/{len(videos)}")
            stem = video_path.stem
            prompt_path = video_path.with_suffix(".txt")
            if not prompt_path.is_file():
                continue
            metadata_path = video_path.with_suffix(".json")
            query_path = query_index.get(stem)
            if query_path is not None:
                query = query_path.read_text(encoding="utf-8").strip()
            else:
                query = ""
                missing_query += 1
            source_prompt_path = text_index.get(stem)
            source_prompt = ""
            if source_prompt_path is not None:
                source_prompt = source_prompt_path.read_text(encoding="utf-8").strip()
                if _looks_like_model_json(source_prompt):
                    _log(f"  skip model-json txt for {stem}: {source_prompt_path}")
                    source_prompt = ""
                    source_prompt_path = None
            matched += 1
            clips.append(
                Clip(
                    clip_id=f"{source.folder_name}::{stem}",
                    output_stem=stem,
                    video_path=video_path,
                    prompt_path=prompt_path,
                    metadata_path=metadata_path if metadata_path.is_file() else None,
                    query=query,
                    query_path=query_path,
                    source_prompt=source_prompt,
                    source_prompt_path=source_prompt_path,
                    source=source,
                )
            )
        _log(f"  kept {matched} clip(s) with a matching .txt")
    if not clips:
        raise RuntimeError("No clips with matching .mp4 + .txt were found.")
    if missing_query:
        _log(
            f"WARNING: {missing_query} clip(s) have no {QUERY_SUFFIX} sidecar "
            f"next to the prompt tree (dataset/index/{{stem}}_query.txt)"
        )
    _log(f"Discovered {len(clips)} clip(s) across {len(sources)} config(s)")
    return clips


def config_rating_dir(output_root: Path, folder_name: str) -> Path:
    return output_root / folder_name


def rater_clips_dir(output_root: Path, folder_name: str, rater_id: str) -> Path:
    return config_rating_dir(output_root, folder_name) / rater_id


def rating_json_path(
    output_root: Path, folder_name: str, rater_id: str, output_stem: str
) -> Path:
    return rater_clips_dir(output_root, folder_name, rater_id) / f"{output_stem}.json"


def rater_aggregate_path(output_root: Path, folder_name: str, rater_id: str) -> Path:
    return config_rating_dir(output_root, folder_name) / f"{rater_id}.json"


def is_clip_rated(output_root: Path, clip: Clip, rater_id: str) -> bool:
    return rating_json_path(
        output_root, clip.source.folder_name, rater_id, clip.output_stem
    ).is_file()


def unrated_clips(output_root: Path, clips: list[Clip], rater_id: str) -> list[Clip]:
    return [c for c in clips if not is_clip_rated(output_root, c, rater_id)]


def load_rating(path: Path) -> dict[str, Any] | None:
    return _load_optional_json(path)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def validate_scores(scores: dict[str, Any]) -> dict[str, int]:
    cleaned: dict[str, int] = {}
    for key in SCORE_KEYS:
        if key not in scores or scores[key] is None:
            raise ValueError(f"Missing score: {key}")
        value = int(scores[key])
        if value < 1 or value > 5:
            raise ValueError(f"Score {key} must be 1–5, got {value}")
        cleaned[key] = value
    return cleaned


def save_rating(
    output_root: Path,
    clip: Clip,
    rater_id: str,
    scores: dict[str, Any],
) -> Path:
    rater_id = sanitize_rater_id(rater_id)
    cleaned = validate_scores(scores)
    prompt = ""
    if clip.prompt_path.is_file():
        prompt = clip.prompt_path.read_text(encoding="utf-8").strip()
    payload = {
        "rater_id": rater_id,
        "output_stem": clip.output_stem,
        "video_path": str(clip.video_path),
        "query": clip.query,
        "query_path": str(clip.query_path) if clip.query_path else None,
        "source_prompt": clip.source_prompt,
        "source_prompt_path": (
            str(clip.source_prompt_path) if clip.source_prompt_path else None
        ),
        "prompt": prompt,
        "scores": cleaned,
        "rated_at": _utc_now(),
        "generation_config": clip.source.config_name,
        "generation_config_path": str(clip.source.config_path),
        "generation_output_folder": str(clip.source.output_folder),
        "generation_metadata": _load_optional_json(clip.metadata_path)
        if clip.metadata_path
        else None,
    }
    path = rating_json_path(
        output_root, clip.source.folder_name, rater_id, clip.output_stem
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return path


def _mean_std(values: list[float]) -> dict[str, float | int | None]:
    n = len(values)
    if n == 0:
        return {"mean": None, "std": None, "n": 0}
    mean = statistics.fmean(values)
    std = statistics.stdev(values) if n >= 2 else 0.0
    return {"mean": mean, "std": std, "n": n}


def metrics_from_ratings(ratings: list[dict[str, Any]]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for key in SCORE_KEYS:
        values: list[float] = []
        for rating in ratings:
            scores = rating.get("scores") or {}
            if key in scores and scores[key] is not None:
                values.append(float(scores[key]))
        metrics[key] = _mean_std(values)

    followed: list[float] = []
    for rating in ratings:
        scores = rating.get("scores") or {}
        if scores.get("query_followed") is not None:
            followed.append(float(scores["query_followed"]))
    n = len(followed)
    n_success = sum(1 for value in followed if value >= SUCCESS_SCORE_THRESHOLD)
    metrics["success_score"] = {
        "threshold": SUCCESS_SCORE_THRESHOLD,
        "n_success": n_success,
        "n": n,
        "ratio": (n_success / n) if n else None,
    }
    return metrics


def clips_for_source(clips: list[Clip], folder_name: str) -> list[Clip]:
    return [c for c in clips if c.source.folder_name == folder_name]


def load_rater_clip_ratings(
    output_root: Path, folder_name: str, rater_id: str
) -> list[dict[str, Any]]:
    folder = rater_clips_dir(output_root, folder_name, rater_id)
    if not folder.is_dir():
        return []
    ratings: list[dict[str, Any]] = []
    for path in sorted(folder.glob("*.json")):
        data = load_rating(path)
        if data is not None:
            ratings.append(data)
    return ratings


def maybe_write_rater_aggregate(
    output_root: Path,
    folder_name: str,
    rater_id: str,
    expected_clips: list[Clip],
) -> Path | None:
    """Write ``{rater_id}.json`` when every expected clip for this config is rated."""
    rater_id = sanitize_rater_id(rater_id)
    expected = clips_for_source(expected_clips, folder_name)
    if not expected:
        return None
    n_rated = sum(1 for c in expected if is_clip_rated(output_root, c, rater_id))
    if n_rated < len(expected):
        return None
    ratings = load_rater_clip_ratings(output_root, folder_name, rater_id)
    payload = {
        "rater_id": rater_id,
        "folder_name": folder_name,
        "n_expected": len(expected),
        "n_rated": n_rated,
        "complete": True,
        "updated_at": _utc_now(),
        "metrics": metrics_from_ratings(ratings),
    }
    path = rater_aggregate_path(output_root, folder_name, rater_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return path


def refresh_rater_aggregates(
    output_root: Path, clips: list[Clip], rater_id: str
) -> list[Path]:
    _log(f"Checking aggregates for rater {rater_id!r} …")
    written: list[Path] = []
    folders = sorted({c.source.folder_name for c in clips})
    for folder_name in folders:
        path = maybe_write_rater_aggregate(output_root, folder_name, rater_id, clips)
        if path is not None:
            _log(f"  wrote {path}")
            written.append(path)
        else:
            n_expected = len(clips_for_source(clips, folder_name))
            n_rated = sum(
                1
                for c in clips_for_source(clips, folder_name)
                if is_clip_rated(output_root, c, rater_id)
            )
            _log(f"  {folder_name}: {n_rated}/{n_expected} rated (aggregate later)")
    return written


def rewrite_rater_aggregate(
    output_root: Path,
    folder_name: str,
    rater_id: str,
    *,
    n_expected: int | None = None,
) -> Path | None:
    """Rebuild ``{rater_id}.json`` from that rater's clip JSONs (no re-rating)."""
    ratings = load_rater_clip_ratings(output_root, folder_name, rater_id)
    if not ratings:
        return None
    existing = load_rating(rater_aggregate_path(output_root, folder_name, rater_id))
    expected = n_expected
    if expected is None and existing is not None:
        raw = existing.get("n_expected")
        expected = int(raw) if raw is not None else None
    if expected is None:
        expected = len(ratings)
    payload = {
        "rater_id": rater_id,
        "folder_name": folder_name,
        "n_expected": expected,
        "n_rated": len(ratings),
        "complete": len(ratings) >= expected,
        "updated_at": _utc_now(),
        "metrics": metrics_from_ratings(ratings),
    }
    path = rater_aggregate_path(output_root, folder_name, rater_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return path


def list_complete_rater_ids(config_dir: Path) -> list[str]:
    ids: list[str] = []
    if not config_dir.is_dir():
        return ids
    for path in sorted(config_dir.glob("*.json")):
        if path.name == ACROSS_RATERS_FILENAME:
            continue
        rater_id = path.stem
        if not (config_dir / rater_id).is_dir():
            continue
        ids.append(rater_id)
    return ids


def write_across_raters_aggregate(
    output_root: Path,
    folder_name: str,
    expected_stems: list[str] | None = None,
) -> Path | None:
    config_dir = config_rating_dir(output_root, folder_name)
    rater_ids = list_complete_rater_ids(config_dir)
    if not rater_ids:
        return None

    per_rater: dict[str, Any] = {}
    all_ratings: list[dict[str, Any]] = []
    for rater_id in rater_ids:
        ratings = load_rater_clip_ratings(output_root, folder_name, rater_id)
        if expected_stems is not None:
            ratings = [r for r in ratings if r.get("output_stem") in expected_stems]
        per_rater[rater_id] = metrics_from_ratings(ratings)
        all_ratings.extend(ratings)

    payload = {
        "folder_name": folder_name,
        "rater_ids": rater_ids,
        "n_raters": len(rater_ids),
        "n_ratings": len(all_ratings),
        "updated_at": _utc_now(),
        "metrics": metrics_from_ratings(all_ratings),
        "per_rater": per_rater,
    }
    path = config_dir / ACROSS_RATERS_FILENAME
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return path


def rating_folder_names_from_root(output_root: Path) -> list[str]:
    if not output_root.is_dir():
        return []
    names: list[str] = []
    for child in sorted(output_root.iterdir()):
        if child.is_dir() and not child.name.startswith("."):
            names.append(child.name)
    return names
