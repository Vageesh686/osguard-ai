"""Bounded Windows inventories used by the approved local diagnostic registry.

PowerShell is used only for fixed, source-controlled read-only queries. User or
model text is never interpolated into a script or passed as an executable.
"""

from __future__ import annotations

import ctypes
import ipaddress
import json
import platform
import re
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

import psutil

try:
    import winreg
except ImportError:  # Tests and documentation can still import this Windows-only module elsewhere.
    winreg = None

from osguard.schemas import ToolExecutionResult
from osguard.tools.windows import _result, _permission_error, get_event_logs, get_service_status


_DEVICE_QUERY = (
    "Get-CimInstance Win32_PnPEntity | Select-Object -First 300 "
    "Name,PNPClass,DeviceID,Status,ConfigManagerErrorCode | ConvertTo-Json -Compress -Depth 3"
)
_PROBLEM_DEVICE_QUERY = (
    "Get-CimInstance Win32_PnPEntity | Where-Object { $_.ConfigManagerErrorCode -ne 0 } | "
    "Select-Object -First 100 Name,PNPClass,DeviceID,Status,ConfigManagerErrorCode | "
    "ConvertTo-Json -Compress -Depth 3"
)
_DRIVER_QUERY = (
    "Get-CimInstance Win32_PnPSignedDriver | Select-Object -First 300 "
    "DeviceName,DeviceClass,DeviceID,DriverProviderName,DriverVersion,DriverDate,IsSigned | "
    "ConvertTo-Json -Compress -Depth 3"
)
_UPDATE_QUERY = (
    "$s = New-Object -ComObject Microsoft.Update.Session; "
    "$h = $s.CreateUpdateSearcher().QueryHistory(0,40); "
    "$h | Select-Object -First 40 Title,Date,ResultCode,HResult | ConvertTo-Json -Compress -Depth 3"
)


def _powershell_path() -> Path:
    """Resolve the system copy, never an executable from PATH or the project."""
    buffer = ctypes.create_unicode_buffer(32768)
    length = ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer))
    if not 0 < length < len(buffer):
        raise OSError("Windows system directory unavailable")
    return Path(buffer.value) / "WindowsPowerShell" / "v1.0" / "powershell.exe"


