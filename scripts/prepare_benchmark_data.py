#!/usr/bin/env python3
"""Download and materialize public benchmark manifests."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.benchmark_data import DEFAULT_DATA_DIR, BENCHMARKS, materialize_benchmarks


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare public spreadsheet benchmark data.")
    parser.add_argument(
        "--benchmark",
        action="append",
        choices=[*sorted(BENCHMARKS), "all"],
        default=[],
        help="Benchmark to prepare. May repeat. Defaults to all.",
    )
    parser.add_argument(
        "--variant",
        help="Benchmark variant. Defaults: sheetbench=qa, spreadsheetbench=verified, v2=example.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_DATA_DIR),
        help="Directory for downloaded archives, extracted data, and generated manifests.",
    )
    parser.add_argument("--force", action="store_true", help="Redownload and re-extract archives.")
    parser.add_argument("--no-download", action="store_true", help="Use already downloaded archives only.")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    benchmarks = args.benchmark or ["all"]
    manifests = materialize_benchmarks(
        benchmarks,
        output_dir=args.output_dir,
        variant=args.variant,
        force=args.force,
        download=not args.no_download,
    )
    for manifest in manifests:
        print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
