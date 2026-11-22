"""Command-line entry point for the curated local FAISS corpus."""

from __future__ import annotations

import argparse
import json
import sys

from osguard.rag.knowledge_base import initialize_knowledge_base


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
    result = initialize_knowledge_base(**kwargs)
    print(json.dumps({
        "status": result.state, "backend": result.backend,
        "index_dir": result.index_dir, "document_count": result.document_count,
        "retrieval_verified": result.retrieval_verified,
        "message": result.message, "errors": result.errors,
    }, indent=2))
    return 0 if result.state == "faiss_ready" and result.retrieval_verified else 1


if __name__ == "__main__":
    sys.exit(main())
