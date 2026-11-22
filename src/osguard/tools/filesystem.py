"""Read-only, bounded metadata scans of explicitly named Windows known folders."""

from __future__ import annotations

import ctypes
import os
import stat
import time
import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from osguard.schemas import ToolExecutionResult
from osguard.tools.windows import _is_windows, _result


KnownFolder = Literal["Downloads", "Documents", "Desktop"]
_FOLDER_IDS = {
    "Downloads": "374DE290-123F-4565-9164-39C4925E467B",
    "Documents": "FDD39AD0-238F-46AF-ADB4-6C85480369C7",
    "Desktop": "B4BFCC3A-DB2C-424C-B029-7FE99A87C641",
}
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8),
    ]


def resolve_known_folder(folder: KnownFolder) -> Path:
    """Ask Windows for the current user's real known-folder location."""
    if folder not in _FOLDER_IDS:
        raise ValueError("Only approved known folders are available.")
    if not _is_windows():
        raise OSError("Windows known folders are available only on Windows.")
    guid = _GUID.from_buffer_copy(uuid.UUID(_FOLDER_IDS[folder]).bytes_le)
    path = ctypes.c_wchar_p()
    shell = ctypes.windll.shell32
    shell.SHGetKnownFolderPath.argtypes = [
        ctypes.POINTER(_GUID), ctypes.c_uint32, ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_wchar_p),
    ]
    shell.SHGetKnownFolderPath.restype = ctypes.c_long
    result = shell.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(path))
    if result != 0 or not path.value:
        raise OSError(f"Windows could not resolve the {folder} known folder.")
    try:
        return Path(path.value)
    finally:
        ctypes.windll.ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        ctypes.windll.ole32.CoTaskMemFree(path)


class FolderScanArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    folder: KnownFolder
    limit: int = Field(default=10, ge=1, le=50)
    recursive: bool = False
    max_depth: int = Field(default=2, ge=0, le=3)
    max_entries: int = Field(default=2000, ge=1, le=5000)
    timeout_seconds: float = Field(default=5.0, ge=0.1, le=10.0)


def _is_reparse(metadata: os.stat_result) -> bool:
    return bool(getattr(metadata, "st_file_attributes", 0) & _REPARSE_POINT)


def _scan(name: str, args: FolderScanArgs, *, mode: str) -> ToolExecutionResult:
    if not _is_windows():
        return _result(name, "unsupported_os", "Known-folder scans require Windows.")
    try:
        root = resolve_known_folder(args.folder)
        root_stat = os.lstat(root)
        if _is_reparse(root_stat) or stat.S_ISLNK(root_stat.st_mode):
            return _result(name, "invalid_input", "The known-folder target is a reparse point.")
        if not stat.S_ISDIR(root_stat.st_mode):
            return _result(name, "not_found", "The known folder is not a directory.")
    except FileNotFoundError:
        return _result(name, "not_found", "The known folder does not exist.")
    except PermissionError:
        return _result(name, "permission_denied", "The known folder cannot be inspected.")
    except (OSError, ValueError) as exc:
        return _result(name, "failed", "The known folder could not be resolved.", error=type(exc).__name__)

    deadline = time.monotonic() + args.timeout_seconds
    pending: list[tuple[Path, int]] = [(root, 0)]
    rows: list[dict] = []
    entries_scanned = directories_scanned = skipped_reparse = denied = 0
    total_bytes = 0
    truncated = False
    while pending:
        if time.monotonic() >= deadline or entries_scanned >= args.max_entries:
            truncated = True
            break
        directory, depth = pending.pop(0)
        try:
            with os.scandir(directory) as iterator:
                directories_scanned += 1
                for entry in iterator:
                    if time.monotonic() >= deadline or entries_scanned >= args.max_entries:
                        truncated = True
                        break
                    entries_scanned += 1
                    try:
                        metadata = entry.stat(follow_symlinks=False)
                        if _is_reparse(metadata) or stat.S_ISLNK(metadata.st_mode):
                            skipped_reparse += 1
                            continue
                        if stat.S_ISDIR(metadata.st_mode):
                            if args.recursive and depth < args.max_depth:
                                pending.append((Path(entry.path), depth + 1))
                            elif args.recursive:
                                truncated = True
                            if mode == "list" and depth == 0:
                                rows.append({"name": entry.name, "kind": "directory", "size_bytes": None})
                            continue
                        if not stat.S_ISREG(metadata.st_mode):
                            continue
                        size = int(metadata.st_size)
                        total_bytes += size
                        if mode != "size":
                            rows.append({
                                "name": entry.name,
                                "relative_path": str(Path(entry.path).relative_to(root)),
                                "kind": "file", "size_bytes": size,
                                "modified_epoch": float(metadata.st_mtime),
                            })
                    except (PermissionError, OSError):
                        denied += 1
        except (PermissionError, OSError):
            denied += 1
    if mode == "largest":
        rows.sort(key=lambda item: item["size_bytes"], reverse=True)
    elif mode == "list":
        rows.sort(key=lambda item: item["name"].casefold())
    visible = rows[:args.limit]
    display_truncated = len(rows) > args.limit
    complete = not truncated and denied == 0
    data = {
        "folder": args.folder,
        "files": visible, "total_bytes": total_bytes,
        "entries_scanned": entries_scanned,
        "directories_scanned": directories_scanned,
        "skipped_reparse_points": skipped_reparse,
        "permission_errors": denied,
        "scan_complete": complete,
        "scan_truncated": truncated,
        "display_truncated": display_truncated,
        "recursive": args.recursive,
    }
    if denied and not entries_scanned:
        return _result(name, "permission_denied", "The directory could not be read.", data=data)
    summary = (
        f"Read {entries_scanned} metadata entries in the {args.folder} known folder."
        + (" Ranking or total is partial because the scan was limited or entries were inaccessible." if not complete else "")
    )
    return _result(name, "success", summary, data=data)


def _validated_scan(name: str, mode: str, **kwargs: object) -> ToolExecutionResult:
    try:
        args = FolderScanArgs.model_validate(kwargs)
    except ValidationError:
        return _result(name, "invalid_input", "Folder, limits, or recursion parameters are invalid.")
    return _scan(name, args, mode=mode)


def get_largest_files(*, folder: KnownFolder, limit: int = 10, recursive: bool = False,
                      max_depth: int = 2, max_entries: int = 2000,
                      timeout_seconds: float = 5.0) -> ToolExecutionResult:
    """Rank file metadata in an approved known folder; do not read contents."""
    return _validated_scan("get_largest_files", "largest", folder=folder, limit=limit,
                           recursive=recursive, max_depth=max_depth,
                           max_entries=max_entries, timeout_seconds=timeout_seconds)


def list_directory(*, folder: KnownFolder, limit: int = 50,
                   max_entries: int = 2000, timeout_seconds: float = 5.0) -> ToolExecutionResult:
    """List immediate children in an approved known folder."""
    return _validated_scan("list_directory", "list", folder=folder, limit=limit,
                           recursive=False, max_depth=0, max_entries=max_entries,
                           timeout_seconds=timeout_seconds)


def get_directory_size(*, folder: KnownFolder, recursive: bool = True,
                       max_depth: int = 2, max_entries: int = 2000,
                       timeout_seconds: float = 5.0) -> ToolExecutionResult:
    """Measure bounded file sizes in an approved known folder."""
    return _validated_scan("get_directory_size", "size", folder=folder, limit=1,
                           recursive=recursive, max_depth=max_depth,
                           max_entries=max_entries, timeout_seconds=timeout_seconds)
