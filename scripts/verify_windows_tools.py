"""Read-only Windows tool smoke check with privacy-limited output."""

from __future__ import annotations

import json
import time

from osguard.tools.windows import (
    get_disk_info,
    get_event_logs,
    get_memory_info,
    get_process_stats,
    get_service_status,
    get_system_info,
)


def main() -> int:
    checks = [
        ("system", get_system_info),
        ("process", lambda: get_process_stats(limit=3, sample_seconds=0.05)),
        ("memory", get_memory_info),
        ("disk", get_disk_info),
        ("service", lambda: get_service_status("EventLog")),
        ("missing_service", lambda: get_service_status("__OSGUARD_MISSING_SERVICE__")),
        ("events", lambda: get_event_logs({"log_name": "System", "hours_back": 1, "max_events": 3})),
    ]
    for name, check in checks:
        started = time.monotonic()
        result = check()
        data = result.data
        summary = {
            "check": name,
            "status": result.status,
            "error": result.error,
            "seconds": round(time.monotonic() - started, 3),
        }
        if name == "system":
            summary.update({key: data.get(key) for key in ("os_name", "os_build", "architecture")})
        elif name == "process":
            summary.update({
                "system_cpu_percent": data.get("system_cpu_percent"),
                "processes_scanned": data.get("processes_scanned"),
                "returned_process_count": len(data.get("processes", [])),
            })
        elif name == "memory":
            summary.update({key: data.get(key) for key in ("total_bytes", "available_bytes", "utilization_percent")})
        elif name == "disk":
            summary["volume_count"] = data.get("volume_count")
        elif name in {"service", "missing_service"}:
            summary["service_status"] = data.get("status")
        elif name == "events":
            summary["count"] = data.get("count")
        print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
