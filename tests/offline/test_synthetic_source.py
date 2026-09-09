import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import rfc8785

from moj_discovery.synthetic_source import (
    load_synthetic_observations,
    validate_synthetic_observation,
)


def context() -> dict[str, Any]:
    return {
        "schema_version": "offline-run-context/v1",
        "source_kind": "SYNTHETIC_TEST",
        **{name: str(uuid4()) for name in ["run_id", "browser_run_id", "producer_id", "stream_id"]},
        "generation": "0",
        "backend_url": "ws://127.0.0.1:8765/offline",
        "allowed_extension_origin": "chrome-extension://" + "a" * 32,
        "max_duration_seconds": 600,
        "max_frame_bytes": 262144,
        "max_raw_bytes": 65536,
        "max_batch_records": 32,
        "normal_spool_limit_bytes": "133169152",
        **{
            name: "a" * 64
            for name in ["code_sha256", "vendor_sha256", "schema_lock_sha256", "scenario_sha256"]
        },
        "live_authority": False,
        "provider_authority": False,
        "money_authority": False,
    }


def scenario(path: Path, ctx: dict[str, Any], count: int = 3) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": "offline-scenario/v1",
                "source_kind": "SYNTHETIC_TEST",
                "context": ctx,
                "record_count": count,
            }
        )
    )
    return path


def test_source_is_deterministic_synthetic_accounting(tmp_path: Path) -> None:
    ctx = context()
    path = scenario(tmp_path / "scenario.json", ctx)
    rows = load_synthetic_observations(path)
    assert rows == load_synthetic_observations(path)
    assert [r["sequence"] for r in rows] == ["1", "2", "3"]
    assert len({r["raw_observation_id"] for r in rows}) == 3
    assert all(
        r["observation_kind"] == "TERMINAL" and r["production_authority"] == "NONE" for r in rows
    )
    assert all(validate_synthetic_observation(rfc8785.dumps(r), ctx) == r for r in rows)


@pytest.mark.parametrize("mutation", ["live", "unknown", "wrong-run", "bad-hash", "secret"])
def test_bad_source_never_crosses_validation(tmp_path: Path, mutation: str) -> None:
    ctx = context()
    path = scenario(tmp_path / "scenario.json", ctx)
    if mutation in {"live", "unknown"}:
        manifest = json.loads(path.read_text())
        if mutation == "live":
            manifest["source_kind"] = "OPERATOR_OBSERVED"
        else:
            manifest["url"] = "https://example.invalid"
        path.write_text(json.dumps(manifest))
        with pytest.raises(ValueError, match="E_OFFLINE_SOURCE_BINDING"):
            load_synthetic_observations(path)
    else:
        row = load_synthetic_observations(path)[0]
        row[
            {"wrong-run": "discovery_run_id", "bad-hash": "content_hash", "secret": "cookie"}[
                mutation
            ]
        ] = str(uuid4()) if mutation == "wrong-run" else "f" * 64
        with pytest.raises(ValueError, match="^E_OFFLINE_"):
            validate_synthetic_observation(rfc8785.dumps(row), ctx)
