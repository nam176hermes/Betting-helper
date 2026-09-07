"""Closed, read-only mapping from recorded evidence locators to retained bytes."""

from __future__ import annotations

import hashlib
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from os import stat_result
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import NoReturn, cast


def _fail() -> NoReturn:
    raise ValueError("E_RETAINED_ARTIFACT")


def _canonical_recorded(value: object) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        _fail()
    candidate = value
    unc = re.fullmatch(r"\\\\wsl\.localhost\\([^\\]+)\\(.+)", candidate, re.I)
    if unc is not None:
        if unc.group(1).lower() != "ubuntu":
            _fail()
        candidate = "/" + unc.group(2).replace("\\", "/")
    else:
        drive = re.fullmatch(r"([A-Za-z]):\\(.+)", candidate)
        if drive is not None:
            candidate = f"/mnt/{drive.group(1).lower()}/{drive.group(2).replace('\\', '/')}"
    if not candidate.startswith("/") or "\\" in candidate or "//" in candidate:
        _fail()
    parts = candidate.split("/")[1:]
    if not parts or any(part in {"", ".", ".."} for part in parts):
        _fail()
    return PurePosixPath(candidate).as_posix()


def canonical_recorded_locator(value: object) -> str:
    """Return the single supported POSIX identity for a recorded locator."""
    return _canonical_recorded(value)


def _canonical_relative(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        _fail()
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        _fail()
    return path.as_posix()


@dataclass(frozen=True)
class _Entry:
    boundary: str
    relative: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class RetainedArtifactIO:
    recorded_boundaries: tuple[str, ...]
    physical_root: Path
    recorded_to_relative: Mapping[str, str]
    _entries: Mapping[str, _Entry]

    def _validated_target(self, relative: str) -> tuple[Path, stat_result]:
        target = self.physical_root / relative
        try:
            root_info = self.physical_root.lstat()
            if (
                self.physical_root.is_symlink()
                or not stat.S_ISDIR(root_info.st_mode)
                or self.physical_root.absolute() != self.physical_root.resolve(strict=True)
            ):
                _fail()
            parent = self.physical_root
            for part in PurePosixPath(relative).parts[:-1]:
                parent /= part
                parent_info = parent.lstat()
                if parent.is_symlink() or not stat.S_ISDIR(parent_info.st_mode):
                    _fail()
            info = target.lstat()
        except OSError as error:
            raise ValueError("E_RETAINED_ARTIFACT") from error
        if target.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            _fail()
        return target, info

    @classmethod
    def from_manifest(cls, manifest: object, physical_root: Path) -> RetainedArtifactIO:
        if (
            not isinstance(manifest, dict)
            or set(manifest) != {"schema_version", "recorded_boundaries", "files"}
            or manifest.get("schema_version") != "retained-artifact-manifest/v1"
            or not isinstance(manifest.get("recorded_boundaries"), list)
            or not isinstance(manifest.get("files"), list)
        ):
            _fail()
        try:
            root_info = physical_root.lstat()
        except OSError as error:
            raise ValueError("E_RETAINED_ARTIFACT") from error
        if (
            physical_root.is_symlink()
            or not stat.S_ISDIR(root_info.st_mode)
            or physical_root.absolute() != physical_root.resolve(strict=True)
        ):
            _fail()
        boundaries = tuple(
            _canonical_recorded(item)
            for item in cast(list[object], manifest["recorded_boundaries"])
        )
        if not boundaries or len(set(boundaries)) != len(boundaries):
            _fail()
        entries: dict[str, _Entry] = {}
        relatives: set[str] = set()
        inodes: set[tuple[int, int]] = set()
        expected_keys = {
            "recorded_locator",
            "recorded_boundary",
            "copied_relative_path",
            "size_bytes",
            "sha256",
        }
        for raw_row in cast(list[object], manifest["files"]):
            if not isinstance(raw_row, dict) or set(raw_row) != expected_keys:
                _fail()
            row = cast(dict[str, object], raw_row)
            locator = _canonical_recorded(row["recorded_locator"])
            boundary = _canonical_recorded(row["recorded_boundary"])
            relative = _canonical_relative(row["copied_relative_path"])
            size = row["size_bytes"]
            digest = row["sha256"]
            if (
                boundary not in boundaries
                or not PurePosixPath(locator).is_relative_to(PurePosixPath(boundary))
                or locator == boundary
                or locator in entries
                or relative in relatives
                or not isinstance(size, int)
                or isinstance(size, bool)
                or size < 0
                or not isinstance(digest, str)
                or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            ):
                _fail()
            target = physical_root / relative
            try:
                parent = physical_root
                for part in PurePosixPath(relative).parts[:-1]:
                    parent /= part
                    parent_info = parent.lstat()
                    if parent.is_symlink() or not stat.S_ISDIR(parent_info.st_mode):
                        _fail()
                info = target.lstat()
                data = target.read_bytes()
            except OSError as error:
                raise ValueError("E_RETAINED_ARTIFACT") from error
            inode = (info.st_dev, info.st_ino)
            if (
                target.is_symlink()
                or not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or inode in inodes
                or len(data) != size
                or hashlib.sha256(data).hexdigest() != digest
            ):
                _fail()
            entries[locator] = _Entry(boundary, relative, size, digest)
            relatives.add(relative)
            inodes.add(inode)
        actual = {
            item.relative_to(physical_root).as_posix()
            for item in physical_root.rglob("*")
            if item.is_file() or item.is_symlink()
        }
        if actual != relatives:
            _fail()
        return cls(
            recorded_boundaries=boundaries,
            physical_root=physical_root,
            recorded_to_relative=MappingProxyType(
                {key: value.relative for key, value in entries.items()}
            ),
            _entries=MappingProxyType(entries),
        )

    def physical_path(self, recorded_locator: str, *, recorded_boundary: str) -> Path:
        locator = _canonical_recorded(recorded_locator)
        boundary = _canonical_recorded(recorded_boundary)
        entry = self._entries.get(locator)
        if entry is None or entry.boundary != boundary:
            _fail()
        target, _info = self._validated_target(entry.relative)
        return target

    def recorded_boundary(self, recorded_locator: str) -> str:
        entry = self._entries.get(_canonical_recorded(recorded_locator))
        if entry is None:
            _fail()
        return entry.boundary

    def recorded_locators(self) -> tuple[str, ...]:
        return tuple(self._entries)

    def read_bytes(self, recorded_locator: str, *, recorded_boundary: str) -> bytes:
        locator = _canonical_recorded(recorded_locator)
        target = self.physical_path(recorded_locator, recorded_boundary=recorded_boundary)
        entry = self._entries[locator]
        try:
            info = target.lstat()
            data = target.read_bytes()
        except OSError as error:
            raise ValueError("E_RETAINED_ARTIFACT") from error
        if (
            target.is_symlink()
            or not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or len(data) != entry.size_bytes
            or hashlib.sha256(data).hexdigest() != entry.sha256
        ):
            _fail()
        return data


__all__ = ["RetainedArtifactIO", "canonical_recorded_locator"]
