"""Freeze a performance-blind availability view; never trains or selects a model."""

import copy
import hashlib
import json
import sqlite3
from collections import Counter
from collections.abc import Sequence
from contextlib import closing
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import rfc8785

from .live_replay import file_hash

RunRef = Path
QualityView = dict[str, Any]
DataManifest = dict[str, Any]


def freeze_dataset_manifest(run_refs: Sequence[RunRef], quality_view: QualityView) -> DataManifest:
    from tools.qualify_live_readonly import qualify_recorded_run

    required = {"selection_basis", "historical_data", "chronological_partitions"}
    if (
        type(quality_view) is not dict
        or not required <= set(quality_view) <= required | {"data_rights_refs"}
        or quality_view["selection_basis"] != "DATA_QUALITY_ONLY"
        or quality_view["historical_data"] not in {"NOT_SUPPLIED", "PARTIAL", "PRESENT"}
        or len(run_refs) > 100
        or len(set(run_refs)) != len(run_refs)
    ):
        raise ValueError("E_DATA_MANIFEST_INPUT")
    partitions = quality_view["chronological_partitions"]
    if type(partitions) is not list or len(partitions) > 3:
        raise ValueError("E_DATA_MANIFEST_PARTITIONS")
    last = None
    for index, part in enumerate(partitions):
        if (
            set(part) != {"name", "start", "end"}
            or part["name"] != ("TRAIN", "VALIDATION", "TEST")[index]
        ):
            raise ValueError("E_DATA_MANIFEST_PARTITIONS")
        start, end = date.fromisoformat(part["start"]), date.fromisoformat(part["end"])
        if start >= end or last is not None and start < last:
            raise ValueError("E_DATA_MANIFEST_PARTITIONS")
        last = end
    rights = []
    for ref in quality_view.get("data_rights_refs", []):
        if set(ref) != {"source", "path", "sha256"} or ref["source"] not in {
            "API_FOOTBALL",
            "MISE_O_JEU",
        }:
            raise ValueError("E_DATA_MANIFEST_RIGHTS")
        path = Path(ref["path"])
        if (
            not path.is_absolute()
            or not path.is_file()
            or any(p.is_symlink() for p in (path, *path.parents))
            or path.stat().st_size > 65536
            or file_hash(path) != ref["sha256"]
        ):
            raise ValueError("E_DATA_MANIFEST_RIGHTS")
        record = json.loads(path.read_bytes())
        if (
            set(record) != {"source", "status", "uses", "reviewer_role", "reviewed_at_utc"}
            or record["source"] != ref["source"]
            or record["status"] not in {"ACCEPTED", "REVIEW_REQUIRED"}
            or record["uses"] != ["LOCAL_RECORDING", "RESEARCH"]
            or record["reviewer_role"] != "USER_DATA_ACCESS_REVIEW"
            or datetime.fromisoformat(record["reviewed_at_utc"]) > datetime.now(UTC)
        ):
            raise ValueError("E_DATA_MANIFEST_RIGHTS")
        rights.append({**ref, "status": record["status"]})
    if len(rights) > 2 or len({r["source"] for r in rights}) != len(rights):
        raise ValueError("E_DATA_MANIFEST_RIGHTS")
    rows, targets, qualifications = [], [], []
    for run in run_refs:
        qualified = qualify_recorded_run(run)
        qualifications.append(qualified)
        database = run.absolute() / "live.sqlite3"
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
            db.execute("PRAGMA query_only=ON")
            events = [
                json.loads(row[0])
                for row in db.execute(
                    "SELECT payload_canonical FROM live_events ORDER BY receive_index"
                )
            ]
        provider = [e["payload"] for e in events if e["payload_type"] == "ProviderState"]
        bindings = [e["payload"]["after"] for e in events if e["payload_type"] == "BindingChange"]
        rows.append(
            {
                "run_id": qualified["run_id"],
                "source_kind": qualified["source_kind"],
                "identity": [
                    {
                        k: b[k]
                        for k in (
                            "provider_fixture_id",
                            "league_id",
                            "season",
                            "home_id",
                            "away_id",
                            "kickoff_utc",
                        )
                    }
                    for b in bindings
                ],
                "coverage": {
                    "event_count": len(events),
                    "provider_observations": len(provider),
                    "ft_comparisons": qualified["complete_ft_book_checks"],
                },
                "timing": {
                    "first_receipt_utc": events[0]["observed_at_utc"] if events else None,
                    "last_receipt_utc": events[-1]["observed_at_utc"] if events else None,
                    "source_age": "UNKNOWN_UNLESS_SOURCE_TIMESTAMP_OBSERVED",
                },
                "corrections_and_quality_flags": dict(
                    Counter(flag for state in provider for flag in state["quality_flags"])
                ),
                "missingness": qualified["missing_inputs"],
                "quota": {"real_http_attempts": qualified["real_http_attempts"]},
                "cost": "UNKNOWN",
                "settlement": {
                    "FT": "NORMAL_TIME_INCLUDING_STOPPAGE",
                    "H1": "NOT_QUALIFIED",
                    "H2": "NOT_QUALIFIED",
                },
            }
        )
        if file_hash(database) != qualified["artifacts"]["live.sqlite3"]:
            raise ValueError("E_DATA_MANIFEST_SOURCE_CHANGED")
        targets.append(
            {
                "path": str(database),
                "sha256": file_hash(database),
                "content": "RECORDED_OBSERVATIONS_ONLY_NOT_SETTLED_OUTCOME_LABELS",
            }
        )
    accepted = len(rights) == 2 and all(r["status"] == "ACCEPTED" for r in rights)
    result: DataManifest = {
        "schema_version": "part-b-data-manifest/v1",
        "has_source_provenance": bool(qualifications),
        "quality_view": {k: copy.deepcopy(quality_view[k]) for k in required} | {"runs": rows},
        "actual_targets": targets,
        "rights_evidence": rights,
        "data_rights": "USER_REVIEW_RECORDED" if accepted else "REVIEW_REQUIRED",
        "SCOPE0_READY_FOR_REVIEW": bool(qualifications)
        and accepted
        and all(q["LIVE_READ_ONLY_PASS"] for q in qualifications),
        "MODEL_ENABLED": False,
        "MONEY_READY": "NO",
        "PART_C_ACTIVATED": False,
    }
    return {**result, "manifest_sha256": hashlib.sha256(rfc8785.dumps(result)).hexdigest()}
