# P09 task contracts

Generated from docs/tasks/task-manifest.v6.3.6.json. Follow dependency order, including the recurring MIG0 tasks. Read docs/contracts/00–09 before executing.

## V636-P09-T01 — Assemble immutable review-pack candidate

Assemble the governed source, configured evidence closure and the verified descendant receipt without consulting historical hard-coded roots.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: QUALIFIED → SEALED.

### Dependencies

- `V636-P08-T03`

### Preconditions

- Dependency V636-P08-T03 is ACCEPTED

### Inputs

- /home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P01-T02.json
- /home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/bootstrap/authoring-repository-receipt.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/CANDIDATE_QUALIFICATION.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/DESCENDANT_REPOSITORY_QUALIFICATION.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-MIG0-T06.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P00-T05.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P02-T02.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P03-T02.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P03-T07.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P04-T04.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P05-T02.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P05-T04.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P05-T05.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P05-T09.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P06-T01.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P07-T01.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P07-T02.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P07-T03.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/bootstrap/authoring-repository-receipt-descendant-source-v2.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/environment/environment-aggregate.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/environment/inventory.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/full-repair/aggregate.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/full-repair/inventory.json
- /home/thenam176/betting-helper/hybrid-discovery-v6.3.6-authoring/.bootstrap/authoring-workspace-receipt.json
- /home/thenam176/betting-helper/plan-input/.receipts/hybrid-discovery-v6.3.6-plan-input.json
- authoring-fixtures/part-b-compiler-inputs.json
- authoring-fixtures/part-b-review-predecessor.json
- authoring-tests/test_part_b_review_inputs.py
- authoring-tools/prepare_part_b_review_inputs.py
- pack/docs/configs/full-verifier-controller.v2.json
- pack/docs/contracts/02-authority-graph.md
- pack/docs/receipts/declaration-complete.v1.json
- pack/docs/receipts/migration-receipt.v1.json
- pack/docs/receipts/source-provenance.v1.json
- plan-input/bootstrap/create_authoring_workspace.py
- plan-input/bootstrap/extract_plan.py
- plan-input/bootstrap/initialize_authoring_repository.py
- plan-input/bootstrap/test_bootstrap_tools.py
- plan-input/bootstrap/verify_extracted_plan.py
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/CURRENT_INPUTS.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/CAPTURE_V636_SUPPLEMENTAL_ENVIRONMENT.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/CAPTURE_V636_SUPPLEMENTAL_ENVIRONMENT.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/COMPILE_ALL_TESTS.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/COMPILE_ALL_TESTS.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/COMPILE_CRASH_HARNESS.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/COMPILE_CRASH_HARNESS.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/COMPILE_CRASH_HARNESS_AFTER_IMPLEMENTATION.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/COMPILE_CRASH_HARNESS_AFTER_IMPLEMENTATION.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/COMPILE_PRODUCTION.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/COMPILE_PRODUCTION.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/COMPILE_V636_P04_T03.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/COMPILE_V636_P04_T03.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/ISSUE_CURRENT_PHASE_PROOFS.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/ISSUE_CURRENT_PHASE_PROOFS.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/QUALIFY_INHERITED_BOOTSTRAP_PY.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/QUALIFY_INHERITED_BOOTSTRAP_PY.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/QUALIFY_INHERITED_BOOTSTRAP_TS.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/QUALIFY_INHERITED_BOOTSTRAP_TS.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/QUALIFY_INHERITED_CANONICAL_PY.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/QUALIFY_INHERITED_CANONICAL_PY.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/QUALIFY_SUCCESSOR_NORMATIVE_BINDINGS.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/QUALIFY_SUCCESSOR_NORMATIVE_BINDINGS.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/QUALIFY_SUCCESSOR_REGISTRY_SELF_CHECK.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/QUALIFY_SUCCESSOR_REGISTRY_SELF_CHECK.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_RELEASE_TOOLS.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_RELEASE_TOOLS.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_SECURITY_PY.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_SECURITY_PY.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_SECURITY_TS.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_SECURITY_TS.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_TS_V636_P04_T03.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_TS_V636_P04_T03.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P01_T01.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P01_T01.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P01_T02.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P01_T02.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P01_T03.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P01_T03.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P01_T04.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P01_T04.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P01_T05.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P01_T05.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P01_T06.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P01_T06.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P02_T01.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P02_T01.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P02_T02.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P02_T02.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P02_T03.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P02_T03.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P03_T01.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P03_T01.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P03_T02.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P03_T02.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P03_T03.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P03_T03.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P03_T04.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P03_T04.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P03_T05.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P03_T05.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P03_T06.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P03_T06.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P03_T07.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P03_T07.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P04_T01.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P04_T01.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P04_T02.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P04_T02.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P04_T04.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P04_T04.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T01.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T01.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T02.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T02.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T03.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T03.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T04.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T04.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T05.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T05.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T06.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T06.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T07.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T07.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T08.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T08.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P06_T01.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P06_T01.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P06_T02.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P06_T02.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P06_T03.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P06_T03.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/VALIDATE_CURRENT_DECLARATION.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/VALIDATE_CURRENT_DECLARATION.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/VALIDATE_CURRENT_DESCENDANT_MIGRATION.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/VALIDATE_CURRENT_DESCENDANT_MIGRATION.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/VERIFY_REVIEW_AUTHORITY_BOOTSTRAP.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/VERIFY_REVIEW_AUTHORITY_BOOTSTRAP.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/VERIFY_V636_P07_T01.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/VERIFY_V636_P07_T01.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/VERIFY_V636_P07_T02.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/VERIFY_V636_P07_T02.stderr
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/VERIFY_V636_P07_T03.stdout
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/VERIFY_V636_P07_T03.stderr

