"""Verify immutable review and provenance inputs already seeded in pack/."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pack_path(config_path: Path, value: str) -> Path:
    relative = value.removeprefix("pack/")
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError("E_SOURCE_PATH")
    return config_path.parents[2] / relative


def import_review_sources(config_path: Path) -> dict[str, object]:
    config_path = config_path.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    verified: list[str] = []
    for row in config["required_plan_source_files"]:
        path = _pack_path(config_path, row["path"])
        if not path.is_file():
            raise ValueError(f"E_SOURCE_MISSING:{row['path']}")
        if "size" in row and path.stat().st_size != row["size"]:
            raise ValueError(f"E_SOURCE_SIZE:{row['path']}")
        if sha256(path) != row["sha256"]:
            raise ValueError(f"E_SOURCE_HASH:{row['path']}")
        verified.append(row["path"])
    review = _pack_path(config_path, config["plan_review_import"])
    if sha256(review) != config["v6_3_1_plan_review_input_sha256"]:
        raise ValueError("E_REVIEW_IMPORT_HASH")
    receipt = {
        "schema_version": "source-provenance/v1",
        "result": "PASS",
        "source_inputs_sha256": sha256(config_path),
        "review_sha256": sha256(review),
        "verified_paths": verified,
    }
    payload = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    receipt_path = config_path.parents[2] / "docs/receipts/source-provenance.v1.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    if receipt_path.exists():
        if receipt_path.read_text(encoding="utf-8") != payload:
            raise ValueError("E_SOURCE_RECEIPT_MISMATCH")
    else:
        receipt_path.write_text(payload, encoding="utf-8")
    return {"result": "PASS", "verified_files": len(verified), "review": str(review)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(import_review_sources(args.config), sort_keys=True))


if __name__ == "__main__":
    main()
