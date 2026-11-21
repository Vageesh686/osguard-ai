"""Windows diagnostic tool tests use deterministic psutil/Event Log fixtures."""

from types import SimpleNamespace

import psutil
import pytest

from osguard.tools import windows


def _windows(monkeypatch):
    monkeypatch.setattr(windows.platform, "system", lambda: "Windows")


def test_system_info_reports_version_build_and_architecture_without_identity(monkeypatch):
    _windows(monkeypatch)
    monkeypatch.setattr(windows.platform, "win32_ver", lambda: ("11", "10.0.22631", ""))
    monkeypatch.setattr(windows.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(
        windows.sys,
        "getwindowsversion",
        lambda: SimpleNamespace(major=10, build=22631, release="10"),
        raising=False,
    )

    result = windows.get_system_info()

    assert result.status == "success"
    assert result.data["os_name"] == "Windows 11"
    assert result.data["os_build"] == "22631"
    assert result.data["architecture"] == "AMD64"
    assert "hostname" not in result.data and "username" not in result.data
    assert result.evidence_id.startswith("tool:get_system_info:")


def test_process_snapshot_is_bounded_and_reports_cpu_memory(monkeypatch):
    _windows(monkeypatch)

    class Process:
        pid = 34
        info = {"pid": 34, "name": "sample.exe"}

        def __init__(self):
            self.cpu_calls = iter((0.0, 18.5))

        def cpu_percent(self, interval=None):
            assert interval is None
            return next(self.cpu_calls)

        def memory_info(self):
            return SimpleNamespace(rss=1024 * 1024 * 32)

    process = Process()
    monkeypatch.setattr(windows.psutil, "process_iter", lambda **_kwargs: [process])
    # psutil's first timed/priming sample is represented by the process mock;
    # the implementation takes one system sample after its bounded delay.
    cpu_values = iter((7.5,))
    monkeypatch.setattr(windows.psutil, "cpu_percent", lambda interval=None: next(cpu_values))
    monkeypatch.setattr(windows.time, "sleep", lambda _seconds: None)

    result = windows.get_process_stats(limit=1, sample_seconds=0.1)

    assert result.status == "success"
    assert result.data["system_cpu_percent"] == 7.5
    assert result.data["processes"][0] == {
        "pid": 34,
        "name": "sample.exe",
        "cpu_percent": 18.5,
        "memory_mb": 32.0,
        "memory_mib": 32.0,
        "memory_bytes": 1024 * 1024 * 32,
    }
    assert result.data["processes_scanned"] == 1
    assert windows.get_process_stats(limit=51).status == "invalid_input"
    assert windows.get_process_stats(sample_seconds=5).status == "invalid_input"


def test_memory_and_disk_information_are_structured(monkeypatch):
    _windows(monkeypatch)
    monkeypatch.setattr(
        windows.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(total=1000, available=250, used=750, percent=75.0),
    )
    monkeypatch.setattr(
        windows.psutil,
        "disk_partitions",
        lambda all=False: [SimpleNamespace(device="C:\\", mountpoint="C:\\", fstype="NTFS")],
    )
    monkeypatch.setattr(
        windows.psutil,
        "disk_usage",
        lambda _path: SimpleNamespace(total=10000, free=2500, percent=75.0),
    )

    memory = windows.get_memory_info()
    disk = windows.get_disk_info()

    assert memory.status == "success"
    assert memory.data["total_bytes"] == 1000
    assert memory.data["available_bytes"] == 250
    assert memory.data["utilization_percent"] == 75.0
    assert disk.status == "success"
    assert disk.data["volumes"][0]["filesystem"] == "NTFS"
    assert disk.data["volumes"][0]["free_bytes"] == 2500


def test_service_lookup_validates_name_and_handles_missing_or_denied(monkeypatch):
    _windows(monkeypatch)
    monkeypatch.setattr(
        windows.psutil,
        "win_service_get",
        lambda name: SimpleNamespace(
            as_dict=lambda: {"status": "running", "start_type": "automatic", "display_name": name}
        ),
    )
    result = windows.get_service_status("Spooler")
    assert result.status == "success"
    assert result.data["status"] == "running"
    assert result.data["start_type"] == "automatic"
    assert windows.get_service_status("*").status == "invalid_input"
    assert windows.get_service_status("Spooler;Stop-Service").status == "invalid_input"

    monkeypatch.setattr(
        windows.psutil,
        "win_service_get",
        lambda _name: (_ for _ in ()).throw(psutil.NoSuchProcess(1)),
    )
    assert windows.get_service_status("MissingSvc").status == "not_found"
    monkeypatch.setattr(
        windows.psutil,
        "win_service_get",
        lambda _name: (_ for _ in ()).throw(psutil.AccessDenied(1)),
    )
    assert windows.get_service_status("ProtectedSvc").status == "permission_denied"


def test_event_log_filters_are_allowlisted_bounded_and_permission_errors_are_clear(monkeypatch):
    _windows(monkeypatch)

    class FakeEventAPI:
        def __init__(self):
            self.call = None

        def query(self, log_name, xpath, maximum):
            self.call = (log_name, xpath, maximum)
            return [{"event_id": 1}, {"event_id": 2}, {"event_id": 3}]

    api = FakeEventAPI()
    result = windows.get_event_logs(
        {"log_name": "System", "hours_back": 8, "event_ids": [41], "levels": [2], "max_events": 2},
        _api=api,
    )
    assert result.status == "success"
    assert result.data["count"] == 2
    assert len(result.data["events"]) == 2
    assert api.call[0] == "System"
    assert "28800000" in api.call[1]
    assert "EventID=41" in api.call[1]
    assert api.call[2] == 2

    assert windows.get_event_logs({"log_name": "Security"}).status == "invalid_input"
    assert windows.get_event_logs({"query": "*"}).status == "invalid_input"
    assert windows.get_event_logs({"hours_back": 999}).status == "invalid_input"
    assert windows.get_event_logs({"max_events": 101}).status == "invalid_input"
    denied = windows.get_event_logs(_api=SimpleNamespace(query=lambda *_a: (_ for _ in ()).throw(PermissionError())))
    assert denied.status == "permission_denied"


@pytest.mark.parametrize(
    "tool_call",
    [
        windows.get_system_info,
        windows.get_process_stats,
        windows.get_memory_info,
        windows.get_disk_info,
        lambda: windows.get_service_status("Spooler"),
        windows.get_event_logs,
    ],
)
def test_windows_tools_report_unsupported_operating_system(monkeypatch, tool_call):
    monkeypatch.setattr(windows.platform, "system", lambda: "Linux")
    assert tool_call().status == "unsupported_os"