### Outputs

- `pack/authoring-source/bootstrap/create_authoring_workspace.py`
- `pack/authoring-source/bootstrap/extract_plan.py`
- `pack/authoring-source/bootstrap/initialize_authoring_repository.py`
- `pack/authoring-source/bootstrap/test_bootstrap_tools.py`
- `pack/authoring-source/bootstrap/verify_extracted_plan.py`
- `pack/docs/receipts/descendant-repository-qualification-receipt.json`
- `pack/evidence/CANDIDATE_QUALIFICATION.json`
- `pack/evidence/V636-MIG0-T06.json`
- `pack/evidence/V636-P00-T05.json`
- `pack/evidence/V636-P02-T02.json`
- `pack/evidence/V636-P03-T02.json`
- `pack/evidence/V636-P03-T07.json`
- `pack/evidence/V636-P04-T04.json`
- `pack/evidence/V636-P05-T02.json`
- `pack/evidence/V636-P05-T04.json`
- `pack/evidence/V636-P05-T05.json`
- `pack/evidence/V636-P05-T09.json`
- `pack/evidence/V636-P06-T01.json`
- `pack/evidence/V636-P07-T01.json`
- `pack/evidence/V636-P07-T02.json`
- `pack/evidence/V636-P07-T03.json`
- `pack/evidence/retained`
- `pack/evidence/retained-artifact-manifest.json`

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
- Verify the configured descendant receipt and exact inputs before exclusive destination creation.
- Copy the finite declared source and evidence closure into evidence/retained with its sibling retained-artifact-manifest/v1; preserve original bytes and locator boundaries.
- Reject conflicting locator boundaries, unsafe or aliased files, named-copy divergence and protected destination overlap; remove only an owned failed destination.
- Revalidate full-repair, supplemental, descendant and normative semantics through the copied SEALED context without original-root fallback.

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

Create Markdown and JSON self-review records binding governed content, the neutral descendant identity, candidate qualification, task manifest and command-result roots.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: QUALIFIED → SEALED.

### Dependencies

- `V636-P09-T02`

### Preconditions

- Dependency V636-P09-T02 is ACCEPTED

### Inputs

- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/CANDIDATE_QUALIFICATION.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P07-T01.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P07-T02.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P07-T03.json
- /home/thenam176/betting-helper/part-b-candidate/vendor/hybrid-discovery-v6.3.6/docs/configs/full-verifier-controller.v2.json
- pack/GOVERNED_CONTENT_ROOT.json
- pack/docs/configs/full-verifier-controller.v2.json
- pack/docs/receipts/descendant-repository-qualification-receipt.json
- pack/evidence/retained
- pack/evidence/retained-artifact-manifest.json
- runtime/tools/assemble_review_pack.py
- runtime/tools/build_self_review.py
- runtime/tools/retained_artifact_io.py

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

- /home/thenam176/betting-helper/part-b-candidate/vendor/hybrid-discovery-v6.3.6/docs/configs/full-verifier-controller.v2.json
- Verified immutable plan-input and the task-specific registered command inputs
- pack/GOVERNED_CONTENT_ROOT.json
- pack/SELF_REVIEW_REPORT.json
- pack/SELF_REVIEW_REPORT.md
- pack/docs/configs/full-verifier-controller.v2.json
- pack/docs/receipts/descendant-repository-qualification-receipt.json
- pack/docs/tasks/task-manifest.v6.3.6.json
- pack/evidence/retained
- pack/evidence/retained-artifact-manifest.json
- runtime/tools/assemble_review_pack.py
- runtime/tools/retained_artifact_io.py
- runtime/tools/seal_review_pack.py

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
