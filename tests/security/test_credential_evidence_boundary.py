import copy
import json
from pathlib import Path

from moj_discovery.universal_denial import (
    DenialReceiptIdentity,
    UniversalDenialEngine,
    run_synthetic_side_effect_boundary,
)

ROOT = Path(__file__).parents[2]
E0_SCHEMA = "urn:hybrid-discovery:v6.2:e0-evidence:v1"
IDENTITY = DenialReceiptIdentity(
    receipt_id="denial-receipt:" + "9" * 64,
    attempt_id="99999999-9999-4999-8999-999999999999",
    input_class="RAW_OBSERVATION",
)


def test_security_boundary() -> None:
    attack_vectors = {
        "allow": "SEC_CREDENTIAL_EVIDENCE-ALLOW",
        "deny": "SEC_CREDENTIAL_EVIDENCE-DENY",
        "mutate": "SEC_CREDENTIAL_EVIDENCE-MUTATE",
    }
    vectors = json.loads(
        (ROOT / "vendor/hybrid-discovery-v6.3.6/vectors/e0-evidence-v1.json").read_text()
    )
    valid = next(
        item["record"]
        for item in vectors["valid_records"]
        if item["case_id"] == "E0-VALID-S01-NOT-OBSERVED"
    )
    engine = UniversalDenialEngine()
    allowed_effects: list[str] = []
    allowed = run_synthetic_side_effect_boundary(
        engine, json.dumps(valid, separators=(",", ":")).encode(), E0_SCHEMA, allowed_effects.append
    )
    assert allowed.disposition == "ACCEPTED", attack_vectors["allow"]
    assert allowed_effects

    for field, value in (
        ("cookie", "TEST_ONLY_SESSION_SECRET"),
        ("token", "Bearer TEST_ONLY_TOKEN"),
        ("raw_response", "TEST_ONLY_RAW_RESPONSE"),
    ):
        record = copy.deepcopy(valid)
        record["facts"][field] = value
        effects: list[str] = []
        outcome = run_synthetic_side_effect_boundary(
            engine,
            json.dumps(record, separators=(",", ":")).encode(),
            E0_SCHEMA,
            effects.append,
            receipt_identity=IDENTITY,
        )
        assert outcome.disposition != "ACCEPTED", attack_vectors["deny"]
        assert effects == []
        assert outcome.receipt is not None
        assert outcome.receipt["candidate_bytes_hashed"] is False

    mutated = copy.deepcopy(valid)
    mutated["facts"]["authorization"] = "Basic TEST_ONLY"
    mutation_effects: list[str] = []
    mutation = run_synthetic_side_effect_boundary(
        engine,
        json.dumps(mutated, separators=(",", ":")).encode(),
        E0_SCHEMA,
        mutation_effects.append,
        receipt_identity=IDENTITY,
    )
    assert mutation.disposition != "ACCEPTED", attack_vectors["mutate"]
    assert mutation_effects == []
