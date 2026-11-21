"""Command-line entry point for the curated local FAISS corpus."""

from __future__ import annotations

import argparse
import json
import sys

from osguard.rag.ingest import build_index


def main() -> int:
    parser = argparse.ArgumentParser(description="Build OSGuard's curated Microsoft documentation index")
    parser.add_argument("--sources", help="Optional path to a curated source JSON file")
    parser.add_argument("--index-dir", help="Optional FAISS output directory")
    options = parser.parse_args()
    kwargs = {}
    if options.sources:
        kwargs["source_config"] = options.sources
    if options.index_dir:
        kwargs["index_dir"] = options.index_dir
    result = build_index(**kwargs)
    print(json.dumps(result.model_dump(), indent=2))
    return 0 if result.status in {"success", "partial_success"} else 1


if __name__ == "__main__":
    sys.exit(main())
