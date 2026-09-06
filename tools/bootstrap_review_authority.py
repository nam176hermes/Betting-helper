"""Create or verify the host-only review key and one-use state database."""
# ruff: noqa: E402
from __future__ import annotations

import argparse
import base64
import json
import os
import sqlite3
import stat
import sys
from hashlib import sha256
from pathlib import Path

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RUNTIME_ROOT), str(RUNTIME_ROOT / "src")]

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from moj_discovery.review_authorization import key_id


def _regular(path: Path) -> None:
    if path.is_symlink() or not path.is_file() or stat.S_ISLNK(path.lstat().st_mode):
        raise ValueError("E_REVIEW_AUTHORITY_CONFIG")


def _state(path: Path, key: str, epoch: int) -> None:
    if path.exists():
        _regular(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS authority_state (key_id TEXT PRIMARY KEY, trust_epoch INTEGER NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS consumed_serials (authority_key_id TEXT NOT NULL, one_use_serial TEXT NOT NULL, PRIMARY KEY (authority_key_id, one_use_serial))"
        )
        connection.execute("CREATE TABLE IF NOT EXISTS revocations (authorization_id TEXT PRIMARY KEY)")
        stored = connection.execute("SELECT key_id, trust_epoch FROM authority_state").fetchall()
        if not stored:
            connection.execute("INSERT INTO authority_state VALUES (?, ?)", (key, epoch))
        elif stored != [(key, epoch)]:
            raise ValueError("E_REVIEW_AUTHORITY_CONFIG")
        connection.commit()
    finally:
        connection.close()
    os.chmod(path, 0o600)


def bootstrap_review_authority(
    config: dict[str, object], *, initialize_if_absent: bool = False
) -> dict[str, object]:
    private_path = Path(str(config["private_key_path"]))
    public_path = Path(str(config["public_key_path"]))
    if (
        config.get("production_authority") != "NONE"
        or not private_path.is_absolute()
        or not public_path.is_absolute()
        or private_path.parent != public_path.parent
    ):
        raise ValueError("E_REVIEW_AUTHORITY_CONFIG")
    state_path = private_path.parent / "state.sqlite"
    present = (private_path.exists(), public_path.exists())
    if not all(present):
        if not initialize_if_absent or any(present):
            raise ValueError("E_REVIEW_AUTHORITY_ABSENT")
        private_path.parent.mkdir(parents=True, exist_ok=True)
        key = Ed25519PrivateKey.generate()
        private_path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            )
        )
        raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        public_path.write_text(
            json.dumps(
                {
                    "schema_version": "review-public-key/v1", "key_id": "key:ed25519:" + sha256(raw).hexdigest(),
                    "role": "HOST_REVIEW_AUTHORITY",
                    "public_key_b64url": base64.urlsafe_b64encode(raw).decode().rstrip("="), "trust_epoch": 0,
                }, sort_keys=True, separators=(",", ":")
            ) + "\n"
        )
    _regular(private_path)
    _regular(public_path)
    try:
        private = serialization.load_pem_private_key(private_path.read_bytes(), password=None)
        public = json.loads(public_path.read_text())
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("E_REVIEW_AUTHORITY_CONFIG") from error
    if not isinstance(private, Ed25519PrivateKey) or not isinstance(public, dict) or set(public) != {
        "schema_version", "key_id", "role", "public_key_b64url", "trust_epoch"
    }:
        raise ValueError("E_REVIEW_AUTHORITY_CONFIG")
    raw = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    expected = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    epoch = public.get("trust_epoch")
    if (
        public.get("schema_version") != "review-public-key/v1"
        or public.get("role") != "HOST_REVIEW_AUTHORITY"
        or public.get("key_id") != key_id(private.public_key())
        or public.get("public_key_b64url") != expected
        or not isinstance(epoch, int)
        or isinstance(epoch, bool)
        or epoch < 0
    ):
        raise ValueError("E_REVIEW_AUTHORITY_CONFIG")
    os.chmod(private_path, int(str(config["private_key_mode"]), 8))
    os.chmod(public_path, int(str(config["public_key_mode"]), 8))
    _state(state_path, key_id(private.public_key()), epoch)
    return {"result": "PASS", "key_id": public["key_id"], "production_authority": "NONE"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--initialize-if-absent", action="store_true")
    args = parser.parse_args()
    print(json.dumps(bootstrap_review_authority(json.loads(args.config.read_text()), initialize_if_absent=args.initialize_if_absent), sort_keys=True))


if __name__ == "__main__":
    main()
