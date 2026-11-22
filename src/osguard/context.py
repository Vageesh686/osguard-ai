"""Bounded evidence collection shared by selected specialist agents."""

from __future__ import annotations

import re
import json
import os
from collections.abc import Callable, Mapping
from typing import Any

from osguard.privacy import redact_sensitive_text
from osguard.schemas import (
    OSSubsystem,
    ProblemType,
    RequestIntent,
    RetrievalResult,
    SpecialistName,
    SystemEnvironment,
    ToolExecutionResult,
    WorkflowError,
)
from osguard.state import OSGuardState
from osguard.repair.demo_cache import DemoCacheStore, explicit_demo_request_quote, is_exact_demo_request
from osguard.tools.windows import (
    get_disk_info,
    get_event_logs,
    get_memory_info,
    get_process_stats,
    get_service_status,
    get_system_info,
    get_system_uptime,
    list_services,
)
from osguard.tools.filesystem import get_largest_files, list_directory, get_directory_size
from osguard.tools.registry import validate_arguments


WindowsTool = Callable[..., ToolExecutionResult]
_SERVICE_PATTERNS = (
    re.compile(r"\bservice\s+name\s*[:=]?\s*[`'\"]?([A-Za-z0-9_.-]{1,128})", re.I),
    re.compile(r"\bservice\s+named\s+[`'\"]([A-Za-z0-9_.-]{1,128})[`'\"]", re.I),
    re.compile(r"\bservice\s*[:=]\s*[`'\"]?([A-Za-z0-9_.-]{1,128})", re.I),
)


def _service_name(request: str) -> str | None:
    if re.search(r"\bwindows update\b", request, re.I):
        return "wuauserv"
    for pattern in _SERVICE_PATTERNS:
        match = pattern.search(request)
        if match:
            candidate = match.group(1).rstrip(".,;:")
            if candidate.casefold() not in {"failed", "stopped", "not", "is", "was", "has"}:
                return candidate
    return None


def _known_folder(request: str) -> str | None:
    for folder in ("Downloads", "Documents", "Desktop"):
        if re.search(rf"\b{folder}\b", request, re.I):
            return folder
    return None


def _local_fact_question(state: OSGuardState) -> bool:
    request = state.get("user_request", "")
    return bool(re.search(
        r"\b(which|what|show|list|is|how much|how many)\b.*\b"
        r"(file|folder|directory|downloads|documents|desktop|process|ram|memory|service|uptime|windows update)\b",
        request, re.I,
    ))


