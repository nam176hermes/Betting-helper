import sqlite3
import sys
import time
from pathlib import Path

database, ddl_path, boundary = sys.argv[1:]
connection = sqlite3.connect(database)
connection.executescript(Path(ddl_path).read_text())
hash_a = "a" * 64
raw_hash = "1" * 64
revision_hash = "2" * 64
h0 = "149300a0e3954885a1d6c0f13a9d1101227cc21cce37bd6b7c72eab641741c0c"
h1 = "739669d828057e94c856e7725ed05218e26639610d4ce58c2a5568244a16fc28"
identity = ("run", "browser", "producer:test", "stream", 0)
connection.execute(
    "INSERT INTO run_meta VALUES (?,?,?,?,?,?,?,?)",
    ("run", 1, "OPEN", "authorization", hash_a, hash_a, 0, None),
)
connection.execute(
    "INSERT INTO stream_generations VALUES (?,?,?,?,?,?,?,?,?,?,?)",
    ("generation", *identity, None, "ACTIVE", 0, None, None),
)
connection.commit()

statements = [
    (
        "INSERT INTO raw_commits VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("raw", *identity, 1, "observation", raw_hash, h0, h1, 1, "APPLIED", 1),
    ),
    (
        "INSERT INTO application_records VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("application", "raw", *identity, 1, raw_hash, h0, "APPLIED", 2),
    ),
    (
        "INSERT INTO derived_revisions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("revision", "application", "raw", *identity, 1, 1, None, revision_hash, 3),
    ),
    (
        "INSERT INTO reducer_cursors VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("cursor", "revision", *identity, 1, h0, h1, 1, raw_hash, 4),
    ),
    (
        "INSERT INTO ack_outbox VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("outbox", "raw", "application", "revision", "cursor", *identity, 1, h1, 1, 5),
    ),
]

connection.execute("BEGIN IMMEDIATE")
for index, (statement, parameters) in enumerate(statements, 1):
    connection.execute(statement, parameters)
    if str(index) == boundary:
        print("READY", flush=True)
        time.sleep(300)
if boundary == "commit":
    print("READY", flush=True)
    time.sleep(300)
connection.commit()
