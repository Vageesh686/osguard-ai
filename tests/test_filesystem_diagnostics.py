"""Disposable-file tests; never inspect a real user known folder."""

from __future__ import annotations

import builtins
import os

import pytest

from osguard.tools import filesystem as fs


@pytest.fixture
def downloads(tmp_path, monkeypatch):
    monkeypatch.setattr(fs, "_is_windows", lambda: True)
    monkeypatch.setattr(fs, "resolve_known_folder", lambda _folder: tmp_path)
    return tmp_path


def test_largest_files_sort_and_no_content_reads(downloads, monkeypatch):
    (downloads / "small.txt").write_bytes(b"a" * 3)
    (downloads / "large.bin").write_bytes(b"b" * 9)
    original = builtins.open
    def no_content_open(*args, **kwargs):
        raise AssertionError("File content must not be opened")
    monkeypatch.setattr(builtins, "open", no_content_open)
    try:
        result = fs.get_largest_files(folder="Downloads", limit=2)
    finally:
        monkeypatch.setattr(builtins, "open", original)
    assert result.status == "success"
    assert [row["name"] for row in result.data["files"]] == ["large.bin", "small.txt"]
    assert result.data["scan_complete"]
    assert (downloads / "large.bin").stat().st_size == 9


def test_empty_unauthorized_and_partial_scans(downloads):
    assert fs.get_largest_files(folder="Downloads").data["files"] == []
    assert fs.get_largest_files(folder="C:\\Windows").status == "invalid_input"
    for number in range(4):
        (downloads / f"item-{number}").write_bytes(b"x")
    result = fs.get_largest_files(folder="Downloads", max_entries=1)
    assert result.status == "success"
    assert not result.data["scan_complete"]
    assert result.data["scan_truncated"]


def test_directory_size_and_permission_failure(downloads, monkeypatch):
    nested = downloads / "nested"
    nested.mkdir()
    (nested / "data.bin").write_bytes(b"12345")
    result = fs.get_directory_size(folder="Downloads")
    assert result.status == "success" and result.data["total_bytes"] == 5
    assert result.data["scan_complete"]
    monkeypatch.setattr(fs.os, "scandir", lambda *_args: (_ for _ in ()).throw(PermissionError()))
    denied = fs.list_directory(folder="Downloads")
    assert denied.status == "permission_denied"


def test_symlink_is_not_followed(downloads):
    outside = downloads.parent / "outside-file.txt"
    outside.write_bytes(b"secret-data")
    link = downloads / "link.txt"
    try:
        os.symlink(outside, link)
    except OSError as exc:
        pytest.skip(f"Windows symlink privilege unavailable: {exc}")
    result = fs.get_largest_files(folder="Downloads")
    assert result.status == "success"
    assert result.data["files"] == []
    assert result.data["skipped_reparse_points"] == 1
