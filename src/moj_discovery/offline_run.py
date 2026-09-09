"""Fresh synthetic run seeds in the real governed SQLite store."""

import hashlib
import os
from contextlib import closing
from pathlib import Path
from time import time_ns
from typing import Any

import rfc8785

from .offline_protocol import validate_context
from .store import RunStore


def create_offline_run(run_dir: Path, context: dict[str, Any]) -> RunStore:
    validate_context(context)
    if any(path.is_symlink() for path in (run_dir, *run_dir.parents)):
        raise ValueError("E_OFFLINE_RUN_PATH")
    run_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    (run_dir / "raw").mkdir(mode=0o700)
    descriptor = os.open(run_dir / "context.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(rfc8785.dumps(context))
        output.flush()
        os.fsync(output.fileno())
    store = RunStore(run_dir / "run.sqlite3")
    store.bootstrap_v1()
    os.chmod(store.db_path, 0o600)
    identity = hashlib.sha256(
        rfc8785.dumps([context["run_id"], context["stream_id"], context["generation"]])
    ).hexdigest()
    now = time_ns() // 1000
    with closing(store.connect()) as connection, connection:
        connection.execute(
            "INSERT INTO run_meta VALUES (?,1,'OPEN',"
            "'offline-only:synthetic-not-authorization',?,?,?,NULL)",
            (context["run_id"], context["vendor_sha256"], context["code_sha256"], now),
        )
        connection.execute(
            "INSERT INTO stream_generations VALUES (?,?,?,?,?,?,NULL,'ACTIVE',?,NULL,NULL)",
            (
                "generation:" + identity,
                context["run_id"],
                context["browser_run_id"],
                context["producer_id"],
                context["stream_id"],
                int(context["generation"]),
                now,
            ),
        )
        connection.execute(
            "INSERT INTO coherence_epochs VALUES (?,?,'fixture:offline-accounting',"
            "0,NULL,'OPEN',NULL,NULL,?,0)",
            ("epoch:" + identity, context["run_id"], now),
        )
        connection.execute(
            "INSERT INTO coherence_controllers VALUES (?,?,'fixture:offline-accounting',"
            "'OPEN',?,NULL,NULL,NULL,0,?)",
            ("controller:" + identity, context["run_id"], "epoch:" + identity, now),
        )
    directory = os.open(run_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return store
