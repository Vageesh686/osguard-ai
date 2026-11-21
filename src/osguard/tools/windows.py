"""Bounded read-only Windows measurements; no shell or mutation interfaces."""

from __future__ import annotations

import ctypes
import platform
import re
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from typing import Any

import psutil

from osguard.privacy import redact_sensitive_text
from osguard.schemas import ToolExecutionResult


_SERVICE_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_ALLOWED_LOGS = {"Application", "System", "Setup"}
_ALLOWED_EVENT_FILTERS = {"log_name", "hours_back", "event_ids", "levels", "max_events"}
_MAX_PROCESS_SCAN = 200
_MAX_DISK_PARTITIONS = 24


def _is_windows() -> bool:
    return platform.system() == "Windows"


def _result(
    name: str,
    status: str,
    summary: str,
    *,
    data: dict[str, Any] | None = None,
    error: str | None = None,
) -> ToolExecutionResult:
    evidence_id = f"tool:{name}:{uuid.uuid4().hex}" if status == "success" else None
    return ToolExecutionResult(
        tool_name=name,
        status=status,
        summary=summary,
        data=data or {},
        evidence_id=evidence_id,
        error=error,
    )


def _permission_error(exc: BaseException) -> bool:
    return isinstance(exc, PermissionError) or getattr(exc, "winerror", None) == 5


def get_system_info() -> ToolExecutionResult:
    """Read Windows version/build and architecture without machine identifiers."""
    if not _is_windows():
        return _result("get_system_info", "unsupported_os", "System metadata is available only on Windows.")
    try:
        version = platform.win32_ver()
        native = sys.getwindowsversion() if hasattr(sys, "getwindowsversion") else None
        build = str(getattr(native, "build", "") or version[1] or platform.version()) or None
        major = getattr(native, "major", None)
        release = getattr(native, "release", None) or platform.release()
        if major == 10 and build and build.isdigit():
            os_name = "Windows 11" if int(build) >= 22000 else "Windows 10"
        else:
            os_name = f"Windows {release}" if release else "Windows"
        data = {
            "os_name": os_name,
            "os_version": version[0] or release or None,
            "os_build": build,
            "architecture": platform.machine() or None,
            "service_pack": version[2] or None,
        }
        return _result("get_system_info", "success", "Read basic Windows version and architecture.", data=data)
    except Exception as exc:
        return _result("get_system_info", "failed", "Windows system information could not be read.", error=type(exc).__name__)


def get_process_stats(*, limit: int = 10, sample_seconds: float = 0.15) -> ToolExecutionResult:
    """Sample system CPU and a bounded set of process CPU/memory values."""
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
        return _result("get_process_stats", "invalid_input", "limit must be an integer from 1 to 50.")
    if not isinstance(sample_seconds, (int, float)) or isinstance(sample_seconds, bool) or not 0.05 <= sample_seconds <= 0.5:
        return _result("get_process_stats", "invalid_input", "sample_seconds must be from 0.05 to 0.5.")
    if not _is_windows():
        return _result("get_process_stats", "unsupported_os", "Process snapshots are enabled only on Windows.")
    try:
        sampled: list[tuple[Any, int, str]] = []
        denied_during_scan = 0
        for process in psutil.process_iter(attrs=["pid", "name"]):
            if len(sampled) >= _MAX_PROCESS_SCAN:
                break
            try:
                info = process.info
                name = str(info.get("name") or "unknown")[:120]
                process.cpu_percent(interval=None)
                sampled.append((process, int(info.get("pid") or process.pid), name))
            except psutil.AccessDenied:
                denied_during_scan += 1
                continue
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
        time.sleep(float(sample_seconds))
        system_cpu = psutil.cpu_percent(interval=None)
        rows: list[dict[str, Any]] = []
        for process, pid, name in sampled:
            try:
                rows.append(
                    {
                        "pid": pid,
                        "name": name,
                        "cpu_percent": round(float(process.cpu_percent(interval=None)), 1),
                        "memory_mb": round(process.memory_info().rss / (1024 * 1024), 1),
                    }
                )
            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
        rows.sort(key=lambda row: (row["cpu_percent"], row["memory_mb"]), reverse=True)
        data = {
            "system_cpu_percent": round(float(system_cpu), 1),
            "sample_window_seconds": float(sample_seconds),
            "processes_scanned": len(sampled),
            "processes_skipped_access_denied": denied_during_scan,
            "processes": rows[:limit],
        }
        if not sampled and denied_during_scan:
            return _result(
                "get_process_stats", "permission_denied",
                "No process statistics were accessible.", data=data,
            )
        return _result("get_process_stats", "success", "Sampled system CPU and bounded process statistics.", data=data)
    except Exception as exc:
        status = "permission_denied" if _permission_error(exc) else "failed"
        return _result("get_process_stats", status, "Process statistics could not be read.", error=type(exc).__name__)