def _read_inventory(script: str, *, timeout: float = 12.0) -> list[dict[str, Any]]:
    if platform.system() != "Windows":
        raise OSError("Windows inventory unavailable")
    if script not in {_DEVICE_QUERY, _PROBLEM_DEVICE_QUERY, _DRIVER_QUERY, _UPDATE_QUERY}:
        raise ValueError("Unapproved inventory query")
    completed = subprocess.run(
        [str(_powershell_path()), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=timeout, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode:
        detail = completed.stderr[:400]
        if "Access is denied" in detail or "AccessDenied" in detail:
            raise PermissionError("Windows inventory access denied")
        raise RuntimeError("Windows inventory query failed")
    if len(completed.stdout) > 1_000_000:
        raise ValueError("Inventory output exceeded size limit")
    raw = completed.stdout.strip()
    if not raw:
        return []
    parsed = json.loads(raw)
    values = parsed if isinstance(parsed, list) else [parsed]
    if not all(isinstance(value, dict) for value in values):
        raise ValueError("Inventory output was not a list of records")
    return values


def _inventory_failure(name: str, exc: Exception) -> ToolExecutionResult:
    if platform.system() != "Windows":
        status = "unsupported_os"
    elif _permission_error(exc):
        status = "permission_denied"
    elif isinstance(exc, subprocess.TimeoutExpired):
        status = "failed"
    else:
        status = "failed"
    return _result(name, status, "Windows inventory could not be read.", error=type(exc).__name__)


def _device_state(code: Any, status: Any) -> str:
    if code == 0:
        return "healthy" if str(status).casefold() == "ok" else "unknown"
    return {22: "disabled", 24: "disconnected", 28: "missing_driver"}.get(code, "reported_problem") if isinstance(code, int) else "unknown"


def _device_rows(raw: list[dict[str, Any]], *, device_class: str | None, status: str | None,
                 device_id: str | None, problem_only: bool, limit: int) -> tuple[list[dict[str, Any]], int]:
    rows = []
    for item in raw:
        code = item.get("ConfigManagerErrorCode")
        state = _device_state(code, item.get("Status"))
        row = {
            "name": str(item.get("Name") or "Unknown device")[:160],
            "device_class": str(item.get("PNPClass") or "unknown")[:80],
            "device_id": str(item.get("DeviceID") or "")[:300],
            "status": state,
            "windows_status": str(item.get("Status") or "unknown")[:40],
            "problem_code": code if isinstance(code, int) else None,
        }
        if device_class and row["device_class"].casefold() != device_class.casefold():
            continue
        if status and row["status"] != status:
            continue
        if device_id and device_id.casefold() not in row["device_id"].casefold():
            continue
        if problem_only and state == "healthy":
            continue
        rows.append(row)
    return rows[:limit], len(rows)


def _pnputil_problem_devices(problem_only: bool = True) -> list[dict[str, Any]]:
    """Fallback to the documented read-only PnPUtil device inventory."""
    arguments = ["/enum-devices", "/problem"] if problem_only else ["/enum-devices"]
    completed = subprocess.run(
        [str(_powershell_path().parents[2] / "pnputil.exe"), *arguments],
        capture_output=True, text=True, timeout=12.0, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode:
        raise RuntimeError("PnPUtil inventory failed")
    if len(completed.stdout) > 1_000_000:
        raise ValueError("PnPUtil output exceeded size limit")
    records = []
    for block in re.split(r"\r?\n\s*\r?\n", completed.stdout):
        fields = dict(re.findall(r"^([A-Za-z ]+):\s*(.*)$", block, re.M))
        if not fields.get("Instance ID"):
            continue
        code_match = re.match(r"\s*(\d+)", fields.get("Problem Code", ""))
        records.append({
            "Name": fields.get("Device Description") or fields.get("Device Name"),
            "PNPClass": fields.get("Class Name"),
            "DeviceID": fields["Instance ID"],
            "Status": fields.get("Status") or "unknown",
            "ConfigManagerErrorCode": int(code_match.group(1)) if code_match else None,
        })
        if len(records) >= 100:
            break
    if not records and "No devices" not in completed.stdout and "no devices" not in completed.stdout.casefold():
        raise ValueError("PnPUtil output format was not recognized")
    return records


def inspect_problem_devices(*, device_class: str | None = None, status: str | None = None,
                            device_id: str | None = None, problem_only: bool = True,
                            limit: int = 20) -> ToolExecutionResult:
    name = "inspect_problem_devices"
    try:
        source = "pnputil" if problem_only else "cim"
        try:
            raw = _pnputil_problem_devices() if problem_only else _read_inventory(_DEVICE_QUERY)
        except (RuntimeError, subprocess.TimeoutExpired, ValueError):
            raw = _read_inventory(_PROBLEM_DEVICE_QUERY) if problem_only else _pnputil_problem_devices(False)
            source = "cim" if problem_only else "pnputil"
        rows, matched = _device_rows(raw, device_class=device_class, status=status,
                                     device_id=device_id, problem_only=problem_only, limit=limit)
        return _result(name, "success", f"Inspected device inventory; {matched} matching device(s).",
                       data={"devices": rows, "matching_count": matched, "scan_cap_reached": len(raw) >= (100 if problem_only else 300),
                             "display_truncated": matched > limit, "inventory_source": source})
    except Exception as exc:
        return _inventory_failure(name, exc)


def inspect_device_status(*, device_class: str | None = None, status: str | None = None,
                          device_id: str | None = None, problem_only: bool = False,
                          limit: int = 20) -> ToolExecutionResult:
    result = inspect_problem_devices(device_class=device_class, status=status, device_id=device_id,
                                     problem_only=problem_only, limit=limit)
    return result.model_copy(update={"tool_name": "inspect_device_status",
                                     "evidence_id": result.evidence_id.replace("inspect_problem_devices", "inspect_device_status") if result.evidence_id else None})


def inspect_device_drivers(*, device_class: str | None = None, device_id: str | None = None,
                           limit: int = 20) -> ToolExecutionResult:
    name = "inspect_device_drivers"
    try:
        raw = _read_inventory(_DRIVER_QUERY)
        rows = [{"name": str(item.get("DeviceName") or "Unknown device")[:160],
                 "device_class": str(item.get("DeviceClass") or "unknown")[:80],
                 "device_id": str(item.get("DeviceID") or "")[:300],
                 "provider": str(item.get("DriverProviderName") or "")[:160],
                 "driver_version": str(item.get("DriverVersion") or "")[:80],
                 "driver_date": str(item.get("DriverDate") or "")[:80],
                 "is_signed": item.get("IsSigned") if isinstance(item.get("IsSigned"), bool) else None}
                for item in raw]
        if device_class:
            rows = [row for row in rows if row["device_class"].casefold() == device_class.casefold()]
        if device_id:
            rows = [row for row in rows if device_id.casefold() in row["device_id"].casefold()]
        return _result(name, "success", f"Read {len(rows)} matching driver record(s).",
                       data={"drivers": rows[:limit], "matching_count": len(rows),
                             "scan_cap_reached": len(raw) >= 300, "display_truncated": len(rows) > limit})
    except Exception as exc:
        return _inventory_failure(name, exc)


def inspect_network_adapters(*, limit: int = 20) -> ToolExecutionResult:
    name = "inspect_network_adapters"
    if platform.system() != "Windows":
        return _result(name, "unsupported_os", "Windows network adapters are unavailable.")
    try:
        stats = psutil.net_if_stats()
        rows = [{"name": str(alias)[:160], "is_up": bool(item.isup),
                 "speed_mbps": item.speed if item.speed >= 0 else None, "mtu": item.mtu}
                for alias, item in stats.items()]
        return _result(name, "success", "Read network adapter operational status.",
                       data={"adapters": rows[:limit], "display_truncated": len(rows) > limit})
    except Exception as exc:
        return _inventory_failure(name, exc)


def _address_list(value: Any) -> list[str]:
    candidates = value if isinstance(value, list) else re.split(r"[,;\s]+", str(value or ""))
    accepted = []
    for candidate in candidates[:20]:
        try:
            accepted.append(str(ipaddress.ip_address(candidate)))
        except ValueError:
            pass
    return accepted


def _address_scope(value: Any) -> str:
    candidates = value if isinstance(value, list) else [value]
    for candidate in candidates:
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if address.is_link_local:
            return "link_local"
        if address.is_loopback:
            return "loopback"
        if address.is_private:
            return "private"
        return "public"
    return "unknown"


def _native_network_interfaces() -> list[dict[str, Any]]:
    """Use psutil plus read-only TCP/IP interface registry metadata."""
    addresses = psutil.net_if_addrs()
    rows = []
    for alias, items in list(addresses.items())[:64]:
        ipv4 = [item.address for item in items if item.family == socket.AF_INET][:4]
        ipv6 = [item.address.split("%")[0] for item in items if item.family == socket.AF_INET6][:4]
        rows.append({"name": str(alias)[:160], "ipv4": ipv4, "ipv6": ipv6,
                     "ipv4_scope": _address_scope(ipv4), "default_gateway": None,
                     "dns_servers": [], "registry_metadata_available": False})
    if winreg is None:
        return rows
    path = r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as root:
            for index in range(min(winreg.QueryInfoKey(root)[0], 128)):
                try:
                    with winreg.OpenKey(root, winreg.EnumKey(root, index)) as key:
                        def value(field: str) -> Any:
                            try:
                                return winreg.QueryValueEx(key, field)[0]
                            except OSError:
                                return None
                        ips = _address_list(value("IPAddress")) + _address_list(value("DhcpIPAddress"))
                        for row in rows:
                            if not set(ips) & set(row["ipv4"]):
                                continue
                            row["default_gateway"] = (
                                _address_list(value("DefaultGateway")) or
                                _address_list(value("DhcpDefaultGateway")) or [None]
                            )[0]
                            row["dns_servers"] = (
                                _address_list(value("NameServer")) or
                                _address_list(value("DhcpNameServer"))
                            )[:8]
                            row["registry_metadata_available"] = True
                except OSError:
                    continue
    except OSError:
        pass
    return rows


def get_network_configuration(*, limit: int = 20) -> ToolExecutionResult:
    name = "get_network_configuration"
    if platform.system() != "Windows":
        return _result(name, "unsupported_os", "Windows network configuration is unavailable.")
    try:
        rows = _native_network_interfaces()
        return _result(name, "success", "Read local IP addresses; gateway metadata is included when available.",
                       data={"interfaces": rows[:limit], "display_truncated": len(rows) > limit,
                             "inventory_source": "psutil_registry"})
    except Exception as exc:
        return _inventory_failure(name, exc)


def inspect_dns_configuration(*, limit: int = 20) -> ToolExecutionResult:
    name = "inspect_dns_configuration"
    if platform.system() != "Windows":
        return _result(name, "unsupported_os", "Windows DNS configuration is unavailable.")
    try:
        rows = _native_network_interfaces()
        return _result(name, "success", "Read available DNS server metadata; empty values may mean unavailable registry data.",
                       data={"interfaces": rows[:limit], "display_truncated": len(rows) > limit,
                             "inventory_source": "psutil_registry"})
    except Exception as exc:
        return _inventory_failure(name, exc)


_CONNECTIVITY_TARGETS = {"microsoft": ("www.microsoft.com", 443)}


def check_network_connectivity(*, target: str = "microsoft", timeout_seconds: float = 2.0) -> ToolExecutionResult:
    name = "check_network_connectivity"
    if target not in _CONNECTIVITY_TARGETS or not 0.2 <= timeout_seconds <= 3.0:
        return _result(name, "invalid_input", "Only an approved target and bounded timeout are accepted.")
    if platform.system() != "Windows":
        return _result(name, "unsupported_os", "Windows connectivity checks are unavailable.")
    host, port = _CONNECTIVITY_TARGETS[target]
    started = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            pass
        return _result(name, "success", "TCP connection to the approved public test endpoint succeeded.",
                       data={"target": target, "host": host, "port": port,
                             "connected": True, "elapsed_ms": round((time.monotonic() - started) * 1000)})
    except (OSError, TimeoutError) as exc:
        return _result(name, "failed", "TCP connection to the approved public test endpoint failed; local configuration may still be valid.",
                       data={"target": target, "host": host, "port": port, "connected": False}, error=type(exc).__name__)


def get_windows_update_history(*, limit: int = 20, failed_only: bool = False) -> ToolExecutionResult:
    name = "inspect_failed_updates" if failed_only else "get_windows_update_history"
    try:
        raw = _read_inventory(_UPDATE_QUERY)
        rows = [{"title": str(item.get("Title") or "")[:200], "installed_at": str(item.get("Date") or "")[:80],
                 "result_code": item.get("ResultCode"), "hresult": item.get("HResult"),
                 "status": {2: "succeeded", 3: "succeeded_with_errors", 4: "failed", 5: "aborted"}.get(item.get("ResultCode"), "unknown")}
                for item in raw]
        if failed_only:
            rows = [row for row in rows if row["status"] in {"failed", "succeeded_with_errors", "aborted"}]
        return _result(name, "success", f"Read {len(rows)} matching Windows Update history record(s).",
                       data={"updates": rows[:limit], "matching_count": len(rows),
                             "history_window": min(len(raw), 40), "display_truncated": len(rows) > limit})
    except Exception as exc:
        return _inventory_failure(name, exc)


def inspect_failed_updates(*, limit: int = 20) -> ToolExecutionResult:
    return get_windows_update_history(limit=limit, failed_only=True)


def inspect_update_service_status() -> ToolExecutionResult:
    result = get_service_status("wuauserv")
    return result.model_copy(update={"tool_name": "inspect_update_service_status",
                                     "evidence_id": result.evidence_id.replace("get_service_status", "inspect_update_service_status") if result.evidence_id else None})


def inspect_installed_software(*, name: str | None = None, limit: int = 20) -> ToolExecutionResult:
    tool = "inspect_installed_software"
    if platform.system() != "Windows":
        return _result(tool, "unsupported_os", "Installed software inventory is available only on Windows.")
    rows: list[dict[str, str]] = []
    denied = 0
    try:
        paths = (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                 r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall")
        locations = [(winreg.HKEY_LOCAL_MACHINE, p) for p in paths]
        locations.append((winreg.HKEY_CURRENT_USER, paths[0]))
        for hive, path in locations:
            try:
                with winreg.OpenKey(hive, path) as root:
                    count = min(winreg.QueryInfoKey(root)[0], 500)
                    for index in range(count):
                        try:
                            with winreg.OpenKey(root, winreg.EnumKey(root, index)) as key:
                                def value(field: str) -> str:
                                    try:
                                        return str(winreg.QueryValueEx(key, field)[0])[:200]
                                    except OSError:
                                        return ""
                                title = value("DisplayName")
                                if title and (not name or name.casefold() in title.casefold()):
                                    rows.append({"name": title, "version": value("DisplayVersion"),
                                                 "publisher": value("Publisher")})
                        except (PermissionError, OSError):
                            denied += 1
            except (PermissionError, OSError):
                denied += 1
        rows = list({(row["name"], row["version"]): row for row in rows}.values())
        rows.sort(key=lambda row: row["name"].casefold())
        if denied and not rows:
            return _result(tool, "permission_denied", "Installed software inventory was inaccessible.", data={"entries_skipped": denied})
        return _result(tool, "success", "Read installed software names and versions from uninstall registry keys.",
                       data={"applications": rows[:limit], "matching_count": len(rows),
                             "display_truncated": len(rows) > limit, "entries_skipped": denied})
    except Exception as exc:
        return _inventory_failure(tool, exc)


def inspect_application_process(*, name: str, limit: int = 20) -> ToolExecutionResult:
    tool = "inspect_application_process"
    if platform.system() != "Windows":
        return _result(tool, "unsupported_os", "Application process inspection is available only on Windows.")
    rows = []
    denied = 0
    try:
        terms = [part.casefold() for part in re.findall(r"[A-Za-z0-9]+", name) if len(part) >= 4]
        for process in psutil.process_iter(attrs=["pid", "name", "memory_info"]):
            try:
                info = process.info
                process_name = str(info.get("name") or "").casefold()
                if name.casefold() not in process_name and not any(part in process_name for part in terms):
                    continue
                memory = info.get("memory_info")
                rows.append({"pid": int(info["pid"]), "name": str(info.get("name") or "")[:160],
                             "working_set_bytes": int(memory.rss) if memory else None})
                if len(rows) >= limit:
                    break
            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                denied += 1
        return _result(tool, "success", "Read matching process names and working sets; no command lines were inspected.",
                       data={"processes": rows, "processes_skipped": denied})
    except Exception as exc:
        return _inventory_failure(tool, exc)


def inspect_application_errors(*, name: str | None = None, hours_back: int = 48,
                               limit: int = 20) -> ToolExecutionResult:
    tool = "inspect_application_errors"
    result = get_event_logs({"log_name": "Application", "hours_back": hours_back,
                             "event_ids": [1000, 1001], "levels": [1, 2, 3], "max_events": min(100, max(limit * 3, 20))})
    if result.status != "success":
        return result.model_copy(update={"tool_name": tool})
    rows = result.data.get("events", [])
    if name:
        rows = [row for row in rows if name.casefold() in json.dumps(row, ensure_ascii=False).casefold()]
    return _result(tool, "success", f"Read {len(rows)} matching application error event(s).",
                   data={"events": rows[:limit], "matching_count": len(rows),
                         "display_truncated": len(rows) > limit, "queried_event_ids": [1000, 1001]})
