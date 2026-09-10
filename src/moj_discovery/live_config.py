"""Explicit v2 configuration. Parsing is network-free and grants no run authority."""

import copy
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from .canonical import parse_strict_json
from .live_contracts import schema_validate

ROOT = Path(__file__).resolve().parents[2]


def private_path(name: str, *, root: Path = ROOT, must_exist: bool = False) -> Path:
    relative = Path(name)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or "\\" in name
        or not relative.parts
        or relative.parts[0] != ".local"
    ):
        raise ValueError("E_LIVE_CONFIG_PATH")
    path = root / relative
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("E_LIVE_CONFIG_PATH")
    if not path.resolve().is_relative_to((root / ".local").resolve()):
        raise ValueError("E_LIVE_CONFIG_PATH")
    if must_exist and not path.is_file():
        raise ValueError("E_LIVE_CONFIG_EVIDENCE_MISSING")
    return path


@dataclass(frozen=True)
class LiveConfig:
    _data: dict[str, Any]
    sha256: str

    @property
    def public(self) -> dict[str, Any]:
        return copy.deepcopy(self._data)

    @property
    def enabled(self) -> bool:
        return bool(self._data["enabled"])

    @property
    def fixture_ids(self) -> tuple[int, ...]:
        return tuple(sorted(self._data["provider"]["fixture_ids"]))


def load_live_config(path: Path, require_enabled: bool = False) -> LiveConfig:
    try:
        if path.is_symlink() or path.stat().st_size > 65536:
            raise ValueError("E_LIVE_CONFIG_FILE")
        raw = path.read_bytes()
        value = cast(dict[str, Any], parse_strict_json(raw))
        schema_validate(value, "config")
        provider, runtime, operator = value["provider"], value["runtime"], value["operator"]
        for name in (
            "batch_api_limit",
            "live_poll_seconds",
            "halftime_poll_seconds",
            "prematch_poll_seconds",
            "near_kickoff_poll_seconds",
            "events_fallback_poll_seconds",
            "daily_soft_cap",
            "max_requests_per_run",
            "max_requests_per_minute",
            "min_request_gap_seconds",
            "max_in_flight",
        ):
            if type(provider[name]) is not int:
                raise ValueError("E_LIVE_CONFIG_INTEGER")
        if type(runtime["max_matches"]) is not int or type(runtime["port"]) is not int:
            raise ValueError("E_LIVE_CONFIG_INTEGER")
        selected = set(provider["fixture_ids"])
        fallback = set(provider["events_fallback_fixture_ids"])
        if (
            len(selected) > runtime["max_matches"]
            or not fallback <= selected
            or (not provider["events_fallback_enabled"] and fallback)
        ):
            raise ValueError("E_LIVE_CONFIG_SCOPE")
        if require_enabled and not value["enabled"]:
            raise ValueError("E_LIVE_CONFIG_DISABLED")
        private_path(runtime["run_output_dir"])
        refs = [
            operator["capture_profile_path"],
            runtime["platform_qualification_path"],
            *(ref for name, ref in value["gates"].items() if name != "live_intent_path"),
        ]
        for ref in refs:
            if ref is not None:
                private_path(ref, must_exist=value["enabled"])
        # Intent creation follows config creation; the launcher validates its bytes before I/O.
        if value["gates"]["live_intent_path"] is not None:
            private_path(value["gates"]["live_intent_path"])
        if value["enabled"]:
            profile = private_path(operator["capture_profile_path"], must_exist=True)
            if (
                hashlib.sha256(profile.read_bytes()).hexdigest()
                != operator["profile_evidence_hash"]
            ):
                raise ValueError("E_LIVE_CONFIG_PROFILE_HASH")
        return LiveConfig(copy.deepcopy(value), hashlib.sha256(raw).hexdigest())
    except Exception:
        raise ValueError("E_LIVE_CONFIG") from None
