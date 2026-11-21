"""The sole mutable demo fixture: one known disposable cache payload."""

from __future__ import annotations

import ctypes
import hashlib
import os
import re
import stat
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Iterator

from osguard.schemas import DemoCacheInspection, DemoCacheSnapshot, ToolExecutionResult


DEMO_CACHE_ID = "osguard_demo"
DEMO_TOOL_NAME = "inspect_osguard_demo_cache"
DEMO_EVIDENCE_ID = "osguard_demo_cache_inspection"
OWNER_MARKER = b"OSGUARD_DEMO_CACHE_OWNER_V1\n"
DEMO_PAYLOAD = b"OSGuard demo application cache fixture\nDisposable test data only.\n"
_ALLOWED_NAMES = {".osguard-owner", "cache-entry.bin"}
_MARKER_HASH = hashlib.sha256(OWNER_MARKER).hexdigest()
_DEMO_REQUEST = re.compile(
    r"(?:^|[.!?]\s+)(?:please\s+)?(?:clear|reset)\s+(?:the\s+)?osguard demo cache\b",
    re.IGNORECASE,
)
_EXACT_DEMO_REQUEST = re.compile(
    r"^(?:please\s+)?(?:clear|reset)\s+(?:the\s+)?osguard demo cache[.!]?\s*$",
    re.IGNORECASE,
)


class DemoCacheError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def explicit_demo_request_quote(request: str) -> str | None:
    """Recognize a direct request for this exact repair, never a question about it."""
    match = _DEMO_REQUEST.search(request.strip())
    return match.group(0).strip() if match else None


def is_exact_demo_request(request: str) -> bool:
    return bool(_EXACT_DEMO_REQUEST.fullmatch(request.strip()))


def _is_reparse(path: Path) -> bool:
    info = path.lstat()
    return (
        path.is_symlink()
        or path.is_junction()
        or bool(getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    )


def _assert_regular(path: Path, *, directory: bool) -> None:
    if _is_reparse(path):
        raise DemoCacheError("reparse_point", "The demo cache path contains a symbolic link or junction.")
    mode = path.lstat().st_mode
    if not (stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)):
        raise DemoCacheError("unexpected_file_type", "The demo cache contains an unexpected file type.")


def _directory_chain(path: Path) -> list[Path]:
    return [*reversed(path.parents), path]


@contextmanager
def _locked_known_payload(path: Path, project_root: Path) -> Iterator[object]:
    """Open the exact file without following reparse points; lock its ancestors.

    Windows handles opened without delete sharing prevent a directory swap while
    the payload handle is checked and changed. No path supplied by an LLM enters
    this function.
    """
    if os.name != "nt":
        raise DemoCacheError("unsupported_os", "The demo repair runs only on Windows.")
    if not path.is_relative_to(project_root) or path == project_root:
        raise DemoCacheError("target_mismatch", "The payload is outside the trusted project root.")

    import msvcrt
    from ctypes import wintypes

    class _HandleInfo(ctypes.Structure):
        _fields_ = [
            ("attributes", wintypes.DWORD),
            ("creation_time", wintypes.FILETIME),
            ("access_time", wintypes.FILETIME),
            ("write_time", wintypes.FILETIME),
            ("volume_serial", wintypes.DWORD),
            ("size_high", wintypes.DWORD),
            ("size_low", wintypes.DWORD),
            ("links", wintypes.DWORD),
            ("file_index_high", wintypes.DWORD),
            ("file_index_low", wintypes.DWORD),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(_HandleInfo)]
    kernel.GetFileInformationByHandle.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    invalid = ctypes.c_void_p(-1).value
    file_read_attributes = 0x80
    generic_read_write = 0x80000000 | 0x40000000
    share_read_write = 0x1 | 0x2
    open_existing = 3
    open_reparse_point = 0x00200000
    backup_semantics = 0x02000000
    directory_attribute = 0x10
    reparse_attribute = 0x400

    def open_checked(known_path: Path, *, directory: bool) -> int:
        handle = kernel.CreateFileW(
            str(known_path),
            file_read_attributes if directory else generic_read_write,
            share_read_write if directory else 0x1,
            None,
            open_existing,
            open_reparse_point | (backup_semantics if directory else 0),
            None,
        )
        if handle == invalid:
            raise ctypes.WinError(ctypes.get_last_error())
        info = _HandleInfo()
        if not kernel.GetFileInformationByHandle(handle, ctypes.byref(info)):
            error = ctypes.WinError(ctypes.get_last_error())
            kernel.CloseHandle(handle)
            raise error
        if info.attributes & reparse_attribute or bool(info.attributes & directory_attribute) != directory:
            kernel.CloseHandle(handle)
            raise DemoCacheError("reparse_point", "The demo cache path changed or contains a reparse point.")
        return handle

    with ExitStack() as stack:
        directories = [project_root]
        current = project_root
        for component in path.parent.relative_to(project_root).parts:
            current = current / component
            directories.append(current)
        for directory in directories:
            handle = open_checked(directory, directory=True)
            stack.callback(kernel.CloseHandle, handle)
        payload_handle = open_checked(path, directory=False)
        try:
            descriptor = msvcrt.open_osfhandle(payload_handle, os.O_RDWR | os.O_BINARY)
        except Exception:
            kernel.CloseHandle(payload_handle)
            raise
        with os.fdopen(descriptor, "r+b") as payload:
            yield payload


