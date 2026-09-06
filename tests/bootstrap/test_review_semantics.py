import json
from pathlib import Path

import pytest

from moj_discovery.governance import validate_semantic_vector_file


def test_review_counterexamples_are_present() -> None:
    validate_semantic_vector_file("review-semantic-v1.json")


def test_open_semantic_vector_contract_is_rejected(tmp_path: Path) -> None:
    vector_dir = tmp_path / "vectors"
    vector_dir.mkdir()
    (vector_dir / "review-semantic-v1.json").write_text(
        json.dumps(
            {
                "production_authority": "NONE",
                "vectors": [{"case_id": "UNBOUNDED"}],
                "vector_contract": {"patch_semantics": "UNSPECIFIED"},
            }
        )
    )
    with pytest.raises(AssertionError):
        validate_semantic_vector_file("review-semantic-v1.json", tmp_path)
