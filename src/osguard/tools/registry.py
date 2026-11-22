"""Independent client-side argument policy for approved diagnostic tools."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class NoArgs(ToolArgs):
    pass


class ProcessArgs(ToolArgs):
    limit: int = Field(default=10, ge=1, le=50)
    sample_seconds: float = Field(default=0.15, ge=0.05, le=0.5)
    sort_by: Literal["cpu", "memory"] = "cpu"


class ServiceArgs(ToolArgs):
    service_name: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,128}$")


class EventFilters(ToolArgs):
    log_name: Literal["Application", "System", "Setup"] = "Application"
    hours_back: int = Field(default=24, ge=1, le=168)
    event_ids: list[int] = Field(default_factory=list, max_length=20)
    levels: list[int] = Field(default_factory=lambda: [1, 2, 3], max_length=5)
    max_events: int = Field(default=20, ge=1, le=100)
    provider_name: str | None = Field(default=None, min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_. -]+$")

    @field_validator("event_ids")
    @classmethod
    def valid_event_ids(cls, values: list[int]) -> list[int]:
        if any(isinstance(value, bool) or not 0 <= value <= 65535 for value in values):
            raise ValueError("event IDs must be integers from 0 to 65535")
        return values

    @field_validator("levels")
    @classmethod
    def valid_levels(cls, values: list[int]) -> list[int]:
        if any(isinstance(value, bool) or not 1 <= value <= 5 for value in values):
            raise ValueError("event levels must be integers from 1 to 5")
        return values


class EventArgs(ToolArgs):
    filters: EventFilters


class FolderArgs(ToolArgs):
    folder: Literal["Downloads", "Documents", "Desktop"]
    limit: int = Field(default=10, ge=1, le=50)
    recursive: bool = False
    max_depth: int = Field(default=2, ge=0, le=3)
    max_entries: int = Field(default=2000, ge=1, le=5000)
    timeout_seconds: float = Field(default=5.0, ge=0.1, le=10.0)


class ListFolderArgs(ToolArgs):
    folder: Literal["Downloads", "Documents", "Desktop"]
    limit: int = Field(default=50, ge=1, le=50)
    max_entries: int = Field(default=2000, ge=1, le=5000)
    timeout_seconds: float = Field(default=5.0, ge=0.1, le=10.0)


class SizeFolderArgs(ToolArgs):
    folder: Literal["Downloads", "Documents", "Desktop"]
    recursive: bool = True
    max_depth: int = Field(default=2, ge=0, le=3)
    max_entries: int = Field(default=2000, ge=1, le=5000)
    timeout_seconds: float = Field(default=5.0, ge=0.1, le=10.0)


class ServicesArgs(ToolArgs):
    limit: int = Field(default=30, ge=1, le=50)


class DeviceArgs(ToolArgs):
    device_class: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_. -]+$")
    status: Literal["healthy", "reported_problem", "disabled", "disconnected", "missing_driver", "unknown"] | None = None
    device_id: str | None = Field(default=None, min_length=3, max_length=120, pattern=r"^[A-Za-z0-9_&\\#.+{}-]+$")
    problem_only: bool = True
    limit: int = Field(default=20, ge=1, le=50)


class DeviceStatusArgs(DeviceArgs):
    problem_only: bool = False


class DriverArgs(ToolArgs):
    device_class: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_. -]+$")
    device_id: str | None = Field(default=None, min_length=3, max_length=120, pattern=r"^[A-Za-z0-9_&\\#.+{}-]+$")
    limit: int = Field(default=20, ge=1, le=50)


class LimitArgs(ToolArgs):
    limit: int = Field(default=20, ge=1, le=50)


class SoftwareArgs(LimitArgs):
    name: str | None = Field(default=None, min_length=2, max_length=80, pattern=r"^[A-Za-z0-9_.+ -]+$")


class AppProcessArgs(LimitArgs):
    name: str = Field(min_length=2, max_length=80, pattern=r"^[A-Za-z0-9_.+ -]+$")


class AppErrorsArgs(LimitArgs):
    name: str | None = Field(default=None, min_length=2, max_length=80, pattern=r"^[A-Za-z0-9_.+ -]+$")
    hours_back: int = Field(default=48, ge=1, le=168)


class ConnectivityArgs(ToolArgs):
    target: Literal["microsoft"] = "microsoft"
    timeout_seconds: float = Field(default=2.0, ge=0.2, le=3.0)


APPROVED_ARGUMENTS: dict[str, type[ToolArgs]] = {
    "get_system_info": NoArgs,
    "get_process_stats": ProcessArgs,
    "get_memory_info": NoArgs,
    "get_disk_info": NoArgs,
    "get_service_status": ServiceArgs,
    "get_event_logs": EventArgs,
    "get_largest_files": FolderArgs,
    "list_directory": ListFolderArgs,
    "get_directory_size": SizeFolderArgs,
    "get_system_uptime": NoArgs,
    "list_services": ServicesArgs,
    "inspect_problem_devices": DeviceArgs,
    "inspect_device_status": DeviceStatusArgs,
    "inspect_device_drivers": DriverArgs,
    "inspect_network_adapters": LimitArgs,
    "get_network_configuration": LimitArgs,
    "inspect_dns_configuration": LimitArgs,
    "check_network_connectivity": ConnectivityArgs,
    "get_windows_update_history": LimitArgs,
    "inspect_failed_updates": LimitArgs,
    "inspect_update_service_status": NoArgs,
    "inspect_installed_software": SoftwareArgs,
    "inspect_application_process": AppProcessArgs,
    "inspect_application_errors": AppErrorsArgs,
}


def validate_arguments(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Reject unknown tools and parameters before either backend sees them."""
    model = APPROVED_ARGUMENTS.get(name)
    if model is None:
        raise ValueError("Tool is not in the read-only diagnostic registry.")
    return model.model_validate(arguments).model_dump(mode="python", exclude_unset=True)
