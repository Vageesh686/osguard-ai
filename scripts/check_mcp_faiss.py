"""Manual, read-only MCP + persisted FAISS + Groq smoke check.

Run only after initializing the documentation index. This script does not
request repair approval or execute any repair action.
"""

from __future__ import annotations

import json
import os

from osguard.graph import build_supervisor_graph
from osguard.state import make_initial_state


REQUEST = (
    "Why is my PC using so much RAM? Check my current memory usage, identify "
    "the main memory-consuming processes, and explain the findings using "
    "Microsoft documentation."
)


def main() -> int:
    # A failed MCP connection must be visible; the same-process direct tool
    # fallback would make this specific integration check ambiguous.
    os.environ["OSGUARD_DIRECT_FALLBACK"] = "0"
    result = build_supervisor_graph(diagnostic_backend="mcp").invoke(make_initial_state(REQUEST))
    retrieval = result.get("retrieval_result")
    tools = result.get("tool_results", [])
    final = result.get("final_response")
    summary = {
        "diagnostic_backend": result.get("diagnostic_backend"),
        "retrieval_status": retrieval.status if retrieval else "not_run",
        "retrieval_backend": retrieval.backend if retrieval else None,
        "evidence": [
            {"id": item.source_id, "title": item.title, "url": item.source_url,
             "section": item.metadata.get("section")}
            for item in result.get("retrieved_evidence", [])
        ],
        "tools": [
            {"name": item.tool_name, "status": item.status, "backend": item.backend,
             "evidence_id": item.evidence_id}
            for item in tools
        ],
        "specialists": [
            {"name": item.specialist.value, "status": item.status}
            for item in result.get("specialist_results", [])
        ],
        "error_codes": [item.code for item in result.get("errors", [])],
        "final_response": final.message if final else None,
        "repair_executed": bool(result.get("execution_result") and
                                result["execution_result"].status == "success"),
    }
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    successful_tools = {item.tool_name for item in tools if item.status == "success" and item.backend == "mcp"}
    return 0 if (
        summary["diagnostic_backend"] == "mcp"
        and summary["retrieval_status"] == "success"
        and summary["retrieval_backend"] == "faiss"
        and {"get_memory_info", "get_process_stats"}.issubset(successful_tools)
        and not summary["repair_executed"]
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