def get_memory_info() -> ToolExecutionResult:
    """Read total, available and used physical memory."""
    if not _is_windows():
        return _result("get_memory_info", "unsupported_os", "Memory diagnostics are enabled only on Windows.")
    try:
        memory = psutil.virtual_memory()
        data = {
            "total_bytes": int(memory.total),
            "available_bytes": int(memory.available),
            "used_bytes": int(memory.used),
            "utilization_percent": round(float(memory.percent), 1),
        }
        return _result("get_memory_info", "success", "Read physical memory capacity and utilization.", data=data)
    except Exception as exc:
        status = "permission_denied" if _permission_error(exc) else "failed"
        return _result("get_memory_info", status, "Memory information could not be read.", error=type(exc).__name__)


def get_disk_info() -> ToolExecutionResult:
    """Read capacity and filesystem type for a bounded number of local volumes."""
    if not _is_windows():
        return _result("get_disk_info", "unsupported_os", "Disk diagnostics are enabled only on Windows.")
    try:
        volumes: list[dict[str, Any]] = []
        denied_volumes = 0
        for partition in psutil.disk_partitions(all=False):
            if len(volumes) >= _MAX_DISK_PARTITIONS:
                break
            device = str(partition.device or "")
            if device.startswith("\\\\"):
                continue
            try:
                usage = psutil.disk_usage(partition.mountpoint)
            except (PermissionError, psutil.AccessDenied):
                denied_volumes += 1
                continue
            except OSError:
                continue
            volumes.append(
                {
                    "mountpoint": str(partition.mountpoint)[:120],
                    "filesystem": str(partition.fstype or "unknown")[:40],
                    "total_bytes": int(usage.total),
                    "free_bytes": int(usage.free),
                    "used_percent": round(float(usage.percent), 1),
                }
            )
        data = {
            "volumes": volumes,
            "volume_count": len(volumes),
            "volumes_skipped_access_denied": denied_volumes,
        }
        if not volumes and denied_volumes:
            return _result("get_disk_info", "permission_denied", "No local disk volumes were accessible.", data=data)
        return _result("get_disk_info", "success", "Read capacity for accessible local volumes.", data=data)
    except Exception as exc:
        status = "permission_denied" if _permission_error(exc) else "failed"
        return _result("get_disk_info", status, "Disk information could not be read.", error=type(exc).__name__)


def get_service_status(service_name: str) -> ToolExecutionResult:
    """Read one exact Windows service name; wildcards and mutations are absent."""
    if not isinstance(service_name, str) or not _SERVICE_NAME.fullmatch(service_name):
        return _result(
            "get_service_status", "invalid_input",
            "service_name must be one exact service name using letters, digits, dot, underscore, or hyphen.",
        )
    if not _is_windows():
        return _result("get_service_status", "unsupported_os", "Windows service status is available only on Windows.")
    try:
        service = psutil.win_service_get(service_name)
        details = service.as_dict()
        data = {
            "service_name": service_name,
            "status": str(details.get("status") or "unknown"),
            "start_type": str(details.get("start_type") or "unknown"),
            "display_name": str(details.get("display_name") or "")[:160],
        }
        return _result("get_service_status", "success", "Read the requested Windows service status.", data=data)
    except psutil.NoSuchProcess:
        return _result("get_service_status", "not_found", "The requested Windows service was not found.")
    except (psutil.AccessDenied, PermissionError) as exc:
        return _result("get_service_status", "permission_denied", "Access to the requested service was denied.", error=type(exc).__name__)
    except Exception as exc:
        return _result("get_service_status", "failed", "The requested service status could not be read.", error=type(exc).__name__)


