"""
run_aggregate_human_ratings.py — Rebuild per-rater aggregates and pool across raters.

Rewrites each ``{rater_id}.json`` from that rater's clip JSONs, then writes
``aggregate_across_raters.json``. Use this after adding a metric (e.g. success
score) without re-rating.

Usage:
    python run_aggregate_human_ratings.py --pages-config rater_pages.yaml
"""

from __future__ import annotations

import argparse
from pathlib import Path

from harness.human_rating import (
    list_complete_rater_ids,
    load_generation_sources,
    rewrite_rater_aggregate,
    write_across_raters_aggregate,
)
from harness.pages_config import load_pages_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Aggregate complete human ratings across raters"
    )
    parser.add_argument(
        "--pages-config",
        required=True,
        help="Rater pages YAML (aggregates each page's output_folder)",
    )
    return parser.parse_args()


def _aggregate_root(
    output_root: Path, *, configs: list[str], label: str
) -> None:
    prefix = f"{label}: "
    if not output_root.is_dir():
        print(f"{prefix}output folder not found: {output_root}")
        return

    folder_names = [s.folder_name for s in load_generation_sources(configs)]
    if not folder_names:
        print(f"{prefix}no generation configs to aggregate")
        return

    for folder_name in folder_names:
        config_dir = output_root / folder_name
        rater_ids = list_complete_rater_ids(config_dir)
        if not rater_ids:
            print(f"{prefix}{folder_name}: no complete raters yet")
            continue
        for rater_id in rater_ids:
            path = rewrite_rater_aggregate(output_root, folder_name, rater_id)
            if path is not None:
                print(f"{prefix}{folder_name}: wrote {path}")
        across = write_across_raters_aggregate(output_root, folder_name)
        if across is not None:
            print(f"{prefix}{folder_name}: wrote {across}")


def main() -> None:
    args = parse_args()
    pages = load_pages_config(args.pages_config)
    for page in pages:
        _aggregate_root(
            page.output_folder,
            configs=[str(p) for p in page.configs],
            label=page.path,
        )


if __name__ == "__main__":
    main()
