"""One read-only live Supervisor → MCP device → FAISS → specialist check."""

import json
import os

from osguard.graph import build_supervisor_graph
from osguard.state import make_initial_state


def main() -> int:
    os.environ["OSGUARD_DIRECT_FALLBACK"] = "0"
    request = "Are there any issues with the drivers in this PC? Inspect reported device problems and explain only supported findings."
    result = build_supervisor_graph(diagnostic_backend="mcp").invoke(make_initial_state(request))
    retrieval = result.get("retrieval_result")
    tools = result.get("tool_results", [])
    summary = {
        "category": str(getattr(result.get("classification"), "problem_type", "unknown")),
        "diagnostic_backend": result.get("diagnostic_backend"),
        "tool_results": [{"name": item.tool_name, "status": item.status,
                          "backend": item.backend, "evidence_id_present": bool(item.evidence_id)}
                         for item in tools],
        "retrieval_status": retrieval.status if retrieval else "not_run",
        "retrieval_backend": retrieval.backend if retrieval else None,
        "retrieved_passages": len(result.get("retrieved_evidence", [])),
        "specialists": [{"name": item.specialist.value, "status": item.status}
                        for item in result.get("specialist_results", [])],
        "error_codes": [item.code for item in result.get("errors", [])],
        "repair_executed": bool(result.get("execution_result") and
                                result["execution_result"].status == "success"),
    }
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 0 if (
        summary["diagnostic_backend"] == "mcp"
        and any(item.tool_name == "inspect_problem_devices" and item.status == "success"
                and item.backend == "mcp" for item in tools)
        and not summary["repair_executed"]
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
