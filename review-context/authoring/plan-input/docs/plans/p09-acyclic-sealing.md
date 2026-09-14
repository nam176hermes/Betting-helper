# P09 task contracts

Generated from docs/tasks/task-manifest.v6.3.6.json. Follow dependency order, including the recurring MIG0 tasks. Read docs/contracts/00–09 before executing.

## V636-P09-T01 — Assemble immutable review-pack candidate

Assemble governed pack content, previous review imports, plans, registries, receipts, prompts, and source provenance after REPO0 receipt exists.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: QUALIFIED → SEALED.

### Dependencies

- `V636-P08-T03`

### Preconditions

- Dependency V636-P08-T03 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

None; this task consumes previously created artifacts.

### Exact files

- `runtime/tools/assemble_review_pack.py`
- `runtime/tests/seal/test_pack_assembly.py`

### Exact symbols

- `runtime/tools/assemble_review_pack.py::assemble_review_pack`
- `runtime/tests/seal/test_pack_assembly.py::test_pack_inventory_has_no_external_review_or_final_seal_output`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `VERIFY_V636_P09_T01`

### Tests

- `runtime/tests/seal/test_pack_assembly.py`

### Positive vectors

- `V636-P09-T01-POS-01`

### Negative vectors

- `V636-P09-T01-NEG-01`

### Steps

- Consume the already qualified tools; do not edit source, tests, configs, locks or normative bytes.
- Execute the registered operation against its exact roots.
- Write the external evidence record and stop.

### Acceptance criteria

- All exact commands pass
- All declared outputs are content-addressed
- No production authority is introduced

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P09-T01.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-P09-T02 — Compute acyclic governed-content root

Hash the normative governed file set while excluding root record, self-review, manifest, ZIP, sidecar, and external seal attestation according to a closed registry.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: QUALIFIED → SEALED.

### Dependencies

- `V636-P09-T01`

### Preconditions

- Dependency V636-P09-T01 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `pack/GOVERNED_CONTENT_ROOT.json`

### Exact files

- `runtime/tools/compute_governed_content_root.py`
- `runtime/tests/seal/test_governed_content_root.py`
- `pack/docs/registries/seal-exclusions.v1.json`
- `pack/GOVERNED_CONTENT_ROOT.json`

### Exact symbols

- `runtime/tools/compute_governed_content_root.py::compute_governed_content_root`
- `runtime/tests/seal/test_governed_content_root.py::test_root_is_acyclic_and_exclusion_registry_is_closed`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `VERIFY_V636_P09_T02`

### Tests

- `runtime/tests/seal/test_governed_content_root.py`

### Positive vectors

- `V636-P09-T02-POS-01`

### Negative vectors

- `V636-P09-T02-NEG-01`

### Steps

- Consume the already qualified tools; do not edit source, tests, configs, locks or normative bytes.
- Execute the registered operation against its exact roots.
- Write the external evidence record and stop.

### Acceptance criteria

- All exact commands pass
- All declared outputs are content-addressed
- No production authority is introduced

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P09-T02.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-P09-T03 — Generate internal self-review without ZIP or manifest self-reference

Create Markdown/JSON self-review binding only governed content, REPO0 receipt, candidate qualification, task manifest, and command result roots.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: QUALIFIED → SEALED.

### Dependencies

- `V636-P09-T02`

### Preconditions

- Dependency V636-P09-T02 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `pack/SELF_REVIEW_REPORT.md`
- `pack/SELF_REVIEW_REPORT.json`

### Exact files

- `runtime/tools/build_self_review.py`
- `runtime/tests/seal/test_self_review_binding.py`
- `pack/SELF_REVIEW_REPORT.md`
- `pack/SELF_REVIEW_REPORT.json`

### Exact symbols

- `runtime/tools/build_self_review.py::main`
- `runtime/tests/seal/test_self_review_binding.py::test_self_review_does_not_bind_future_manifest_zip_or_sidecar`

### Schema pointers

- `pack/docs/schemas/self-review-record.schema.json#/$defs/SelfReviewRecord`

### Exact command IDs

- `VERIFY_V636_P09_T03`

### Tests

- `runtime/tests/seal/test_self_review_binding.py`

### Positive vectors

- `V636-P09-T03-POS-01`

### Negative vectors

- `V636-P09-T03-NEG-01`

### Steps

- Consume the already qualified tools; do not edit source, tests, configs, locks or normative bytes.
- Execute the registered operation against its exact roots.
- Write the external evidence record and stop.

### Acceptance criteria

- All exact commands pass
- All declared outputs are content-addressed
- No production authority is introduced

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P09-T03.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-P09-T04 — Generate manifest, deterministic ZIP, sidecar, and external seal attestation

Generate a self-excluding manifest, deterministic archive, sidecar, and external attestation binding ZIP/manifest/governed root/self-review/REPO0 without placing the final ZIP hash inside the ZIP.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: QUALIFIED → SEALED.

### Dependencies

- `V636-P09-T03`

### Preconditions

- Dependency V636-P09-T03 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `pack/MANIFEST_SHA256.json`

### Exact files

- `runtime/tools/seal_review_pack.py`
- `runtime/tests/seal/test_deterministic_seal.py`
- `pack/MANIFEST_SHA256.json`
- `pack/docs/schemas/external-seal-attestation.schema.json`

### Exact symbols

- `runtime/tools/seal_review_pack.py::seal_review_pack`
- `runtime/tests/seal/test_deterministic_seal.py::test_independent_rebuild_is_byte_identical_and_external_attestation_matches`

### Schema pointers

- `pack/docs/schemas/external-seal-attestation.schema.json#/$defs/ExternalSealAttestation`

### Exact command IDs

- `VERIFY_V636_P09_T04`

### Tests

- `runtime/tests/seal/test_deterministic_seal.py`

### Positive vectors

- `V636-P09-T04-POS-01`

### Negative vectors

- `V636-P09-T04-NEG-01`

### Steps

- Consume the already qualified tools; do not edit source, tests, configs, locks or normative bytes.
- Execute the registered operation against its exact roots.
- Write the external evidence record and stop.

### Acceptance criteria

- All exact commands pass
- All declared outputs are content-addressed
- No production authority is introduced

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P09-T04.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.