def select_read_only_tools(
    state: OSGuardState, available: Mapping[str, str] | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    """Select required measurements from the structured route and request."""
    classification = state.get("classification")
    if classification is None or classification.needs_clarification:
        return []
    selected = set(state.get("selected_specialists", []))
    if not selected:
        return []
    planned: list[tuple[str, dict[str, Any]]] = []
    subsystems = set(classification.os_subsystems)
    request = state.get("user_request", "").casefold()
    if is_exact_demo_request(state.get("user_request", "")) and SpecialistName.DIAGNOSTIC in selected:
        return [("inspect_osguard_demo_cache", {})]
    if SpecialistName.COMPATIBILITY in selected:
        planned.append(("get_system_info", {}))
    if SpecialistName.DIAGNOSTIC in selected and classification.intent in {
        RequestIntent.DIAGNOSE, RequestIntent.ANALYZE_LOGS,
        RequestIntent.CHECK_COMPATIBILITY,
    }:
        if explicit_demo_request_quote(state.get("user_request", "")):
            planned.append(("inspect_osguard_demo_cache", {}))
        folder = _known_folder(request)
        if folder and (OSSubsystem.STORAGE_FILESYSTEM in subsystems or re.search(r"\b(files?|folders?|directory|size|largest)\b", request)):
            if re.search(r"\b(largest|biggest|top\s+\d+|most space)\b", request):
                number = re.search(r"\b(?:top|show|list)\s+(\d{1,2})\b", request)
                planned.append(("get_largest_files", {"folder": folder, "limit": min(int(number.group(1)), 50) if number else 1}))
            elif re.search(r"\b(how much|size|space|occupy|take up)\b", request):
                planned.append(("get_directory_size", {"folder": folder}))
            elif re.search(r"\b(list|show|what files)\b", request):
                planned.append(("list_directory", {"folder": folder}))
        memory_needed = (
            OSSubsystem.MEMORY in subsystems
            or classification.problem_type == ProblemType.MEMORY
            or bool(re.search(r"\b(ram|memory|pagefile|paging|swap)\b", request))
        )
        cpu_needed = (
            OSSubsystem.PROCESS_CPU in subsystems
            or bool(re.search(r"\b(cpu|processor|slow computer|slow pc)\b", request))
        )
        if memory_needed:
            planned.append(("get_memory_info", {}))
        if cpu_needed or memory_needed:
            memory_ranking = memory_needed and bool(re.search(
                r"\b(most|highest|top|largest)\b.{0,32}\b(ram|memory)\b|"
                r"\b(ram|memory)\b.{0,32}\b(most|highest|top|largest)\b",
                request,
            ))
            planned.append(("get_process_stats", {
                "limit": 12, "sample_seconds": 0.15,
                "sort_by": "memory" if memory_ranking or not cpu_needed else "cpu",
            }))
        if (not folder or not any(name in dict(planned) for name in ("get_largest_files", "list_directory", "get_directory_size"))) and (
            OSSubsystem.STORAGE_FILESYSTEM in subsystems
            or any(token in request for token in ("disk space", "disk full", "storage", "file system"))
        ):
            planned.append(("get_disk_info", {}))
        if OSSubsystem.SERVICES_STARTUP in subsystems or "service" in request or "windows update" in request:
            name = _service_name(state.get("user_request", ""))
            if name:
                planned.append(("get_service_status", {"service_name": name}))
            elif any(token in request for token in ("failed", "crash", "error", "log", "update", "stopped")):
                planned.append(("get_event_logs", {"filters": {"log_name": "System", "hours_back": 24, "max_events": 20}}))
            else:
                planned.append(("list_services", {"limit": 30}))
        elif any(token in request for token in ("event log", "event viewer", "crash", "crashes", "crashing", "windows update", "after update", "error log")):
            planned.append(("get_event_logs", {"filters": {"log_name": "Application", "hours_back": 24, "max_events": 20}}))
        # Basic OS/build context helps diagnose update, driver, and dependency issues.
        if OSSubsystem.DEVICES_DRIVERS in subsystems or OSSubsystem.SOFTWARE_DEPENDENCIES in subsystems:
            planned.append(("get_system_info", {}))
        if "uptime" in request or "last boot" in request:
            planned.append(("get_system_uptime", {}))
    unique: dict[str, tuple[str, dict[str, Any]]] = {}
    for name, kwargs in planned:
        unique.setdefault(json.dumps([name, kwargs], sort_keys=True), (name, kwargs))
    if available is not None:
        unique = {key: value for key, value in unique.items()
                  if value[0] in available and bool(available[value[0]].strip())}
    return list(unique.values())[:4]


def select_follow_up_tools(
    state: OSGuardState, results: list[ToolExecutionResult]
) -> list[tuple[str, dict[str, Any]]]:
    """Request at most one new approved check when a service snapshot needs context."""
    classification = state.get("classification")
    if classification is None or SpecialistName.DIAGNOSTIC not in state.get("selected_specialists", []):
        return []
    if _local_fact_question(state):
        return []
    service = next((item for item in results if item.tool_name == "get_service_status"), None)
    if (
        service is None or service.status != "success"
        or str(service.data.get("status", "")).casefold() in {"running", ""}
        or any(item.tool_name == "get_event_logs" for item in results)
    ):
        return []
    return [("get_event_logs", {"filters": {
        "log_name": "System", "hours_back": 24, "max_events": 20
    }})]


def _retrieval_failure(query: str, exc: Exception) -> RetrievalResult:
    return RetrievalResult(
        status="retrieval_error",
        query=query,
        message=f"Documentation retrieval failed ({type(exc).__name__}); no passages were supplied to agents.",
    )


def create_evidence_collection_node(
    *,
    retriever: Callable[..., RetrievalResult] | None = None,
    windows_tools: Mapping[str, WindowsTool] | None = None,
    diagnostic_backend: str = "direct",
    mcp_runner: Callable[..., Any] | None = None,
) -> Callable[[OSGuardState], dict[str, Any]]:
    """Create one collector node with a fixed initial plan and one follow-up."""
    if diagnostic_backend not in {"mcp", "direct"}:
        raise ValueError("diagnostic_backend must be mcp or direct")
    if retriever is None:
        from osguard.rag.retriever import search_documentation

        active_retriever = search_documentation
    else:
        active_retriever = retriever
    tools: dict[str, WindowsTool] = {
        "get_system_info": get_system_info,
        "get_process_stats": get_process_stats,
        "get_memory_info": get_memory_info,
        "get_disk_info": get_disk_info,
        "get_service_status": get_service_status,
        "get_event_logs": get_event_logs,
        "get_largest_files": get_largest_files,
        "list_directory": list_directory,
        "get_directory_size": get_directory_size,
        "get_system_uptime": get_system_uptime,
        "list_services": list_services,
        "inspect_osguard_demo_cache": DemoCacheStore().tool_result,
    }
    if windows_tools:
        tools.update(windows_tools)

    def collect(state: OSGuardState) -> dict[str, Any]:
        classification = state.get("classification")
        if classification is None or classification.needs_clarification or not state.get("selected_specialists"):
            return {}
        request = state.get("user_request", "")
        query = redact_sensitive_text(request.strip())[:2000]
        if is_exact_demo_request(request) or (
            _local_fact_question(state)
            and classification.intent == RequestIntent.DIAGNOSE
        ):
            retrieval = RetrievalResult(
                status="not_applicable", query="",
                message="This local factual check uses measured evidence; documentation retrieval is not required.",
            )
        else:
            try:
                retrieval = active_retriever(query)
                if not isinstance(retrieval, RetrievalResult):
                    retrieval = RetrievalResult.model_validate(retrieval)
            except Exception as exc:
                retrieval = _retrieval_failure(query, exc)

        tool_results: list[ToolExecutionResult] = []
        errors: list[WorkflowError] = []
        def run_tool(tool_name: str, kwargs: dict[str, Any]) -> None:
            function = tools.get(tool_name)
            if function is None:
                tool_results.append(
                    ToolExecutionResult(
                        tool_name=tool_name,
                        status="failed",
                        summary="The configured read-only tool is unavailable.",
                        error="tool_unavailable",
                    )
                )
                return
            try:
                validated = kwargs if tool_name == "inspect_osguard_demo_cache" else validate_arguments(tool_name, kwargs)
                result = function(**validated)
                if not isinstance(result, ToolExecutionResult):
                    result = ToolExecutionResult.model_validate(result)
                result = result.model_copy(update={"backend": "direct"})
            except Exception as exc:
                result = ToolExecutionResult(
                    tool_name=tool_name,
                    status="failed",
                    summary="The read-only tool failed; no system changes were attempted.",
                    error=type(exc).__name__,
                    backend="direct",
                )
                errors.append(
                    WorkflowError(
                        stage="read_only_tools",
                        code="tool_failed",
                        message=f"{tool_name} did not return a diagnostic result.",
                    )
                )
            tool_results.append(result)

        plan = select_read_only_tools(state)
        backend_status = "unavailable"
        if diagnostic_backend == "mcp" and plan and not is_exact_demo_request(request):
            try:
                if mcp_runner is None:
                    from osguard.mcp.client import collect_mcp
                    runner = collect_mcp
                else:
                    runner = mcp_runner
                batch = runner(
                    lambda available: select_read_only_tools(state, available),
                    lambda previous: select_follow_up_tools(state, previous),
                )
                tool_results.extend(batch.results)
                backend_status = "mcp"
                missing = [(name, arguments) for name, arguments in plan
                           if name not in {item.tool_name for item in tool_results}]
                if missing and os.getenv("OSGUARD_DIRECT_FALLBACK", "1") == "1":
                    for name, arguments in missing:
                        run_tool(name, arguments)
                    backend_status = "direct"
                elif missing:
                    for name, _ in missing:
                        tool_results.append(ToolExecutionResult(
                            tool_name=name, status="failed", summary="The approved tool was not advertised by the MCP server.",
                            error="capability_unavailable", backend="mcp",
                        ))
            except Exception as exc:
                errors.append(WorkflowError(
                    stage="mcp_diagnostics", code="mcp_unavailable",
                    message=f"The local MCP server could not be used ({type(exc).__name__}).",
                ))
                if os.getenv("OSGUARD_DIRECT_FALLBACK", "1") == "1":
                    for name, arguments in plan:
                        run_tool(name, arguments)
                    backend_status = "direct"
                else:
                    backend_status = "unavailable"
        else:
            for name, arguments in plan:
                run_tool(name, arguments)
            if plan:
                backend_status = "direct"
        for tool_name, kwargs in select_follow_up_tools(state, tool_results):
            if tool_name not in {item.tool_name for item in tool_results}:
                if backend_status == "direct":
                    run_tool(tool_name, kwargs)
                elif backend_status == "unavailable":
                    break

        update: dict[str, Any] = {
            "retrieval_result": retrieval,
            "retrieved_evidence": retrieval.evidence if retrieval.status == "success" else [],
            "tool_results": tool_results,
            "diagnostic_backend": backend_status,
        }
        if not plan and SpecialistName.DIAGNOSTIC in state.get("selected_specialists", []):
            update["uncertainty_notes"] = [
                "No approved read-only diagnostic tool matched the requested measurement or authorized location."
            ]
        if OSSubsystem.DEVICES_DRIVERS in classification.os_subsystems:
            update.setdefault("uncertainty_notes", []).append(
                "Device and driver inventory is not available through an approved read-only tool."
            )
        if errors:
            update["errors"] = errors
        system_info = next(
            (
                item for item in tool_results
                if item.tool_name == "get_system_info" and item.status == "success"
            ),
            None,
        )
        if system_info:
            previous = state.get("available_environment", SystemEnvironment())
            update["available_environment"] = SystemEnvironment(
                source="read_only_tool",
                os_name=system_info.data.get("os_name"),
                os_version=system_info.data.get("os_version"),
                os_build=system_info.data.get("os_build"),
                architecture=system_info.data.get("architecture"),
                application_name=previous.application_name,
                application_version=previous.application_version,
                runtime_versions=previous.runtime_versions,
                other_known_facts=previous.other_known_facts,
            )
        return update

    return collect
