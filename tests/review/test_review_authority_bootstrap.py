import json
from pathlib import Path

from tools.bootstrap_review_authority import bootstrap_review_authority


def test_private_key_stays_outside_all_governed_roots(tmp_path: Path) -> None:
    private = tmp_path / "host/review/private.pem"
    public = tmp_path / "host/review/public.json"
    config: dict[str, object] = {
        "private_key_path": str(private),
        "public_key_path": str(public),
        "private_key_mode": "0600",
        "public_key_mode": "0644",
        "production_authority": "NONE",
    }
    result = bootstrap_review_authority(config, initialize_if_absent=True)
    assert result["result"] == "PASS"
    assert private.stat().st_mode & 0o777 == 0o600
    assert public.stat().st_mode & 0o777 == 0o644
    published = json.loads(public.read_text())
    assert set(published) == {"schema_version", "key_id", "role", "public_key_b64url", "trust_epoch"}
    assert "private_key" not in published
    assert (private.parent / "state.sqlite").stat().st_mode & 0o777 == 0o600
    assert bootstrap_review_authority(config, initialize_if_absent=True)["key_id"] == published["key_id"]