class DemoCacheStore:
    """Fixed trusted location; custom roots are accepted only from application/test code."""

    def __init__(self, project_root: Path | None = None):
        self.project_root = (
            Path(project_root).absolute()
            if project_root is not None
            else Path(__file__).resolve().parents[3]
        )
        self.cache_dir = self.project_root / "data" / "demo_app" / "cache"
        self.marker = self.cache_dir / ".osguard-owner"
        self.payload = self.cache_dir / "cache-entry.bin"

    def _check_directories(self) -> None:
        for directory in _directory_chain(self.cache_dir):
            if not directory.exists() and not directory.is_symlink():
                raise DemoCacheError("cache_missing", "The OSGuard demo cache has not been prepared.")
            _assert_regular(directory, directory=True)

    def inspect(self) -> DemoCacheInspection:
        if os.name != "nt":
            return DemoCacheInspection(status="unsupported_os", reason_code="unsupported_os")
        try:
            self._check_directories()
            if {entry.name for entry in self.cache_dir.iterdir()} != _ALLOWED_NAMES:
                raise DemoCacheError("unexpected_contents", "The demo cache contains missing or unrecognized entries.")
            _assert_regular(self.marker, directory=False)
            _assert_regular(self.payload, directory=False)
            if self.marker.read_bytes() != OWNER_MARKER:
                raise DemoCacheError("ownership_marker_invalid", "The demo cache ownership marker is invalid.")
            if self.payload.stat().st_size > len(DEMO_PAYLOAD):
                raise DemoCacheError("unrecognized_payload", "The demo cache payload is not the disposable fixture.")
            contents = self.payload.read_bytes()
            if contents not in (DEMO_PAYLOAD, b""):
                raise DemoCacheError("unrecognized_payload", "The demo cache payload is not the disposable fixture.")
            snapshot = DemoCacheSnapshot(
                target=str(self.cache_dir),
                payload_size=len(contents),
                payload_sha256=hashlib.sha256(contents).hexdigest(),
                owner_marker_sha256=_MARKER_HASH,
            )
            status = "ready" if contents else "empty"
            return DemoCacheInspection(
                status=status,
                snapshot=snapshot,
                message=f"The OSGuard-owned demo cache contains {len(contents)} bytes of disposable fixture data.",
            )
        except DemoCacheError as exc:
            status = "missing" if exc.code == "cache_missing" else "unsafe"
            return DemoCacheInspection(status=status, reason_code=exc.code, message=str(exc))
        except PermissionError:
            return DemoCacheInspection(status="failed", reason_code="permission_denied", message="Demo cache inspection was denied.")
        except OSError as exc:
            return DemoCacheInspection(status="failed", reason_code=type(exc).__name__, message="Demo cache inspection failed.")

    def prepare_fixture(self) -> DemoCacheInspection:
        """Seed disposable data only after an explicit application demo request."""
        if os.name != "nt":
            return DemoCacheInspection(status="unsupported_os", reason_code="unsupported_os")
        try:
            _assert_regular(self.project_root, directory=True)
            for directory in (self.project_root / "data", self.project_root / "data" / "demo_app", self.cache_dir):
                if not directory.exists() and not directory.is_symlink():
                    directory.mkdir()
                _assert_regular(directory, directory=True)
            entries = {entry.name for entry in self.cache_dir.iterdir()}
            if entries - _ALLOWED_NAMES:
                raise DemoCacheError("unexpected_contents", "The demo cache contains unrecognized entries.")
            if self.marker.exists() or self.marker.is_symlink():
                _assert_regular(self.marker, directory=False)
                if self.marker.read_bytes() != OWNER_MARKER:
                    raise DemoCacheError("ownership_marker_invalid", "The ownership marker is invalid.")
            else:
                with self.marker.open("xb") as marker:
                    marker.write(OWNER_MARKER)
            if self.payload.exists() or self.payload.is_symlink():
                _assert_regular(self.payload, directory=False)
                if self.payload.read_bytes() != b"":
                    return self.inspect()
                with _locked_known_payload(self.payload, self.project_root) as payload:
                    if payload.read() != b"":
                        raise DemoCacheError("payload_changed", "The demo payload changed during preparation.")
                    payload.write(DEMO_PAYLOAD)
                    payload.flush()
                    os.fsync(payload.fileno())
            else:
                with self.payload.open("xb") as payload:
                    payload.write(DEMO_PAYLOAD)
            return self.inspect()
        except DemoCacheError as exc:
            return DemoCacheInspection(status="unsafe", reason_code=exc.code, message=str(exc))
        except PermissionError:
            return DemoCacheInspection(status="failed", reason_code="permission_denied", message="Preparing the demo cache was denied.")
        except OSError as exc:
            return DemoCacheInspection(status="failed", reason_code=type(exc).__name__, message="Preparing the demo cache failed.")

    def clear(self, expected: DemoCacheSnapshot) -> DemoCacheSnapshot:
        """Truncate only the known file, after checking its exact pre-state."""
        if expected.target != str(self.cache_dir) or expected.cache_id != DEMO_CACHE_ID:
            raise DemoCacheError("target_mismatch", "The approved target does not match the fixed demo cache.")
        before = self.inspect()
        if before.status != "ready" or before.snapshot != expected:
            raise DemoCacheError("precondition_changed", "The demo cache differs from the approved pre-state.")
        with _locked_known_payload(self.payload, self.project_root) as payload:
            contents = payload.read(len(DEMO_PAYLOAD) + 1)
            if contents != DEMO_PAYLOAD or hashlib.sha256(contents).hexdigest() != expected.payload_sha256:
                raise DemoCacheError("precondition_changed", "The demo payload changed before execution.")
            payload.seek(0)
            payload.truncate(0)
            payload.flush()
            os.fsync(payload.fileno())
        after = self.inspect()
        if after.snapshot is None:
            raise DemoCacheError("postcheck_unavailable", "The demo cache could not be inspected after execution.")
        return after.snapshot

    def tool_result(self) -> ToolExecutionResult:
        inspection = self.inspect()
        if inspection.status in {"ready", "empty"} and inspection.snapshot:
            return ToolExecutionResult(
                tool_name=DEMO_TOOL_NAME,
                status="success",
                summary=inspection.message,
                evidence_id=DEMO_EVIDENCE_ID,
                data={
                    "cache_id": DEMO_CACHE_ID,
                    "payload_bytes": inspection.snapshot.payload_size,
                    "payload_sha256": inspection.snapshot.payload_sha256,
                    "owner_marker_sha256": inspection.snapshot.owner_marker_sha256,
                    "cache_status": inspection.status,
                },
            )
        return ToolExecutionResult(
            tool_name=DEMO_TOOL_NAME,
            status="not_found" if inspection.status == "missing" else "failed",
            summary=inspection.message or "OSGuard demo cache inspection was unavailable.",
            error=inspection.reason_code,
        )
