"""Official MCP SDK server exposing only bounded read-only diagnostics."""

from __future__ import annotations

from typing import Any, Literal

from mcp.server import MCPServer
from pydantic import Field

from osguard.schemas import ToolExecutionResult
from osguard.tools.registry import EventFilters
from osguard.tools.filesystem import get_directory_size, get_largest_files, list_directory
from osguard.tools.windows import (
    get_disk_info, get_event_logs, get_memory_info, get_process_stats,
    get_service_status, get_system_info, get_system_uptime, list_services,
)


def _wire(result: ToolExecutionResult) -> dict[str, Any]:
    return result.model_dump(mode="json")


def create_server() -> MCPServer:
    """Build a stdio-only server; there is no repair or command tool."""
    server = MCPServer("osguard-windows-diagnostics", version="0.1.0")

    @server.tool(name="get_system_info", description="Read Windows version, build and architecture.", structured_output=True)
    def system_info() -> dict[str, Any]:
        return _wire(get_system_info())

    @server.tool(name="get_process_stats", description="Rank bounded Windows processes by CPU or resident working-set memory.", structured_output=True)
    def process_stats(limit: int = Field(default=10, ge=1, le=50),
                      sample_seconds: float = Field(default=0.15, ge=0.05, le=0.5),
                      sort_by: Literal["cpu", "memory"] = "cpu") -> dict[str, Any]:
        return _wire(get_process_stats(limit=limit, sample_seconds=sample_seconds, sort_by=sort_by))

    @server.tool(name="get_memory_info", description="Read physical memory totals and utilization.", structured_output=True)
    def memory_info() -> dict[str, Any]:
        return _wire(get_memory_info())

    @server.tool(name="get_disk_info", description="Read bounded local volume capacity and free space.", structured_output=True)
    def disk_info() -> dict[str, Any]:
        return _wire(get_disk_info())

    @server.tool(name="get_service_status", description="Inspect one exact Windows service name and start type.", structured_output=True)
    def service_status(service_name: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")) -> dict[str, Any]:
        return _wire(get_service_status(service_name))

    @server.tool(name="get_event_logs", description="Read a bounded, filtered Application, System or Setup event query.", structured_output=True)
    def event_logs(filters: EventFilters) -> dict[str, Any]:
        return _wire(get_event_logs(filters=filters.model_dump(mode="python")))

    @server.tool(name="get_largest_files", description="Rank file metadata in an approved Windows known folder; do not read contents.", structured_output=True)
    def largest_files(folder: Literal["Downloads", "Documents", "Desktop"],
                      limit: int = Field(default=10, ge=1, le=50),
                      recursive: bool = False,
                      max_depth: int = Field(default=2, ge=0, le=3),
                      max_entries: int = Field(default=2000, ge=1, le=5000),
                      timeout_seconds: float = Field(default=5.0, ge=0.1, le=10.0)) -> dict[str, Any]:
        return _wire(get_largest_files(folder=folder, limit=limit, recursive=recursive,
                                       max_depth=max_depth, max_entries=max_entries,
                                       timeout_seconds=timeout_seconds))

    @server.tool(name="list_directory", description="List immediate files and directories in an approved Windows known folder.", structured_output=True)
    def directory_list(folder: Literal["Downloads", "Documents", "Desktop"],
                       limit: int = Field(default=50, ge=1, le=50),
                       max_entries: int = Field(default=2000, ge=1, le=5000),
                       timeout_seconds: float = Field(default=5.0, ge=0.1, le=10.0)) -> dict[str, Any]:
        return _wire(list_directory(folder=folder, limit=limit, max_entries=max_entries,
                                    timeout_seconds=timeout_seconds))

    @server.tool(name="get_directory_size", description="Measure bounded file sizes in an approved Windows known folder.", structured_output=True)
    def directory_size(folder: Literal["Downloads", "Documents", "Desktop"],
                       recursive: bool = True,
                       max_depth: int = Field(default=2, ge=0, le=3),
                       max_entries: int = Field(default=2000, ge=1, le=5000),
                       timeout_seconds: float = Field(default=5.0, ge=0.1, le=10.0)) -> dict[str, Any]:
        return _wire(get_directory_size(folder=folder, recursive=recursive,
                                        max_depth=max_depth, max_entries=max_entries,
                                        timeout_seconds=timeout_seconds))

    @server.tool(name="get_system_uptime", description="Read Windows boot time and uptime.", structured_output=True)
    def system_uptime() -> dict[str, Any]:
        return _wire(get_system_uptime())

    @server.tool(name="list_services", description="List bounded Windows service names, states and start types.", structured_output=True)
    def services(limit: int = Field(default=30, ge=1, le=50)) -> dict[str, Any]:
        return _wire(list_services(limit=limit))

    return server


def main() -> None:
    # MCP owns stdout. Diagnostics and startup errors belong on stderr.
    create_server().run("stdio")


if __name__ == "__main__":
    main()
