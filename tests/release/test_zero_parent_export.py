import hashlib
import json
from pathlib import Path

from tools.export_zero_parent_candidate import export_zero_parent_candidate


def test_export_contains_only_candidate_inventory_and_exact_modes(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    included = source / "app.py"
    included.write_text("print('ok')\n")
    included.chmod(0o755)
    (source / "unqualified.txt").write_text("do not copy\n")
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({
        "schema_version": "candidate-qualification-receipt/v1",
        "production_authority": "NONE",
        "inventory": [{
            "path": "app.py", "sha256": hashlib.sha256(included.read_bytes()).hexdigest(),
            "size": str(included.stat().st_size), "mode": "100755",
        }],
    }))
    ownership = tmp_path / "ownership.json"
    ownership.write_text(json.dumps({"entries": [{"path": "runtime/app.py"}]}))

    export_zero_parent_candidate(source, tmp_path / "final", receipt, ownership)

    copied = tmp_path / "final/app.py"
    assert copied.read_bytes() == included.read_bytes()
    assert copied.stat().st_mode & 0o777 == 0o755
    assert not (tmp_path / "final/unqualified.txt").exists()
