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
from osguard.tools.extended import (
    inspect_problem_devices, inspect_device_status, inspect_device_drivers,
    inspect_network_adapters, get_network_configuration, inspect_dns_configuration,
    check_network_connectivity, get_windows_update_history, inspect_failed_updates,
    inspect_update_service_status, inspect_installed_software,
    inspect_application_process, inspect_application_errors,
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

    @server.tool(name="inspect_problem_devices", description="Inspect Windows Plug and Play devices with reported problem codes; a nonzero code alone does not prove a driver fault.", structured_output=True)
    def problem_devices(device_class: str | None = None, status: str | None = None,
                        device_id: str | None = None, problem_only: bool = True,
                        limit: int = Field(default=20, ge=1, le=50)) -> dict[str, Any]:
        return _wire(inspect_problem_devices(device_class=device_class, status=status, device_id=device_id,
                                             problem_only=problem_only, limit=limit))

    @server.tool(name="inspect_device_status", description="Inspect bounded Windows device status and Configuration Manager problem codes.", structured_output=True)
    def device_status(device_class: str | None = None, status: str | None = None,
                      device_id: str | None = None, problem_only: bool = False,
                      limit: int = Field(default=20, ge=1, le=50)) -> dict[str, Any]:
        return _wire(inspect_device_status(device_class=device_class, status=status, device_id=device_id,
                                           problem_only=problem_only, limit=limit))

    @server.tool(name="inspect_device_drivers", description="Read bounded signed-driver inventory with provider, version and date; never change drivers.", structured_output=True)
    def device_drivers(device_class: str | None = None, device_id: str | None = None,
                       limit: int = Field(default=20, ge=1, le=50)) -> dict[str, Any]:
        return _wire(inspect_device_drivers(device_class=device_class, device_id=device_id, limit=limit))

    @server.tool(name="inspect_network_adapters", description="Read network adapter operational status and link speed.", structured_output=True)
    def network_adapters(limit: int = Field(default=20, ge=1, le=50)) -> dict[str, Any]:
        return _wire(inspect_network_adapters(limit=limit))

    @server.tool(name="get_network_configuration", description="Read local IP addresses and default gateways.", structured_output=True)
    def network_configuration(limit: int = Field(default=20, ge=1, le=50)) -> dict[str, Any]:
        return _wire(get_network_configuration(limit=limit))

    @server.tool(name="inspect_dns_configuration", description="Read configured DNS server addresses.", structured_output=True)
    def dns_configuration(limit: int = Field(default=20, ge=1, le=50)) -> dict[str, Any]:
        return _wire(inspect_dns_configuration(limit=limit))

    @server.tool(name="check_network_connectivity", description="Make one bounded TCP connection only to the approved Microsoft test endpoint.", structured_output=True)
    def connectivity(target: Literal["microsoft"] = "microsoft",
                     timeout_seconds: float = Field(default=2.0, ge=0.2, le=3.0)) -> dict[str, Any]:
        return _wire(check_network_connectivity(target=target, timeout_seconds=timeout_seconds))

    @server.tool(name="get_windows_update_history", description="Read the latest local Windows Update installation history without starting a scan.", structured_output=True)
    def update_history(limit: int = Field(default=20, ge=1, le=50)) -> dict[str, Any]:
        return _wire(get_windows_update_history(limit=limit))

    @server.tool(name="inspect_failed_updates", description="Read failed or aborted items in the latest local Windows Update history.", structured_output=True)
    def failed_updates(limit: int = Field(default=20, ge=1, le=50)) -> dict[str, Any]:
        return _wire(inspect_failed_updates(limit=limit))

    @server.tool(name="inspect_update_service_status", description="Read Windows Update service status without starting or stopping it.", structured_output=True)
    def update_service() -> dict[str, Any]:
        return _wire(inspect_update_service_status())

    @server.tool(name="inspect_installed_software", description="Read application name, version and publisher from uninstall registry keys; never use Win32_Product.", structured_output=True)
    def installed_software(name: str | None = None, limit: int = Field(default=20, ge=1, le=50)) -> dict[str, Any]:
        return _wire(inspect_installed_software(name=name, limit=limit))

    @server.tool(name="inspect_application_process", description="Find matching running process names and working sets without command lines.", structured_output=True)
    def application_process(name: str, limit: int = Field(default=20, ge=1, le=50)) -> dict[str, Any]:
        return _wire(inspect_application_process(name=name, limit=limit))

    @server.tool(name="inspect_application_errors", description="Read recent Application Error and Windows Error Reporting events, optionally matched by application name.", structured_output=True)
    def application_errors(name: str | None = None, hours_back: int = Field(default=48, ge=1, le=168),
                           limit: int = Field(default=20, ge=1, le=50)) -> dict[str, Any]:
        return _wire(inspect_application_errors(name=name, hours_back=hours_back, limit=limit))

    return server


def main() -> None:
    # MCP owns stdout. Diagnostics and startup errors belong on stderr.
    create_server().run("stdio")


if __name__ == "__main__":
    main()