def _event_xpath(filters: dict[str, Any]) -> str:
    conditions = [f"TimeCreated[timediff(@SystemTime) <= {filters['hours_back'] * 3_600_000}]"]
    if filters["levels"]:
        levels = " or ".join(f"Level={value}" for value in filters["levels"])
        conditions.append(f"({levels})")
    if filters["event_ids"]:
        identifiers = " or ".join(f"EventID={value}" for value in filters["event_ids"])
        conditions.append(f"({identifiers})")
    return "*[System[" + " and ".join(conditions) + "]]"


class _WindowsEventLogAPI:
    """Small ctypes wrapper around the Windows Event Log read/query APIs."""

    EVT_QUERY_CHANNEL_PATH = 0x1
    EVT_QUERY_FORWARD_DIRECTION = 0x100
    EVT_RENDER_EVENT_XML = 1
    ERROR_NO_MORE_ITEMS = 259
    ERROR_INSUFFICIENT_BUFFER = 122

    def __init__(self) -> None:
        if not _is_windows():
            raise OSError("Windows Event Log APIs are unavailable")
        self._dll = ctypes.WinDLL("wevtapi", use_last_error=True)
        self._dll.EvtQuery.restype = ctypes.c_void_p
        self._dll.EvtQuery.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
        self._dll.EvtNext.restype = ctypes.c_int
        self._dll.EvtNext.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_uint)]
        self._dll.EvtRender.restype = ctypes.c_int
        self._dll.EvtRender.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint)]
        self._dll.EvtClose.restype = ctypes.c_int
        self._dll.EvtClose.argtypes = [ctypes.c_void_p]

    def _render_event_xml(self, event_handle: int) -> str:
        used = ctypes.c_uint(0)
        properties = ctypes.c_uint(0)
        self._dll.EvtRender(None, event_handle, self.EVT_RENDER_EVENT_XML, 0, None, ctypes.byref(used), ctypes.byref(properties))
        error = ctypes.get_last_error()
        if error != self.ERROR_INSUFFICIENT_BUFFER or used.value > 256_000:
            raise ctypes.WinError(error)
        buffer = ctypes.create_string_buffer(used.value)
        if not self._dll.EvtRender(None, event_handle, self.EVT_RENDER_EVENT_XML, used.value, buffer, ctypes.byref(used), ctypes.byref(properties)):
            raise ctypes.WinError(ctypes.get_last_error())
        return buffer.raw[: used.value].decode("utf-16-le", errors="replace").rstrip("\x00")

    def query(self, log_name: str, xpath: str, max_events: int) -> list[dict[str, Any]]:
        query = self._dll.EvtQuery(None, log_name, xpath, self.EVT_QUERY_CHANNEL_PATH)
        if not query:
            raise ctypes.WinError(ctypes.get_last_error())
        events: list[dict[str, Any]] = []
        try:
            while len(events) < max_events:
                capacity = min(10, max_events - len(events))
                handles = (ctypes.c_void_p * capacity)()
                returned = ctypes.c_uint(0)
                ok = self._dll.EvtNext(query, capacity, handles, 500, 0, ctypes.byref(returned))
                if not ok:
                    error = ctypes.get_last_error()
                    if error == self.ERROR_NO_MORE_ITEMS:
                        break
                    raise ctypes.WinError(error)
                if returned.value == 0:
                    break
                for index in range(returned.value):
                    event_handle = handles[index]
                    try:
                        events.append(_parse_event_xml(self._render_event_xml(event_handle)))
                    finally:
                        self._dll.EvtClose(event_handle)
        finally:
            self._dll.EvtClose(query)
        return events


