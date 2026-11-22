"""Deterministic read-only Windows diagnostic capability fixtures."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from mcp import Client

from osguard.context import select_read_only_tools, select_follow_up_tools
from osguard.mcp.server import create_server
from osguard.mcp.client import collect_mcp_async
from osguard.schemas import OSSubsystem, ProblemType, RequestIntent, SpecialistName, SupervisorClassification, ToolExecutionResult
from osguard.state import make_initial_state
from osguard.tools import extended
from osguard.tools.registry import validate_arguments
from osguard.tools.windows import _event_xpath, _validate_event_filters
from osguard.privacy import redact_sensitive_text


def _state(request: str, subsystem: OSSubsystem, problem: ProblemType = ProblemType.UNKNOWN):
    state = make_initial_state(request)
    state["classification"] = SupervisorClassification(
        intent=RequestIntent.DIAGNOSE, problem_type=problem,
        os_subsystems=[subsystem], selected_specialists=[SpecialistName.DIAGNOSTIC],
    )
    state["selected_specialists"] = [SpecialistName.DIAGNOSTIC]
    return state


def test_driver_problem_codes_and_follow_up(monkeypatch):
    monkeypatch.setattr(extended, "_pnputil_problem_devices", lambda: [
        {"Name": "Healthy device", "PNPClass": "Net", "DeviceID": "PCI\\HEALTHY", "Status": "OK", "ConfigManagerErrorCode": 0},
        {"Name": "Missing driver", "PNPClass": "Net", "DeviceID": "PCI\\MISSING", "Status": "Error", "ConfigManagerErrorCode": 28},
        {"Name": "Disabled adapter", "PNPClass": "Net", "DeviceID": "PCI\\OFF", "Status": "Error", "ConfigManagerErrorCode": 22},
        {"Name": "Uncertain adapter", "PNPClass": "Net", "DeviceID": "PCI\\UNKNOWN", "Status": "Unknown", "ConfigManagerErrorCode": None},
    ])
    result = extended.inspect_problem_devices(limit=10)
    assert result.status == "success" and result.evidence_id
    assert [item["status"] for item in result.data["devices"]] == ["missing_driver", "disabled", "unknown"]
    assert all(item["problem_code"] != 0 for item in result.data["devices"])
    monkeypatch.setattr(extended, "_read_inventory", lambda _script: [
        {"Name": "Healthy device", "PNPClass": "Net", "DeviceID": "PCI\\HEALTHY",
         "Status": "OK", "ConfigManagerErrorCode": 0},
    ])
    healthy = extended.inspect_device_status()
    assert healthy.data["devices"][0]["status"] == "healthy"
    state = _state("Are there any driver problems?", OSSubsystem.DEVICES_DRIVERS)
    assert select_read_only_tools(state)[0][0] == "inspect_problem_devices"
    assert select_follow_up_tools(state, [result]) == [("inspect_device_drivers", {"limit": 20})]


def test_driver_inventory_partial_and_access_denied(monkeypatch):
    monkeypatch.setattr(extended, "_pnputil_problem_devices", lambda: [
        {"Name": f"Device {index}", "PNPClass": "Net", "DeviceID": f"PCI\\{index}",
         "Status": "Error", "ConfigManagerErrorCode": 10} for index in range(100)
    ])
    result = extended.inspect_problem_devices(limit=5)
    assert len(result.data["devices"]) == 5
    assert result.data["scan_cap_reached"] and result.data["display_truncated"]
    def denied():
        raise PermissionError("fixture")
    monkeypatch.setattr(extended, "_pnputil_problem_devices", denied)
    assert extended.inspect_problem_devices().status == "permission_denied"
    def cim_denied(_script):
        raise PermissionError("fixture")
    monkeypatch.setattr(extended, "_read_inventory", cim_denied)
    assert extended.inspect_device_status().status == "permission_denied"


def test_driver_metadata_and_filters(monkeypatch):
    monkeypatch.setattr(extended, "_read_inventory", lambda _script: [
        {"DeviceName": "Ethernet", "DeviceClass": "Net", "DeviceID": "PCI\\1",
         "DriverProviderName": "Vendor", "DriverVersion": "1.2", "DriverDate": "2025-01-01"},
        {"DeviceName": "Other", "DeviceClass": "USB", "DeviceID": "USB\\1"},
    ])
    result = extended.inspect_device_drivers(device_class="Net")
    assert result.data["drivers"][0]["driver_version"] == "1.2"
    assert result.data["matching_count"] == 1
    assert validate_arguments("inspect_problem_devices", {"device_class": "Net"})["device_class"] == "Net"
    for name, arguments in (("inspect_problem_devices", {"device_id": "$(whoami)"}),
                            ("inspect_device_drivers", {"limit": 1000}),
                            ("execute_command", {})):
        try:
            validate_arguments(name, arguments)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Unsafe arguments accepted by {name}")


def test_network_status_configuration_dns_and_selection(monkeypatch):
    monkeypatch.setattr(extended.platform, "system", lambda: "Windows")
    monkeypatch.setattr(extended.psutil, "net_if_stats", lambda: {
        "Ethernet": SimpleNamespace(isup=True, speed=1000, mtu=1500),
        "Wi-Fi": SimpleNamespace(isup=False, speed=0, mtu=1500),
    })
    adapters = extended.inspect_network_adapters()
    assert [item["is_up"] for item in adapters.data["adapters"]] == [True, False]
    monkeypatch.setattr(extended, "_native_network_interfaces", lambda: [
        {"name": "Ethernet", "ipv4": ["192.0.2.2"], "ipv4_scope": "private",
         "default_gateway": "192.0.2.1", "dns_servers": ["192.0.2.53"],
         "registry_metadata_available": True},
    ])
    assert extended.get_network_configuration().data["interfaces"][0]["default_gateway"] == "192.0.2.1"
    assert extended.inspect_dns_configuration().data["interfaces"][0]["dns_servers"] == ["192.0.2.53"]
    wifi = _state("Why is my Wi-Fi not working?", OSSubsystem.NETWORKING, ProblemType.NETWORKING)
    assert [name for name, _ in select_read_only_tools(wifi)][:2] == ["inspect_network_adapters", "get_network_configuration"]
    dns = _state("Which DNS servers am I using?", OSSubsystem.NETWORKING, ProblemType.NETWORKING)
    assert select_read_only_tools(dns)[0][0] == "inspect_dns_configuration"


def test_unspecified_dependency_does_not_trigger_host_software_inventory():
    state = _state("High CPU usage and a missing Runtime dependency", OSSubsystem.SOFTWARE_DEPENDENCIES)
    assert "inspect_installed_software" not in [name for name, _ in select_read_only_tools(state)]


def test_network_probe_rejects_unapproved_target_and_records_timeout(monkeypatch):
    monkeypatch.setattr(extended.platform, "system", lambda: "Windows")
    assert extended.check_network_connectivity(target="example.org").status == "invalid_input"
    try:
        validate_arguments("check_network_connectivity", {"target": "example.org"})
    except ValueError:
        pass
    else:
        raise AssertionError("Unapproved target accepted")
    calls = []
    def timeout(address, timeout):
        calls.append((address, timeout))
        raise TimeoutError()
    monkeypatch.setattr(extended.socket, "create_connection", timeout)
    result = extended.check_network_connectivity(timeout_seconds=0.5)
    assert result.status == "failed" and result.data["connected"] is False
    assert result.evidence_id is None
    assert calls == [(("www.microsoft.com", 443), 0.5)]


def test_update_history_success_failure_and_unavailable(monkeypatch):
    monkeypatch.setattr(extended, "_read_inventory", lambda _script: [
        {"Title": "Successful update", "Date": "2026-01-01", "ResultCode": 2, "HResult": 0},
        {"Title": "Failed update", "Date": "2026-01-02", "ResultCode": 4, "HResult": -1},
    ])
    assert [item["status"] for item in extended.get_windows_update_history().data["updates"]] == ["succeeded", "failed"]
    failed = extended.inspect_failed_updates()
    assert [item["title"] for item in failed.data["updates"]] == ["Failed update"]
    state = _state("Did Windows updates fail recently?", OSSubsystem.SYSTEM_CONFIGURATION)
    assert select_read_only_tools(state)[0][0] == "inspect_failed_updates"
    monkeypatch.setattr(extended, "_read_inventory", lambda _script: [])
    assert extended.get_windows_update_history().data["updates"] == []
    def denied(_script):
        raise PermissionError("fixture")
    monkeypatch.setattr(extended, "_read_inventory", denied)
    assert extended.inspect_failed_updates().status == "permission_denied"


def test_software_process_and_error_evidence(monkeypatch):
    monkeypatch.setattr(extended.platform, "system", lambda: "Windows")
    class FakeKey:
        def __enter__(self): return self
        def __exit__(self, *_args): return None
    class Registry:
        HKEY_LOCAL_MACHINE = 1
        HKEY_CURRENT_USER = 2
        def OpenKey(self, *_args): return FakeKey()
        def QueryInfoKey(self, _key): return (1, 0, 0)
        def EnumKey(self, _key, _index): return "fixture"
        def QueryValueEx(self, _key, name):
            return {"DisplayName": "VS Code", "DisplayVersion": "1.2", "Publisher": "Microsoft"}[name], 1
    monkeypatch.setattr(extended, "winreg", Registry())
    software = extended.inspect_installed_software(name="VS Code")
    assert software.data["applications"] == [{"name": "VS Code", "version": "1.2", "publisher": "Microsoft"}]
    monkeypatch.setattr(extended.psutil, "process_iter", lambda attrs: [
        SimpleNamespace(info={"pid": 123, "name": "Code.exe", "memory_info": SimpleNamespace(rss=1048576)})
    ])
    assert extended.inspect_application_process(name="VS Code").data["processes"][0]["working_set_bytes"] == 1048576
    monkeypatch.setattr(extended, "get_event_logs", lambda _filters: ToolExecutionResult(
        tool_name="get_event_logs", status="success", summary="fixture", evidence_id="tool:get_event_logs:fixture",
        data={"events": [{"event_id": 1000, "data": [{"value": "Code.exe crashed"}]},
                         {"event_id": 1000, "data": [{"value": "Other.exe crashed"}]}]},
    ))
    errors = extended.inspect_application_errors(name="Code")
    assert errors.status == "success" and len(errors.data["events"]) == 1


def test_event_provider_filter_and_mcp_discovery():
    validated, error = _validate_event_filters({"provider_name": "Application Error", "max_events": 10})
    assert error is None and "Provider[@Name='Application Error']" in _event_xpath(validated)
    assert _validate_event_filters({"provider_name": "X'] | *"})[1] is not None
    async def discover():
        async with Client(create_server()) as client:
            tools = {tool.name for tool in (await client.list_tools()).tools}
            assert {"inspect_problem_devices", "inspect_network_adapters", "inspect_failed_updates",
                    "inspect_installed_software", "inspect_application_errors"} <= tools
            assert "execute_command" not in tools and "install_driver" not in tools
    asyncio.run(discover())


def test_documented_read_only_fallbacks_keep_partial_status_explicit(monkeypatch):
    monkeypatch.setattr(extended, "_pnputil_problem_devices", lambda: [
        {"Name": "Adapter", "PNPClass": "Net", "DeviceID": "PCI\\1",
         "Status": "Problem", "ConfigManagerErrorCode": 28},
    ])
    device = extended.inspect_problem_devices()
    assert device.status == "success" and device.data["inventory_source"] == "pnputil"
    assert device.data["devices"][0]["status"] == "missing_driver"
    monkeypatch.setattr(extended, "_native_network_interfaces", lambda: [
        {"name": "Ethernet", "ipv4": ["192.0.2.2"], "ipv4_scope": "private",
         "default_gateway": None, "dns_servers": [], "registry_metadata_available": False},
    ])
    config = extended.get_network_configuration()
    dns = extended.inspect_dns_configuration()
    assert config.data["inventory_source"] == dns.data["inventory_source"] == "psutil_registry"
    assert config.data["interfaces"][0]["default_gateway"] is None
    assert dns.data["interfaces"][0]["registry_metadata_available"] is False


def test_private_network_addresses_are_redacted_before_model_prompt():
    text = '{"ipv4": "192.168.1.20", "ipv6": "fe80::1", "dns_servers": ["10.0.0.1"], "url": "https://learn.microsoft.com/en-us/windows"}'
    redacted = redact_sensitive_text(text)
    assert "192.168.1.20" not in redacted and "10.0.0.1" not in redacted and "fe80::1" not in redacted
    assert "https://learn.microsoft.com/en-us/windows" in redacted
    assert redact_sensitive_text("Invalid address 999.999.999.999")


def test_pnputil_fallback_uses_fixed_read_only_arguments(monkeypatch):
    calls = []
    monkeypatch.setattr(extended, "_powershell_path", lambda: Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"))
    def run(arguments, **options):
        calls.append((arguments, options))
        return SimpleNamespace(returncode=0, stdout=(
            "Instance ID: PCI\\VEN_1234\nDevice Description: Fixture adapter\n"
            "Class Name: Net\nStatus: Problem\nProblem Code: 28 (0x1C)\n\n"
        ), stderr="")
    monkeypatch.setattr(extended.subprocess, "run", run)
    result = extended._pnputil_problem_devices()
    assert result[0]["ConfigManagerErrorCode"] == 28
    assert calls[0][0][1:] == ["/enum-devices", "/problem"]
    assert calls[0][1]["check"] is False and calls[0][1]["timeout"] == 12.0
    assert "shell" not in calls[0][1]


def test_new_mcp_tool_invocation_preserves_evidence_and_skips_duplicate(monkeypatch):
    from osguard.mcp import server as server_module
    calls = []
    def fixture(**kwargs):
        calls.append(kwargs)
        return ToolExecutionResult(
            tool_name="inspect_problem_devices", status="success", summary="Fixture inventory",
            data={"devices": [{"name": "Fixture device", "problem_code": 28}]},
            evidence_id="tool:inspect_problem_devices:fixture",
        )
    monkeypatch.setattr(server_module, "inspect_problem_devices", fixture)
    async def collect():
        server = create_server()
        return await collect_mcp_async(
            lambda _available: [("inspect_problem_devices", {}), ("inspect_problem_devices", {})],
            lambda _results: [("inspect_problem_devices", {})],
            client_factory=lambda: Client(server),
        )
    batch = asyncio.run(collect())
    assert len(calls) == 1
    assert len(batch.results) == 1 and batch.results[0].backend == "mcp"
    assert batch.results[0].evidence_id == "tool:inspect_problem_devices:fixture"
