"""
run_aggregate_human_ratings.py — Rebuild per-rater aggregates and pool across raters.

Rewrites each ``{rater_id}.json`` from that rater's clip JSONs, then writes
``aggregate_across_raters.json``. Use this after adding a metric (e.g. success
score) without re-rating.

Usage:
    python run_aggregate_human_ratings.py \\
        --output-folder /path/to/human_rating \\
        --configs configs/benchmark/control_cosmos_h_og_base.yaml \\
                  configs/benchmark/control_cosmos3_h_surgical_refined_cosmos.yaml

    # Or scan every subfolder of --output-folder:
    python run_aggregate_human_ratings.py --output-folder /path/to/human_rating
"""

from __future__ import annotations

import argparse
from pathlib import Path

from harness.human_rating import (
    list_complete_rater_ids,
    load_generation_sources,
    rating_folder_names_from_root,
    rewrite_rater_aggregate,
    write_across_raters_aggregate,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Aggregate complete human ratings across raters"
    )
    parser.add_argument(
        "--output-folder",
        required=True,
        help="Root folder passed to run_human_rating.py",
    )
    parser.add_argument(
        "--configs",
        nargs="*",
        default=None,
        help="Generation YAMLs (uses each output_folder name). Omit to scan the root.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_root = Path(args.output_folder)
    if not output_root.is_dir():
        raise FileNotFoundError(f"output folder not found: {output_root}")

    if args.configs:
        folder_names = [s.folder_name for s in load_generation_sources(args.configs)]
    else:
        folder_names = rating_folder_names_from_root(output_root)
        if not folder_names:
            raise RuntimeError(f"No config subfolders under {output_root}")

    for folder_name in folder_names:
        config_dir = output_root / folder_name
        rater_ids = list_complete_rater_ids(config_dir)
        if not rater_ids:
            print(f"{folder_name}: no complete raters yet")
            continue
        for rater_id in rater_ids:
            path = rewrite_rater_aggregate(output_root, folder_name, rater_id)
            if path is not None:
                print(f"{folder_name}: wrote {path}")
        across = write_across_raters_aggregate(output_root, folder_name)
        if across is not None:
            print(f"{folder_name}: wrote {across}")


if __name__ == "__main__":
    main()
