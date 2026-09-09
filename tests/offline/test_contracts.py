"""The offline wire carries real raw records and remains disjoint from V1."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from referencing import Registry, Resource

from moj_discovery.canonical import parse_strict_json
from moj_discovery.offline_protocol import validate_frame
from tests.repairs.test_shared_ingest_persistence import BROWSER, PRODUCER, RUN, STREAM, observation

ROOT = Path(__file__).resolve().parents[2]
VENDOR = ROOT / "vendor/hybrid-discovery-v6.3.6/schemas"
CONTRACTS = ROOT / "contracts/offline_slice/v1"


def validator() -> Draft202012Validator:
    # Before migration, exercise the actual inherited wire to expose its missing payload.
    path = CONTRACTS / "frame.schema.json"
    if not path.exists():
        path = VENDOR / "loopback-messages.schema.json"
    schema = json.loads(path.read_text())
    resources = [json.loads(p.read_text()) for p in VENDOR.glob("*.json")]
    resources.append(schema)
    registry = Registry().with_resources((s["$id"], Resource.from_contents(s)) for s in resources)
    return Draft202012Validator(schema, registry=registry)


def batch() -> dict[str, Any]:
    return {
        "protocol": "BH_OFFLINE_WIRE_V1",
        "session_id": RUN,
        "direction": "CLIENT_TO_BACKEND",
        "counter": "3",
        "message_type": "BATCH",
        "body": {
            "batch_id": RUN,
            "run_id": RUN,
            "browser_run_id": BROWSER,
            "producer_id": PRODUCER,
            "stream_id": STREAM,
            "generation": "0",
            "first_sequence": "1",
            "last_sequence": "1",
            "observations": [observation()],
        },
        "mac": "a" * 64,
    }


def test_offline_wire_has_full_raw_payload() -> None:
    assert validator().is_valid(batch()), (
        "Current wire cannot carry the actual full raw observation"
    )


@pytest.mark.parametrize("mutation", ["hash-only", "producer-slug", "command", "raw-extra"])
def test_closed_payload_rejects_old_wire_and_extra_fields(mutation: str) -> None:
    frame = copy.deepcopy(batch())
    if mutation == "hash-only":
        frame["body"]["observations"] = [frame["body"]["observations"][0]["content_hash"]]
    elif mutation == "producer-slug":
        frame["body"]["producer_id"] = "producer:test"
    elif mutation == "command":
        frame["body"]["command"] = "place-bet"
    else:
        frame["body"]["observations"][0]["token"] = "synthetic-poison"  # noqa: S105 -- deliberately invalid synthetic token field
    assert not validator().is_valid(frame)


def test_duplicate_json_keys_rejected_before_schema() -> None:
    with pytest.raises(ValueError):
        parse_strict_json(b'{"counter":"1","counter":"2"}')


def accept_frame(frame: dict[str, Any]) -> None:
    validate_frame(frame)


def test_mixed_streams_rejected() -> None:
    frame = batch()
    frame["body"]["observations"][0]["stream_id"] = RUN
    with pytest.raises(ValueError):
        accept_frame(frame)


def test_typescript_uses_same_local_schema_and_identity_checks(tmp_path: Path) -> None:
    import subprocess

    frame_path = tmp_path / "frame.json"
    frame_path.write_text(json.dumps(batch()))
    script = """
import {readFileSync, readdirSync} from 'node:fs';
import {validateOfflineFrame} from './extension/.test-build/src/offline/protocol.js';
import {validateArtifact} from './extension/.test-build/src/schema-registry.js';
const schemas = ['vendor/hybrid-discovery-v6.3.6/schemas','contracts/offline_slice/v1']
.flatMap(dir => readdirSync(dir).filter(n => n.endsWith('.schema.json'))
.map(n => JSON.parse(readFileSync(dir+'/'+n,'utf8'))));
const frame=JSON.parse(readFileSync(process.argv[1],'utf8'));
validateOfflineFrame(frame, value =>
 validateArtifact(value, "urn:betting-helper:offline-slice:frame:v1", schemas));
frame.body.observations[0].stream_id=frame.body.run_id;
let rejected=false;
try {validateOfflineFrame(frame, value =>
 validateArtifact(value, "urn:betting-helper:offline-slice:frame:v1", schemas));}
catch {rejected=true;}
if(!rejected) throw new Error('MIXED_STREAM_ACCEPTED');
"""
    subprocess.run(  # noqa: S603,S607 -- installed Node, fixed program, owned fixture path
        ["node", "--input-type=module", "-e", script, str(frame_path)],  # noqa: S607 -- pinned Node
        cwd=ROOT,
        check=True,
        timeout=20,
    )
