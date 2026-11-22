"""MCP protocol and graph-collector tests with disposable local fixtures."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from mcp import Client

from osguard.context import create_evidence_collection_node, select_read_only_tools
from osguard.mcp.client import MCPCollection, collect_mcp_async
from osguard.mcp.server import create_server
from osguard.schemas import (
    OSSubsystem, ProblemType, RequestIntent, RetrievalResult,
    SpecialistName, SupervisorClassification, ToolExecutionResult,
)
from osguard.state import make_initial_state
from osguard.tools.registry import APPROVED_ARGUMENTS, validate_arguments


def _state(request: str, subsystem: OSSubsystem, problem: ProblemType):
    state = make_initial_state(request)
    state["classification"] = SupervisorClassification(
        intent=RequestIntent.DIAGNOSE, problem_type=problem,
        os_subsystems=[subsystem], selected_specialists=[SpecialistName.DIAGNOSTIC],
    )
    state["selected_specialists"] = [SpecialistName.DIAGNOSTIC]
    return state


def test_server_discovery_and_structured_invocation(monkeypatch):
    from osguard.mcp import server as server_module
    monkeypatch.setattr(server_module, "get_system_info", lambda: ToolExecutionResult(
        tool_name="get_system_info", status="success", summary="Fixture OS",
        data={"os_name": "Windows 11"}, evidence_id="tool:get_system_info:fixture",
    ))
    server = create_server()
    async def check():
        async with Client(server) as client:
            tools = (await client.list_tools()).tools
            names = {item.name for item in tools}
            assert {"get_system_info", "get_largest_files", "get_directory_size", "list_services"} <= names
            assert "execute_command" not in names
            response = await client.call_tool("get_system_info", {})
            assert not response.is_error
            assert response.structured_content["evidence_id"] == "tool:get_system_info:fixture"
    asyncio.run(check())


def test_mcp_client_validates_and_preserves_provenance(monkeypatch):
    from osguard.mcp import server as server_module
    monkeypatch.setattr(server_module, "get_system_info", lambda: ToolExecutionResult(
        tool_name="get_system_info", status="success", summary="Fixture OS",
        data={"os_name": "Windows 11"}, evidence_id="tool:get_system_info:fixture",
    ))
    server = create_server()
    result = asyncio.run(collect_mcp_async(
        lambda _available: [("get_system_info", {})], lambda _results: [],
        client_factory=lambda: Client(server),
    ))
    assert result.results[0].status == "success"
    assert result.results[0].backend == "mcp"
    assert result.results[0].evidence_id == "tool:get_system_info:fixture"
    assert "get_system_info" in result.available


def test_invalid_arguments_rejected_before_tool_call():
    assert "get_largest_files" in APPROVED_ARGUMENTS
    try:
        validate_arguments("get_process_stats", {"limit": 0})
    except ValueError:
        pass
    else:
        raise AssertionError("Out-of-range limit was accepted")
    try:
        validate_arguments("execute_command", {})
    except ValueError:
        pass
    else:
        raise AssertionError("Unknown command tool was accepted")


def test_mcp_timeout_is_recorded_without_retry():
    calls = []
    class SlowClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_args):
            return None
        async def list_tools(self):
            tool = SimpleNamespace(name="get_system_info", description="Windows version",
                                   input_schema={"type": "object", "properties": {}, "additionalProperties": False})
            return SimpleNamespace(tools=[tool])
        async def call_tool(self, name, arguments, **_kwargs):
            calls.append((name, arguments))
            raise TimeoutError()
    result = asyncio.run(collect_mcp_async(
        lambda _available: [("get_system_info", {})], lambda _results: [],
        client_factory=SlowClient,
    ))
    assert result.results[0].error == "tool_timeout"
    assert calls == [("get_system_info", {})]


def test_collector_uses_controlled_direct_fallback_on_server_failure():
    state = _state("What is my Windows version after the driver issue?",
                   OSSubsystem.DEVICES_DRIVERS, ProblemType.SOFTWARE_FAILURE)
    calls = []
    def direct_info():
        calls.append("direct")
        return ToolExecutionResult(tool_name="get_system_info", status="success",
                                   summary="Fixture OS", data={"os_name": "Windows 11"},
                                   evidence_id="tool:get_system_info:fixture")
    def broken_server(*_args):
        raise ConnectionError("fixture unavailable")
    collect = create_evidence_collection_node(
        retriever=lambda query: RetrievalResult(status="no_results", query=query),
        windows_tools={"get_system_info": direct_info},
        diagnostic_backend="mcp", mcp_runner=broken_server,
    )
    update = collect(state)
    assert calls == ["direct"]
    assert update["diagnostic_backend"] == "direct"
    assert update["tool_results"][0].backend == "direct"
    assert update["errors"][0].code == "mcp_unavailable"


def test_capability_selection_for_known_folder_and_memory():
    folder = _state("Which file in Downloads is largest?", OSSubsystem.STORAGE_FILESYSTEM, ProblemType.STORAGE)
    assert select_read_only_tools(folder)[0][0] == "get_largest_files"
    assert select_read_only_tools(folder, {"get_memory_info": "memory"}) == []
    memory = _state("Which application uses the most RAM?", OSSubsystem.MEMORY, ProblemType.MEMORY)
    assert ("get_process_stats", {"limit": 12, "sample_seconds": 0.15, "sort_by": "memory"}) in select_read_only_tools(memory)


def test_multi_tool_mcp_collection_preserves_two_evidence_ids():
    state = _state("Which application uses the most RAM?", OSSubsystem.MEMORY, ProblemType.MEMORY)
    calls = []
    def fixture_runner(planner, follow_up):
        plan = planner({"get_memory_info": "Physical memory", "get_process_stats": "Process working-set memory"})
        calls.extend(name for name, _ in plan)
        results = [ToolExecutionResult(
            tool_name=name, status="success", summary="Fixture measurement",
            data={"total_bytes": 100} if name == "get_memory_info" else {
                "sort_by": "memory", "processes": [{"name": "fixture.exe", "pid": 1, "memory_bytes": 80}],
            },
            evidence_id=f"tool:{name}:fixture", backend="mcp",
        ) for name, _ in plan]
        assert follow_up(results) == []
        return MCPCollection(results=results, available={name: "fixture" for name, _ in plan}, selected=plan)
    update = create_evidence_collection_node(
        retriever=lambda query: RetrievalResult(status="no_results", query=query),
        diagnostic_backend="mcp", mcp_runner=fixture_runner,
    )(state)
    assert calls == ["get_memory_info", "get_process_stats"]
    assert update["diagnostic_backend"] == "mcp"
    assert {item.evidence_id for item in update["tool_results"]} == {
        "tool:get_memory_info:fixture", "tool:get_process_stats:fixture",
    }
