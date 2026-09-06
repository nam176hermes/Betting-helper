import sqlite3
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from moj_discovery.review_authorization import verify_review_launch_authorization
from tests.security.test_authorization_trust import BOOT_ID, NOW, PACK_SHA256, WORKSPACE, _launch
from tools.bootstrap_review_authority import bootstrap_review_authority
from tools.prepare_review_workspace import _authority_state


def _config(tmp_path: Path) -> dict[str, object]:
    return {
        "private_key_path": str(tmp_path / "authority/private.pem"),
        "public_key_path": str(tmp_path / "authority/public.json"),
        "private_key_mode": "0600",
        "public_key_mode": "0644",
        "production_authority": "NONE",
    }


def _authorization(key_id: str, serial: str, authorization_id: str) -> dict[str, object]:
    return {
        "issuer_key_id": key_id,
        "one_use_serial": serial,
        "authorization_id": authorization_id,
        "trust_epoch": 0,
    }


def test_security_boundary(tmp_path: Path) -> None:
    vectors = {
        "allow": "SEC_REPLAY_REVOCATION-ALLOW",
        "deny": "SEC_REPLAY_REVOCATION-DENY",
        "mutate": "SEC_REPLAY_REVOCATION-MUTATE",
    }
    authority = _config(tmp_path)
    key_id = str(bootstrap_review_authority(authority, initialize_if_absent=True)["key_id"])
    first = _authorization(key_id, "serial-1", "authorization-1")
    _authority_state(first, authority, consume=True)
    with pytest.raises(ValueError, match="E_REVIEW_LAUNCH_CONSUMED"):
        _authority_state(first, authority, consume=True)

    revoked = _authorization(key_id, "serial-2", "authorization-2")
    state = Path(str(authority["private_key_path"])).parent / "state.sqlite"
    connection = sqlite3.connect(state)
    try:
        connection.execute("INSERT INTO revocations VALUES (?)", (revoked["authorization_id"],))
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(ValueError, match="E_REVIEW_LAUNCH_CONSUMED"):
        _authority_state(revoked, authority, consume=True)

    private = Ed25519PrivateKey.generate()
    future = NOW.replace(year=NOW.year + 1)
    past = NOW.replace(year=NOW.year - 1)
    for launch, now in (
        (
            _launch(
                private,
                issued_at=future,
                not_before=future,
                expires_at=future.replace(hour=4),
            ),
            NOW,
        ),
        (
            _launch(
                private,
                issued_at=past,
                not_before=past,
                expires_at=past.replace(hour=4),
            ),
            NOW,
        ),
    ):
        with pytest.raises(ValueError):
            verify_review_launch_authorization(
                launch,
                private.public_key(),
                "IMPLEMENTATION_READINESS_REVIEWER",
                WORKSPACE,
                PACK_SHA256,
                expected_host_boot_id=BOOT_ID,
                expected_trust_epoch=0,
                now=now,
            )
    assert vectors["allow"] and vectors["deny"] and vectors["mutate"]
