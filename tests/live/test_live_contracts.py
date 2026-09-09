import copy
import json
import subprocess
from pathlib import Path

import pytest

from moj_discovery.live_contracts import validate_live_record


def test_complete_book_and_detached_output(synthetic_book):
    book = validate_live_record(synthetic_book, "MarketBook")
    assert book == synthetic_book
    book["selections"]["HOME"]["decimal_odds"] = "9.00"
    assert synthetic_book["selections"]["HOME"]["decimal_odds"] == "2.10"


@pytest.mark.parametrize(
    "field,value",
    [
        ("cookie", "TEST_ONLY"),
        ("capture_evidence_tier", "NATIVE_ATOMIC"),
        ("browser_mono_us", "9223372036854775808"),
        ("browser_mono_us", True),
        ("binding_revision", "01"),
        ("operator_score", {"home": True, "away": 0}),
        ("operator_score", {"home": 101, "away": 0}),
        ("observed_at_utc", "yesterday"),
        ("quality_flags", ["e\u0301"]),
        ("market_id", "bad\nidentifier"),
    ],
)
def test_closed_book(synthetic_book, field, value):
    synthetic_book[field] = value
    with pytest.raises(ValueError, match="E_LIVE_RECORD"):
        validate_live_record(synthetic_book, "MarketBook")


@pytest.mark.parametrize("odds", ["1", "1.000000", "0.99", "NaN", "Infinity", "2.1234567", 2.1])
def test_odds(synthetic_book, odds):
    synthetic_book["selections"]["HOME"]["decimal_odds"] = odds
    with pytest.raises(ValueError):
        validate_live_record(synthetic_book, "MarketBook")


def test_complete_unique_hda(synthetic_book):
    bad = copy.deepcopy(synthetic_book)
    del bad["selections"]["DRAW"]
    with pytest.raises(ValueError):
        validate_live_record(bad, "MarketBook")
    bad = copy.deepcopy(synthetic_book)
    bad["selections"]["DRAW"]["selection_id"] = bad["selections"]["HOME"]["selection_id"]
    with pytest.raises(ValueError):
        validate_live_record(bad, "MarketBook")


def test_live_union_rejects_synthetic_and_source_confusion(synthetic_book):
    event = {
        "protocol": "BH_LIVE_READONLY_V1",
        "run_id": synthetic_book["binding_id"],
        "source_kind": "OPERATOR",
        "stream_id": synthetic_book["document_epoch"],
        "generation": "0",
        "sequence": "1",
        "observation_id": synthetic_book["clock_domain_id"],
        "observed_at_utc": synthetic_book["observed_at_utc"],
        "received_mono_us": "1",
        "previous_hash": "0" * 64,
        "content_hash": "a" * 64,
        "payload_type": "MarketBook",
        "payload": synthetic_book,
    }
    assert validate_live_record(event, "LiveEvent")["source_kind"] == "OPERATOR"
    for field, value in [
        ("source_kind", "PROVIDER"),
        ("protocol", "BH_OFFLINE_WIRE_V1"),
        ("payload_type", "RawObservation"),
        ("sequence", "0"),
    ]:
        with pytest.raises(ValueError):
            validate_live_record({**event, field: value}, "LiveEvent")


def test_no_arbitrary_schema_or_payload():
    for kind in ["https://untrusted.invalid/schema", "../config", "RawObservation", "MarketBook"]:
        with pytest.raises(ValueError):
            validate_live_record({"payload": {"cookie": "TEST_ONLY"}}, kind)


def test_typescript_closed_contract_executes(synthetic_book):
    """Exercise emitted TS against the same source schemas, not compile-only evidence."""
    code = """
      import {createRequire} from 'node:module';
      import fs from 'node:fs';
      import assert from 'node:assert/strict';
      import {validateLiveRecord} from './extension/.test-build/live/src/live/contracts.js';
      const require = createRequire(new URL('./extension/package.json', import.meta.url));
      const Ajv = require('ajv/dist/2020').default;
      const ajv = new Ajv({strict:false});
      require('ajv-formats')(ajv);
      const schema = JSON.parse(fs.readFileSync('contracts/live_readonly/v1/records.schema.json'));
      ajv.addSchema(schema);
      const validate = (value, kind) => ajv.getSchema(schema.$id+'#/$defs/'+kind)(value);
      const book = JSON.parse(fs.readFileSync(0, 'utf8'));
      assert.deepEqual(validateLiveRecord(book, 'MarketBook', validate), book);
      for (const bad of [{...book, cookie:'TEST_ONLY'},
          {...book, browser_mono_us:'9223372036854775808'},
          {...book, capture_evidence_tier:'NATIVE_ATOMIC'},
          {...book, selections:{...book.selections, DRAW:book.selections.HOME}}]) {
        assert.throws(() => validateLiveRecord(bad, 'MarketBook', validate), /E_LIVE_RECORD/);
      }
      assert.throws(() => validateLiveRecord(book,'MarketBook',()=>false), /E_LIVE_RECORD/);
      console.log('TS_LIVE_CONTRACT: 1 positive, 5 rejections');
    """
    root = Path(__file__).resolve().parents[2]
    for argv, data in [
        (["pnpm", "--dir", "extension", "exec", "tsc", "-p", "tsconfig.live.json"], None),
        (["node", "--input-type=module", "-e", code], json.dumps(synthetic_book)),
    ]:
        result = subprocess.run(  # noqa: S603 -- fixed isolated compiler/test commands
            argv,
            input=data,
            text=True,
            capture_output=True,
            cwd=root,
            timeout=60,
        )
        assert result.returncode == 0, result.stdout + result.stderr