def _parse_event_xml(xml_text: str) -> dict[str, Any]:
    root = ET.fromstring(xml_text)
    system = root.find(".//{*}System")
    provider = system.find("{*}Provider") if system is not None else None
    event_id = system.find("{*}EventID") if system is not None else None
    level = system.find("{*}Level") if system is not None else None
    created = system.find("{*}TimeCreated") if system is not None else None
    record = system.find("{*}EventRecordID") if system is not None else None
    data_fields = []
    for item in root.findall(".//{*}EventData/{*}Data")[:8]:
        value = (item.text or "").strip()
        if value:
            data_fields.append(
                {
                    "name": str(item.attrib.get("Name", ""))[:80],
                    "value": redact_sensitive_text(value)[:300],
                }
            )
    return {
        "provider": (provider.attrib.get("Name") if provider is not None else None),
        "event_id": int(event_id.text) if event_id is not None and (event_id.text or "").isdigit() else None,
        "level": int(level.text) if level is not None and (level.text or "").isdigit() else None,
        "time_created": created.attrib.get("SystemTime") if created is not None else None,
        "record_id": int(record.text) if record is not None and (record.text or "").isdigit() else None,
        "data": data_fields,
    }


def _validate_event_filters(filters: dict[str, Any] | None) -> tuple[dict[str, Any] | None, str | None]:
    raw = {} if filters is None else filters
    if not isinstance(raw, dict) or set(raw) - _ALLOWED_EVENT_FILTERS:
        return None, "filters must use only log_name, hours_back, event_ids, levels, and max_events."
    log_name = raw.get("log_name", "System")
    hours = raw.get("hours_back", 24)
    event_ids = raw.get("event_ids", [])
    levels = raw.get("levels", [1, 2, 3])
    max_events = raw.get("max_events", 20)
    if not isinstance(log_name, str) or log_name not in _ALLOWED_LOGS:
        return None, "log_name must be Application, System, or Setup."
    if not isinstance(hours, int) or isinstance(hours, bool) or not 1 <= hours <= 168:
        return None, "hours_back must be an integer from 1 to 168."
    if not isinstance(max_events, int) or isinstance(max_events, bool) or not 1 <= max_events <= 100:
        return None, "max_events must be an integer from 1 to 100."
    if not isinstance(event_ids, list) or len(event_ids) > 20 or any(
        not isinstance(item, int) or isinstance(item, bool) or not 0 <= item <= 65535 for item in event_ids
    ):
        return None, "event_ids must contain at most 20 integer event IDs from 0 to 65535."
    if not isinstance(levels, list) or len(levels) > 5 or any(
        not isinstance(item, int) or isinstance(item, bool) or not 1 <= item <= 5 for item in levels
    ):
        return None, "levels must contain event levels from 1 to 5."
    return {
        "log_name": log_name,
        "hours_back": hours,
        "event_ids": list(dict.fromkeys(event_ids)),
        "levels": list(dict.fromkeys(levels)),
        "max_events": max_events,
    }, None


def get_event_logs(
    filters: dict[str, Any] | None = None,
    *,
    _api: Any | None = None,
) -> ToolExecutionResult:
    """Read only recent events from a small allowlist of non-security logs."""
    validated, problem = _validate_event_filters(filters)
    if problem:
        return _result("get_event_logs", "invalid_input", problem)
    if not _is_windows():
        return _result("get_event_logs", "unsupported_os", "Windows Event Log access is available only on Windows.")
    try:
        api = _api or _WindowsEventLogAPI()
        events = api.query(
            validated["log_name"],
            _event_xpath(validated),
            validated["max_events"],
        )
        return _result(
            "get_event_logs", "success", f"Read {len(events)} event(s) from {validated['log_name']}.",
            data={"log_name": validated["log_name"], "events": events[: validated["max_events"]], "count": len(events[: validated["max_events"]])},
        )
    except Exception as exc:
        if _permission_error(exc):
            return _result("get_event_logs", "permission_denied", "Access to the requested event log was denied.", error=type(exc).__name__)
        if getattr(exc, "winerror", None) in {15007, 15011}:
            return _result("get_event_logs", "not_found", "The requested event log or query result was not found.", error=type(exc).__name__)
        status = "unsupported_os" if isinstance(exc, OSError) and "unavailable" in str(exc).casefold() else "failed"
        return _result("get_event_logs", status, "Windows event records could not be read.", error=type(exc).__name__)
