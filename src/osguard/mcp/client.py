"""Local stdio MCP client for the existing synchronous evidence node."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import validate as validate_json_schema

from osguard.schemas import ToolExecutionResult
from osguard.tools.registry import APPROVED_ARGUMENTS, validate_arguments


Plan = list[tuple[str, dict[str, Any]]]


@dataclass(frozen=True)
class MCPCollection:
    results: list[ToolExecutionResult]
    available: dict[str, str]
    selected: Plan
    error: str | None = None


def _server_parameters():
    from mcp import StdioServerParameters

    source_root = Path(__file__).resolve().parents[2]
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "osguard.mcp.server"],
        env={"PYTHONPATH": str(source_root)},
    )


def _failed(name: str, code: str, detail: str) -> ToolExecutionResult:
    return ToolExecutionResult(
        tool_name=name, status="failed", summary=detail,
        error=code, backend="mcp",
    )


async def collect_mcp_async(
    planner: Callable[[Mapping[str, str]], Plan],
    follow_up: Callable[[list[ToolExecutionResult]], Plan],
    *,
    client_factory: Callable[[], Any] | None = None,
) -> MCPCollection:
    """Discover, validate and call approved tools in one disposable session."""
    if client_factory is None:
        from mcp import Client
        client_factory = lambda: Client(_server_parameters())
    async with client_factory() as client:
        listing = await asyncio.wait_for(client.list_tools(), timeout=8.0)
        discovered = {
            tool.name: tool for tool in listing.tools
            if tool.name in APPROVED_ARGUMENTS
        }
        descriptions = {name: str(tool.description or "") for name, tool in discovered.items()}
        selected = planner(descriptions)[:4]
        results: list[ToolExecutionResult] = []
        called: set[str] = set()

        async def call(name: str, arguments: dict[str, Any]) -> None:
            if name in called:
                return
            called.add(name)
            tool = discovered.get(name)
            if tool is None:
                results.append(_failed(name, "tool_unavailable", "The MCP server did not advertise this approved tool."))
                return
            try:
                validated = validate_arguments(name, arguments)
                validate_json_schema(instance=validated, schema=tool.input_schema)
            except Exception:
                results.append(ToolExecutionResult(
                    tool_name=name, status="invalid_input",
                    summary="Tool arguments failed local or advertised MCP schema validation.",
                    error="invalid_arguments", backend="mcp",
                ))
                return
            try:
                response = await asyncio.wait_for(
                    client.call_tool(name, validated, read_timeout_seconds=25.0),
                    timeout=27.0,
                )
                if response.is_error or not isinstance(response.structured_content, dict):
                    raise ValueError("MCP tool returned an error or no structured data")
                result = ToolExecutionResult.model_validate(response.structured_content)
                if result.tool_name != name or (result.status == "success" and not result.evidence_id):
                    raise ValueError("MCP result name or evidence ID did not match the call")
                results.append(result.model_copy(update={"backend": "mcp"}))
            except TimeoutError:
                results.append(_failed(name, "tool_timeout", "MCP read-only tool timed out; it was not retried."))
            except Exception as exc:
                results.append(_failed(name, type(exc).__name__, "MCP read-only tool failed; no result was accepted."))

        for name, arguments in selected:
            await call(name, arguments)
        for name, arguments in follow_up(results)[:1]:
            await call(name, arguments)
        return MCPCollection(results=results, available=descriptions, selected=selected)


def collect_mcp(
    planner: Callable[[Mapping[str, str]], Plan],
    follow_up: Callable[[list[ToolExecutionResult]], Plan],
    *,
    client_factory: Callable[[], Any] | None = None,
) -> MCPCollection:
    """Synchronous boundary used by LangGraph's existing collector node."""
    return asyncio.run(collect_mcp_async(planner, follow_up, client_factory=client_factory))
