"""Process-local SQLite win32 VFS testing hook; never replaces the VFS or OS API."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

DLL_SHA256 = "8f05e8585c1c439872dded8f930a7462ed8e8e0ff8242b5202d3a2d052b672f6"


class VFS(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int) for name in ("iVersion", "szOsFile", "mxPathname")] + [
        (name, ctypes.c_void_p)
        for name in (
            "pNext",
            "zName",
            "pAppData",
            "xOpen",
            "xDelete",
            "xAccess",
            "xFullPathname",
            "xDlOpen",
            "xDlError",
            "xDlSym",
            "xDlClose",
            "xRandomness",
            "xSleep",
            "xCurrentTime",
            "xGetLastError",
            "xCurrentTimeInt64",
            "xSetSystemCall",
            "xGetSystemCall",
            "xNextSystemCall",
        )
    ]


def file_observation(handle: int) -> dict[str, Any]:
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    final = kernel.GetFinalPathNameByHandleW
    final.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong]
    final.restype = ctypes.c_ulong
    buffer = ctypes.create_unicode_buffer(32768)
    length = final(handle, buffer, len(buffer), 0)

    class Info(ctypes.Structure):
        _fields_ = [
            ("attributes", wintypes.DWORD),
            ("created", wintypes.FILETIME),
            ("accessed", wintypes.FILETIME),
            ("written", wintypes.FILETIME),
        ] + [
            (name, wintypes.DWORD)
            for name in ("volume", "size_high", "size_low", "links", "index_high", "index_low")
        ]

    query = kernel.GetFileInformationByHandle
    query.argtypes = [ctypes.c_void_p, ctypes.POINTER(Info)]
    query.restype = ctypes.c_int
    info = Info()
    if not 0 < length < len(buffer) or not query(handle, ctypes.byref(info)):
        raise ValueError("E_NATIVE_COMMIT_IO_FILE_HANDLE")
    return {
        "path": buffer.value,
        "volume": info.volume,
        "file_index": (info.index_high << 32) | info.index_low,
        "size": (info.size_high << 32) | info.size_low,
    }


def duplicate_journal(writer: Any, handle: int) -> dict[str, Any]:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    duplicate = kernel.DuplicateHandle
    duplicate.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_ulong,
        ctypes.c_int,
        ctypes.c_ulong,
    ]
    duplicate.restype = ctypes.c_int
    copied = ctypes.c_void_p()
    if not duplicate(int(writer._handle), handle, -1, ctypes.byref(copied), 0, False, 2):
        raise ValueError("E_NATIVE_COMMIT_IO_DUPLICATE_HANDLE")
    try:
        result = {
            "source_pid": writer.pid,
            "source_handle": handle,
            "duplicate_handle": copied.value,
            "file": file_observation(int(copied.value or 0)),
        }
    finally:
        close = kernel.CloseHandle
        close.argtypes = [ctypes.c_void_p]
        close.restype = ctypes.c_int
        if not close(copied):
            raise ValueError("E_NATIVE_COMMIT_IO_CLOSE_HANDLE")
    return {**result, "closed": True}


class CommitIoHook:
    def __init__(self, database: Path, case: Path, mode: str) -> None:
        import _sqlite3

        from tools.native_environment_probe import save

        self.case, self.database, self.mode = case, database, mode
        self.snapshot: dict[str, Any] | None = None
        self.events: list[dict[str, Any]] = []
        dll_path = Path(_sqlite3.__file__).with_name("sqlite3.dll").resolve()
        digest = hashlib.sha256(dll_path.read_bytes()).hexdigest()
        if digest != DLL_SHA256 or sqlite3.sqlite_version != "3.53.1":
            raise ValueError("HOLD_NATIVE_COMMIT_IO_DLL")
        self.dll = ctypes.CDLL(str(dll_path))
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        module_name = kernel.GetModuleFileNameW
        module_name.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_ulong]
        module_name.restype = ctypes.c_ulong
        loaded = ctypes.create_unicode_buffer(32768)
        get_module = kernel.GetModuleHandleW
        get_module.argtypes = [ctypes.c_wchar_p]
        get_module.restype = ctypes.c_void_p
        if (
            not module_name(self.dll._handle, loaded, len(loaded))
            or Path(loaded.value).resolve() != dll_path
            or get_module("sqlite3.dll") != self.dll._handle
        ):
            raise ValueError("HOLD_NATIVE_COMMIT_IO_LOADED_DLL")
        self.dll.sqlite3_vfs_find.argtypes = [ctypes.c_char_p]
        self.dll.sqlite3_vfs_find.restype = ctypes.POINTER(VFS)
        self.vfs = self.dll.sqlite3_vfs_find(None)
        if (
            not self.vfs
            or self.vfs.contents.iVersion < 3
            or not self.vfs.contents.xGetSystemCall
            or not self.vfs.contents.xSetSystemCall
        ):
            raise ValueError("HOLD_NATIVE_COMMIT_IO_VFS")
        get = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.POINTER(VFS), ctypes.c_char_p)(
            self.vfs.contents.xGetSystemCall
        )
        self.set = ctypes.CFUNCTYPE(
            ctypes.c_int, ctypes.POINTER(VFS), ctypes.c_char_p, ctypes.c_void_p
        )(self.vfs.contents.xSetSystemCall)
        original = get(self.vfs, b"FlushFileBuffers")
        if not original:
            raise ValueError("HOLD_NATIVE_COMMIT_IO_SYSCALL")
        signature = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, use_last_error=True)  # type: ignore[attr-defined]
        self.original = signature(original)
        self.callback = signature(self.flush)
        address = ctypes.cast(self.callback, ctypes.c_void_p).value
        installed = mode != "bypass"
        code = self.set(self.vfs, b"FlushFileBuffers", address) if installed else None
        observed = get(self.vfs, b"FlushFileBuffers")
        if installed and (code != 0 or observed != address):
            raise ValueError("HOLD_NATIVE_COMMIT_IO_INSTALL")
        self.info = {
            "dll": {"path": str(dll_path), "sha256": digest},
            "loaded_dll_path": loaded.value,
            "loaded_dll_handle": self.dll._handle,
            "sqlite_version": sqlite3.sqlite_version,
            "vfs_version": self.vfs.contents.iVersion,
            "vfs_name": ctypes.string_at(self.vfs.contents.zName).decode(),
            "original_address": original,
            "callback_address": address,
            "observed_address": observed,
            "set_result": code,
            "installed": installed,
            "syscall": "FlushFileBuffers",
            "mode": mode,
        }
        self.record({"event": "install", **self.info})
        self.save = save

    def record(self, value: dict[str, Any]) -> None:
        from tools.native_environment_probe import save

        self.events.append({"ordinal": len(self.events), "pid": os.getpid(), **value})
        save(self.case / "commit-io-events.json", self.events)

    def arm(self, connection: Any, snapshot: dict[str, Any]) -> None:
        self.snapshot = snapshot
        self.record(
            {
                "event": "commit_entry",
                "statement": "COMMIT",
                "in_transaction": connection.in_transaction,
                "armed": self.mode in {"armed", "postcommit"},
                "database": str(self.database),
            }
        )

    def flush(self, handle: int) -> int:
        try:
            observed = file_observation(handle)
            armed = self.snapshot is not None and self.mode in {"armed", "postcommit"}
            target = (
                observed["path"].removeprefix("\\\\?\\").casefold()
                == (str(self.database) + "-journal").casefold()
            )
            event = {
                "event": "flush_entry",
                "handle": handle,
                "file": observed,
                "armed": armed,
                "target": target,
                "before_original": True,
            }
            self.record(event)
            if armed and target and self.mode == "armed":
                witness = {**self.info, **event, "inside_callback": True}
                assert self.snapshot is not None
                self.save(self.case / "checkpoint.json", {**self.snapshot, "commit_io": witness})
                while True:
                    time.sleep(1)
        except Exception as error:
            self.record({"event": "callback_error", "error": str(error)})
        return int(self.original(handle))

    def fallback(self, snapshot: dict[str, Any]) -> None:
        self.record({"event": "postcommit", "in_transaction": False})
        self.save(
            self.case / "checkpoint.json",
            {
                **snapshot,
                "commit_io": {
                    **self.info,
                    "inside_callback": False,
                    "armed": False,
                    "handle": None,
                    "file": None,
                },
            },
        )
        while True:
            time.sleep(1)


def verify_commit_callback(row: dict[str, Any], case: Path, mode: str) -> None:
    from tools.run_environment_qualification import NATIVE, checked, localpath, winpath

    try:
        value = row["checkpoint"]["commit_io"]
        names = {
            "dll",
            "loaded_dll_path",
            "loaded_dll_handle",
            "sqlite_version",
            "vfs_version",
            "vfs_name",
            "original_address",
            "callback_address",
            "observed_address",
            "set_result",
            "installed",
            "syscall",
            "mode",
        }
        info = {key: value[key] for key in names}
        event_names = {"event", "handle", "file", "armed", "target", "before_original"}
        event = {key: value[key] for key in event_names}
        if (
            set(value) != names | event_names | {"inside_callback"}
            or mode != "armed"
            or info["mode"] != mode
            or not value["inside_callback"]
            or not value["armed"]
            or not value["target"]
            or not value["before_original"]
            or value["event"] != "flush_entry"
            or not info["installed"]
            or info["set_result"] != 0
            or info["vfs_version"] != 3
            or info["vfs_name"] != "win32"
            or info["syscall"] != "FlushFileBuffers"
            or info["sqlite_version"] != "3.53.1"
            or info["dll"]["sha256"] != DLL_SHA256
            or localpath(info["dll"]["path"]) != NATIVE.parent / "DLLs/sqlite3.dll"
            or localpath(info["loaded_dll_path"]) != NATIVE.parent / "DLLs/sqlite3.dll"
            or any(
                type(info[key]) is not int or info[key] <= 0
                for key in [
                    "loaded_dll_handle",
                    "original_address",
                    "callback_address",
                    "observed_address",
                ]
            )
            or info["observed_address"] != info["callback_address"]
            or info["original_address"] == info["callback_address"]
        ):
            raise ValueError("callback")
        checked(info["dll"])
        identity = row["checkpoint"]["identity"]
        file = value["file"]
        expected_path = winpath(case / identity["run_id"] / "run.sqlite3") + "-journal"
        if (
            set(file) != {"path", "volume", "file_index", "size"}
            or file["path"].removeprefix("\\\\?\\").casefold() != expected_path.casefold()
            or any(
                type(file[key]) is not int or file[key] <= 0
                for key in ["volume", "file_index", "size"]
            )
            or type(value["handle"]) is not int
            or value["handle"] <= 0
        ):
            raise ValueError("journal")
        observed = row["journal_observation"]
        if (
            set(observed) != {"source_pid", "source_handle", "duplicate_handle", "file", "closed"}
            or observed["source_pid"] != row["writer"]["pid"]
            or observed["source_handle"] != value["handle"]
            or not observed["duplicate_handle"]
            or observed["closed"] is not True
            or observed["file"] != file
        ):
            raise ValueError("independent file handle")
        if localpath(row["commit_io_events"]["path"]) != case / "commit-io-events.json":
            raise ValueError("events path")
        events = json.loads(checked(row["commit_io_events"]))
        expected = [
            {"event": "install", **info},
            {
                "event": "commit_entry",
                "statement": "COMMIT",
                "in_transaction": True,
                "armed": True,
                "database": winpath(case / identity["run_id"] / "run.sqlite3"),
            },
            event,
        ]
        if events != [
            {"ordinal": ordinal, "pid": row["writer"]["pid"], **entry}
            for ordinal, entry in enumerate(expected)
        ]:
            raise ValueError("actual callback events")
    except (KeyError, TypeError, ValueError, OSError) as error:
        raise ValueError("E_NATIVE_COMMIT_IO_CALLBACK") from error
