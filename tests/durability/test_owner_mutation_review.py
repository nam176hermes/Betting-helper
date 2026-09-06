"""Coherent artifact substitutions must still obey real owner semantics."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from moj_discovery.canonical import canonical_content_hash
from tools.owner_mutation_evidence import campaign
from tools.run_indexeddb_crash_matrix import PACK, REGISTRY, run_indexeddb_case
from tools.run_sqlite_crash_matrix import run_sqlite_crash_matrix
from tools.verify_repair_evidence import capture_binding, verify_owner_mutation


@pytest.fixture(scope="module")
def review_records(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    base = tmp_path_factory.mktemp("mutation-review")
    entries = json.loads((PACK / "docs/registries/crash-harness-registry.v1.json").read_text())[
        "entries"
    ]
    sql = next(row for row in entries if row["harness"] == "SQLITE_TRANSACTION")
    browser = next(row for row in entries if row["harness"] == "CHROME_INDEXEDDB")
    sql_report = run_sqlite_crash_matrix(PACK, base / "sql", entries=[sql])
    control = run_indexeddb_case(browser, base / "browser-control", full=True)
    browser_rows = campaign([browser], base / "browser-mutations", [control])
    return {"SQL": sql_report["mutation_results"][1], "BROWSER": browser_rows[0]}


@pytest.mark.parametrize(
    ("damage", "error"),
    [
        ("trial-fail", "E_OWNER_MUTATION_TRIAL"),
        ("control-fail", "E_OWNER_MUTATION_CONTROL"),
        ("backend-observed-pid", "E_ACK_PROCESS_PROVENANCE"),
        ("backend-raw-missing", "E_ACK_PROCESS_PROVENANCE"),
        ("sql-expected", "E_OWNER_MUTATION_INPUT"),
        ("sql-oracle", "E_OWNER_MUTATION_INPUT"),
        ("sql-extra-field", "E_OWNER_MUTATION_INPUT"),
    ],
)
def test_coherent_review_substitutions_reject(
    review_records: dict[str, Any], monkeypatch: pytest.MonkeyPatch, damage: str, error: str
) -> None:
    sql = damage.startswith("sql-")
    row = copy.deepcopy(review_records["SQL" if sql else "BROWSER"])
    execution = row["execution"]
    overlay: dict[Path, bytes] = {}

    def replace_json(descriptor: dict[str, Any], value: Any) -> None:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        overlay[Path(descriptor["path"])] = raw
        descriptor["sha256"] = hashlib.sha256(raw).hexdigest()

    if damage == "trial-fail":
        execution.update(status="FAIL", result="FAIL")
    elif damage == "control-fail":
        row["control"].update(status="FAIL", result="FAIL")
    elif damage == "backend-observed-pid":
        execution["backend_processes"][0]["observed"]["pid"] += 1
    elif damage == "backend-raw-missing":
        execution["backend_processes"][0]["raw_process"] = {
            "path": str(Path(execution["case_directory"]) / "nonexistent-process.json"),
            "sha256": "0" * 64,
        }
    else:
        original = execution["original_input"]
        original[damage.removeprefix("sql-")] = {"retained_rows": 99}
        original["content_hash"] = canonical_content_hash(
            "RawObservation", original, registry_path=REGISTRY
        )
        execution["mutated_input"] = {**original, "content_hash": "0" * 64}
        replace_json(execution["processes"][0]["input"], {"observation": original})
        replace_json(
            execution["processes"][2]["input"],
            {"run_id": original["discovery_run_id"], "observation": execution["mutated_input"]},
        )
    for record in (row["control"], execution):
        if "terminal_artifact" in record:
            replace_json(
                record["terminal_artifact"],
                {key: value for key, value in record.items() if key != "terminal_artifact"},
            )
    replace_json(row["process"]["stdout"], {"pid": row["process"]["pid"], "result": execution})
    replace_json(
        row["terminal_artifact"],
        {key: value for key, value in row.items() if key != "terminal_artifact"},
    )
    binding = capture_binding()
    read_bytes, read_text = Path.read_bytes, Path.read_text
    monkeypatch.setattr(
        Path, "read_bytes", lambda path: overlay[path] if path in overlay else read_bytes(path)
    )
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda path, *args, **kwargs: (
            overlay[path].decode() if path in overlay else read_text(path, *args, **kwargs)
        ),
    )
    with pytest.raises(ValueError, match=error):
        verify_owner_mutation("SQLITE_TRANSACTION" if sql else "CHROME_INDEXEDDB", row, binding)
