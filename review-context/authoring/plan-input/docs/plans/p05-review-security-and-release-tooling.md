# P05 task contracts

Generated from docs/tasks/task-manifest.v6.3.6.json. Follow dependency order, including the recurring MIG0 tasks. Read docs/contracts/00–09 before executing.

## V636-P05-T01 — Implement exact file and symbol resolver

Resolve every declared Python function/class/method and TypeScript named export without cosmetic wrappers or placeholder prose.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: MATERIALIZED → QUALIFIED.

### Dependencies

- `V636-P02-T03`

### Preconditions

- Dependency V636-P02-T03 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `runtime/tools/verify_task_symbols.py`
- `runtime/src/moj_discovery/symbol_inventory.py`
- `runtime/tests/exactness/test_task_symbols.py`
- `runtime/extension/test/exactness/task-symbols.test.ts`

### Exact files

- `runtime/tools/verify_task_symbols.py`
- `runtime/src/moj_discovery/symbol_inventory.py`
- `runtime/tests/exactness/test_task_symbols.py`
- `runtime/extension/test/exactness/task-symbols.test.ts`

### Exact symbols

- `runtime/tools/verify_task_symbols.py::main`
- `runtime/src/moj_discovery/symbol_inventory.py::resolve_python_symbol`
- `runtime/extension/test/exactness/task-symbols.test.ts#taskSymbolResolutionSuite`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `TEST_V636_P05_T01`

### Tests

- `runtime/tests/exactness/test_task_symbols.py`
- `runtime/extension/test/exactness/task-symbols.test.ts`

### Positive vectors

- `V636-P05-T01-POS-01`

### Negative vectors

- `V636-P05-T01-NEG-01`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- Unresolved symbols zero
- Ambiguous symbols zero
- Unexported TypeScript symbols zero

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P05-T01.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-P05-T02 — Implement proof-coverage matrix verifier

Map every promised control to finding, implementation symbol, exact test, vector IDs, command ID, evidence artifact, and release gate.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: MATERIALIZED → QUALIFIED.

### Dependencies

- `V636-P05-T01`

### Preconditions

- Dependency V636-P05-T01 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `runtime/src/moj_discovery/governance.py`
- `runtime/tests/bootstrap/test_schema_closure.py`
- `runtime/tests/coverage/test_proof_coverage_matrix.py`
- `runtime/tools/verify_proof_coverage.py`

### Exact files

- `pack/docs/registries/inherited-baseline-qualification.v1.json`
- `pack/docs/registries/proof-coverage-matrix.v1.json`
- `runtime/src/moj_discovery/governance.py`
- `runtime/tests/bootstrap/test_schema_closure.py`
- `runtime/tests/coverage/test_proof_coverage_matrix.py`
- `runtime/tools/verify_proof_coverage.py`

### Exact symbols

- `runtime/tools/verify_proof_coverage.py::verify_proof_coverage_matrix`
- `runtime/tests/coverage/test_proof_coverage_matrix.py::test_every_promised_control_has_mechanical_proof`

### Schema pointers

- `pack/docs/schemas/proof-coverage.schema.json#/$defs/ProofCoverageMatrix`

### Exact command IDs

- `TEST_V636_P05_T02`

### Tests

- `runtime/tests/coverage/test_proof_coverage_matrix.py`

### Positive vectors

- `V636-P05-T02-POS-01`

### Negative vectors

- `V636-P05-T02-NEG-01`
- `R633-06-REGRESSION`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- All exact commands pass
- All declared outputs are content-addressed
- No production authority is introduced
- At SEALED read the external attestation via explicit argv, require its schema and all bindings, independently recompute ZIP/sidecar, manifest, governed root and internal self-review bindings. Never read an in-pack P09 task receipt.
- SEALED with absent, stale, swapped attestation or unmounted seal input fails. CANDIDATE does not require future seal inputs.
- Preserve all named tests and negative cases; adapt inputs according to docs/contracts/09-inherited-baseline-qualification.md.
- validate_task_dependencies accepts the successor task manifest explicitly and validates its declared count/DAG; validate_canonical_registry accepts pinned historical registry data and explicit successor coverage bindings, never assumes active commands have v6.2 verification_commands shape.
- Reproduce R633-06 from REPAIR_MATRIX_V6_3_6.md and prove its correction; fail if the old counterexample is accepted.

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P05-T02.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-P05-T03 — Freeze cybersecurity command registry and attack matrix

Create exact argv-based commands for every required Chrome, CDP, dispatch, target, message, outbound-network, trust, credential, hashing, custody, sandbox, supply-chain, and build-exclusion attack.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: MATERIALIZED → QUALIFIED.

### Dependencies

- `V636-P05-T02`

### Preconditions

- Dependency V636-P05-T02 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `runtime/tools/verify_cybersecurity_registry.py`
- `runtime/tests/security/test_cybersecurity_command_registry.py`
- `runtime/tests/security/test_capability_manifest.py`
- `runtime/extension/test/security/cdp-reachability.test.ts`
- `runtime/extension/test/security/dynamic-dispatch.test.ts`
- `runtime/extension/test/security/target-escape.test.ts`
- `runtime/extension/test/security/message-smuggling.test.ts`
- `runtime/extension/test/security/outbound-network.test.ts`
- `runtime/tests/security/test_authorization_trust.py`
- `runtime/tests/security/test_replay_revocation.py`
- `runtime/tests/security/test_credential_evidence_boundary.py`
- `runtime/tests/security/test_canonical_hashing.py`
- `runtime/tests/security/test_no_archive_policy.py`
- `runtime/tests/security/test_bubblewrap_isolation.py`
- `runtime/tests/security/test_supply_chain_integrity.py`
- `runtime/extension/test/security/production-build-exclusion.test.ts`

### Exact files

- `runtime/tools/verify_cybersecurity_registry.py`
- `runtime/tests/security/test_cybersecurity_command_registry.py`
- `pack/docs/registries/cybersecurity-command-registry.v1.json`
- `pack/docs/contracts/06-cybersecurity-review.md`
- `runtime/tests/security/test_capability_manifest.py`
- `runtime/extension/test/security/cdp-reachability.test.ts`
- `runtime/extension/test/security/dynamic-dispatch.test.ts`
- `runtime/extension/test/security/target-escape.test.ts`
- `runtime/extension/test/security/message-smuggling.test.ts`
- `runtime/extension/test/security/outbound-network.test.ts`
- `runtime/tests/security/test_authorization_trust.py`
- `runtime/tests/security/test_replay_revocation.py`
- `runtime/tests/security/test_credential_evidence_boundary.py`
- `runtime/tests/security/test_canonical_hashing.py`
- `runtime/tests/security/test_no_archive_policy.py`
- `runtime/tests/security/test_bubblewrap_isolation.py`
- `runtime/tests/security/test_supply_chain_integrity.py`
- `runtime/extension/test/security/production-build-exclusion.test.ts`

### Exact symbols

- `runtime/tools/verify_cybersecurity_registry.py::verify_cybersecurity_command_registry`
- `runtime/tests/security/test_cybersecurity_command_registry.py::test_every_security_area_has_exact_executable_commands`
- `runtime/tests/security/test_capability_manifest.py::test_security_boundary`
- `runtime/extension/test/security/cdp-reachability.test.ts::testSecurityBoundary`
- `runtime/extension/test/security/dynamic-dispatch.test.ts::testSecurityBoundary`
- `runtime/extension/test/security/target-escape.test.ts::testSecurityBoundary`
- `runtime/extension/test/security/message-smuggling.test.ts::testSecurityBoundary`
- `runtime/extension/test/security/outbound-network.test.ts::testSecurityBoundary`
- `runtime/tests/security/test_authorization_trust.py::test_security_boundary`
- `runtime/tests/security/test_replay_revocation.py::test_security_boundary`
- `runtime/tests/security/test_credential_evidence_boundary.py::test_security_boundary`
- `runtime/tests/security/test_canonical_hashing.py::test_security_boundary`
- `runtime/tests/security/test_no_archive_policy.py::test_security_boundary`
- `runtime/tests/security/test_bubblewrap_isolation.py::test_security_boundary`
- `runtime/tests/security/test_supply_chain_integrity.py::test_security_boundary`
- `runtime/extension/test/security/production-build-exclusion.test.ts::testSecurityBoundary`

### Schema pointers

- `pack/docs/schemas/command-registry.schema.json#/$defs/CommandRegistry`

### Exact command IDs

- `TEST_V636_P05_T03`

### Tests

- `runtime/tests/security/test_cybersecurity_command_registry.py`
- `runtime/tests/security/test_capability_manifest.py`
- `runtime/extension/test/security/cdp-reachability.test.ts`
- `runtime/extension/test/security/dynamic-dispatch.test.ts`
- `runtime/extension/test/security/target-escape.test.ts`
- `runtime/extension/test/security/message-smuggling.test.ts`
- `runtime/extension/test/security/outbound-network.test.ts`
- `runtime/tests/security/test_authorization_trust.py`
- `runtime/tests/security/test_replay_revocation.py`
- `runtime/tests/security/test_credential_evidence_boundary.py`
- `runtime/tests/security/test_canonical_hashing.py`
- `runtime/tests/security/test_no_archive_policy.py`
- `runtime/tests/security/test_bubblewrap_isolation.py`
- `runtime/tests/security/test_supply_chain_integrity.py`
- `runtime/extension/test/security/production-build-exclusion.test.ts`

### Positive vectors

- `V636-P05-T03-POS-01`

### Negative vectors

- `V636-P05-T03-NEG-01`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- All exact commands pass
- All declared outputs are content-addressed
- No production authority is introduced

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P05-T03.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-P05-T04 — Implement host-issued review launch authorization

Define and verify role-bound, pack-bound, baseline-bound, workspace-bound, one-use, expiring review authorizations issued outside the authoring session.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: MATERIALIZED → QUALIFIED.

### Dependencies

- `V636-P05-T03`

### Preconditions

- Dependency V636-P05-T03 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `runtime/src/moj_discovery/review_authorization.py`
- `runtime/tools/issue_review_launch_authorization.py`
- `runtime/tests/review/test_review_launch_authorization.py`
- `runtime/tools/bootstrap_review_authority.py`
- `runtime/tests/review/test_review_authority_bootstrap.py`

### Exact files

- `runtime/src/moj_discovery/review_authorization.py`
- `runtime/tools/issue_review_launch_authorization.py`
- `runtime/tests/review/test_review_launch_authorization.py`
- `pack/docs/schemas/review-launch-authorization.schema.json`
- `pack/docs/registries/reviewer-role-registry.v1.json`
- `runtime/tools/bootstrap_review_authority.py`
- `runtime/tests/review/test_review_authority_bootstrap.py`
- `runtime/review-config/review-authority.v1.json`
- `pack/docs/configs/review-authority.v1.json`
- `pack/docs/security/review-trust-root.v1.json`

### Exact symbols

- `runtime/src/moj_discovery/review_authorization.py::verify_review_launch_authorization`
- `runtime/tools/issue_review_launch_authorization.py::main`
- `runtime/tests/review/test_review_launch_authorization.py::test_wrong_role_workspace_pack_or_expiry_is_rejected`
- `runtime/tools/bootstrap_review_authority.py::bootstrap_review_authority`
- `runtime/tests/review/test_review_authority_bootstrap.py::test_private_key_stays_outside_all_governed_roots`

### Schema pointers

- `pack/docs/schemas/review-launch-authorization.schema.json#/$defs/ReviewLaunchAuthorization`

### Exact command IDs

- `TEST_V636_P05_T04`
- `VERIFY_REVIEW_AUTHORITY_BOOTSTRAP`

### Tests

- `runtime/tests/review/test_review_launch_authorization.py`

### Positive vectors

- `V636-P05-T04-POS-01`

### Negative vectors

- `V636-P05-T04-NEG-01`
- `R633-05-REGRESSION`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- Launch authority private key is external to pack/runtime/authoring tree
- Authorization binds role, prompt, commands, workspace, inputs, outputs, freshness, and one-use serial
- Model-context freshness is explicitly human-attested, not cryptographically claimed
- Host review trust source and private-key custody path are explicit
- Private signing key is mechanically absent from authoring, runtime, pack, workspace, result, and log roots
- Launch lifetime is four hours and aggregation freshness is one hour
- Reproduce R633-05 from REPAIR_MATRIX_V6_3_6.md and prove its correction; fail if the old counterexample is accepted.

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P05-T04.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-P05-T05 — Implement isolated review workspace preparation and finalization

Prepare Bubblewrap/read-only review workspaces, exclude authoring and peer-review outputs, attest mount/process facts, and finalize only allowed outputs.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: MATERIALIZED → QUALIFIED.

### Dependencies

- `V636-P05-T04`

### Preconditions

- Dependency V636-P05-T04 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `runtime/tools/prepare_review_workspace.py`
- `runtime/tools/finalize_review.py`
- `runtime/tests/review/test_review_workspace_isolation.py`

### Exact files

- `runtime/tools/prepare_review_workspace.py`
- `runtime/tools/finalize_review.py`
- `runtime/tests/review/test_review_workspace_isolation.py`

### Exact symbols

- `runtime/tools/prepare_review_workspace.py::main`
- `runtime/tools/finalize_review.py::main`
- `runtime/tests/review/test_review_workspace_isolation.py::test_authoring_tree_and_peer_review_output_are_not_mounted`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `TEST_V636_P05_T05`

### Tests

- `runtime/tests/review/test_review_workspace_isolation.py`

### Positive vectors

- `V636-P05-T05-POS-01`

### Negative vectors

- `V636-P05-T05-NEG-01`
- `R634-DEPENDENCY-SETUP-REGRESSION`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- All exact commands pass
- All declared outputs are content-addressed
- No production authority is introduced
- Host preparation copies only node_environment.project_inputs into fresh role scratch, runs the exact install command offline with scripts disabled, verifies package/lock projection and mounts both dependency roots readonly. Five signed artifact mounts remain distinct from these two lock-derived dependency mounts.
- Reject the R634-DEPENDENCY-SETUP predecessor counterexample described in REPAIR_MATRIX_V6_3_6.md; preserve a runnable regression fixture.

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P05-T05.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-P05-T06 — Implement Review A mechanical runner

Run exact implementation-readiness commands and emit a closed evidence bundle for an independent reviewer.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: MATERIALIZED → QUALIFIED.

### Dependencies

- `V636-P05-T05`

### Preconditions

- Dependency V636-P05-T05 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `runtime/tools/run_review_a_checks.py`
- `runtime/tests/review/test_review_a_runner.py`

### Exact files

- `runtime/tools/run_review_a_checks.py`
- `runtime/tests/review/test_review_a_runner.py`
- `runtime/review-config/review-a.v1.json`
- `pack/docs/prompts/CODEX_IMPLEMENTATION_READINESS_REVIEW_PROMPT.md`

### Exact symbols

- `runtime/tools/run_review_a_checks.py::main`
- `runtime/tests/review/test_review_a_runner.py::test_review_a_runner_executes_only_registry_commands`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `TEST_V636_P05_T06`

### Tests

- `runtime/tests/review/test_review_a_runner.py`

### Positive vectors

- `V636-P05-T06-POS-01`

### Negative vectors

- `V636-P05-T06-NEG-01`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- All exact commands pass
- All declared outputs are content-addressed
- No production authority is introduced

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P05-T06.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-P05-T07 — Implement Review B cybersecurity runner

Run every exact cybersecurity command and emit a closed evidence bundle; missing command execution is HOLD.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: MATERIALIZED → QUALIFIED.

### Dependencies

- `V636-P05-T06`

### Preconditions

- Dependency V636-P05-T06 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `runtime/tools/run_review_b_checks.py`
- `runtime/tests/review/test_review_b_runner.py`

### Exact files

- `runtime/tools/run_review_b_checks.py`
- `runtime/tests/review/test_review_b_runner.py`
- `runtime/review-config/review-b.v1.json`
- `pack/docs/prompts/CODEX_CYBERSECURITY_REVIEW_PROMPT.md`

### Exact symbols

- `runtime/tools/run_review_b_checks.py::main`
- `runtime/tests/review/test_review_b_runner.py::test_review_b_runner_rejects_missing_or_skipped_security_area`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `TEST_V636_P05_T07`

### Tests

- `runtime/tests/review/test_review_b_runner.py`

### Positive vectors

- `V636-P05-T07-POS-01`

### Negative vectors

- `V636-P05-T07-NEG-01`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- All exact commands pass
- All declared outputs are content-addressed
- No production authority is introduced

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P05-T07.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-P05-T08 — Implement deterministic review aggregation and internal self-review tooling

Validate review results/receipts, enforce independence/freshness, aggregate verdicts, and build a non-authoritative internal self-review that never binds the future ZIP.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: MATERIALIZED → QUALIFIED.

### Dependencies

- `V636-P05-T07`

### Preconditions

- Dependency V636-P05-T07 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `runtime/tools/aggregate_reviews.py`
- `runtime/tools/build_self_review.py`
- `runtime/src/moj_discovery/review_aggregation.py`
- `runtime/tests/review/test_review_aggregation_and_self_review.py`

### Exact files

- `runtime/tools/aggregate_reviews.py`
- `runtime/tools/build_self_review.py`
- `runtime/src/moj_discovery/review_aggregation.py`
- `runtime/tests/review/test_review_aggregation_and_self_review.py`
- `pack/docs/schemas/review-execution-receipt.schema.json`
- `pack/docs/schemas/review-result.schema.json`
- `pack/docs/schemas/self-review-record.schema.json`

### Exact symbols

- `runtime/tools/aggregate_reviews.py::main`
- `runtime/tools/build_self_review.py::main`
- `runtime/src/moj_discovery/review_aggregation.py::aggregate_independent_reviews`
- `runtime/tests/review/test_review_aggregation_and_self_review.py::test_ready_yes_scope_no_is_valid_and_incomplete_security_holds`

### Schema pointers

- `pack/docs/schemas/review-execution-receipt.schema.json#/$defs/ReviewExecutionReceipt`
- `pack/docs/schemas/review-result.schema.json#/$defs/ReviewResult`
- `pack/docs/schemas/self-review-record.schema.json#/$defs/SelfReviewRecord`

### Exact command IDs

- `TEST_V636_P05_T08`

### Tests

- `runtime/tests/review/test_review_aggregation_and_self_review.py`

### Positive vectors

- `REVIEW-READY-YES-SCOPE0-NO`

### Negative vectors

- `REVIEW-READY-YES-REPO-NO`
- `REVIEW-READY-YES-E0-NO`
- `REVIEW-INCOMPLETE-CYBERSECURITY`
- `REVIEW-SAME-WORKSPACE`
- `REVIEW-SAME-LAUNCH-SERIAL`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- All exact commands pass
- All declared outputs are content-addressed
- No production authority is introduced

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P05-T08.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-P05-T09 — Implement and qualify all candidate, export, baseline and sealing tools

Implement and qualify all candidate, export, baseline and sealing tools

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: MATERIALIZED → QUALIFIED.

### Dependencies

- `V636-P05-T08`
- `V636-P03-T07`
- `V636-P04-T04`

### Preconditions

- Dependency V636-P05-T08 is ACCEPTED
- Dependency V636-P03-T07 is ACCEPTED
- Dependency V636-P04-T04 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `runtime/src/moj_discovery/pack_verifier.py`
- `runtime/tests/bootstrap/test_command_registry.py`
- `runtime/tests/bootstrap/test_repository_baseline.py`
- `runtime/tests/release/test_candidate_command_registry.py`
- `runtime/tests/release/test_candidate_qualification_receipt.py`
- `runtime/tests/release/test_full_proof_coverage.py`
- `runtime/tests/release/test_post_commit_baseline.py`
- `runtime/tests/release/test_zero_parent_export.py`
- `runtime/tests/release/test_zero_parent_repository.py`
- `runtime/tests/seal/test_deterministic_seal.py`
- `runtime/tests/seal/test_governed_content_root.py`
- `runtime/tests/seal/test_pack_assembly.py`
- `runtime/tests/seal/test_self_review_binding.py`
- `runtime/tools/assemble_review_pack.py`
- `runtime/tools/build_candidate_qualification_receipt.py`
- `runtime/tools/build_self_review.py`
- `runtime/tools/compute_governed_content_root.py`
- `runtime/tools/create_zero_parent_repository.py`
- `runtime/tools/export_zero_parent_candidate.py`
- `runtime/tools/qualify_zero_parent_baseline.py`
- `runtime/tools/run_command_registry.py`
- `runtime/tools/seal_review_pack.py`

### Exact files

- `pack/docs/registries/inherited-baseline-qualification.v1.json`
- `runtime/extension/test/bootstrap.test.ts`
- `runtime/extension/test/bootstrap/canonical-vectors.test.ts`
- `runtime/extension/test/bootstrap/clock-coherence-vectors.test.ts`
- `runtime/extension/test/schema-vendor.test.ts`
- `runtime/extension/test/security/capability-reachability.bootstrap.test.ts`
- `runtime/src/moj_discovery/governance.py`
- `runtime/src/moj_discovery/pack_verifier.py`
- `runtime/src/moj_discovery/vendor.py`
- `runtime/tests-red/test_canonical_hash_red.py`
- `runtime/tests/bootstrap/test_authorization_vectors.py`
- `runtime/tests/bootstrap/test_bootstrap.py`
- `runtime/tests/bootstrap/test_capability_reachability.py`
- `runtime/tests/bootstrap/test_clock_coherence.py`
- `runtime/tests/bootstrap/test_command_registry.py`
- `runtime/tests/bootstrap/test_custody_authority.py`
- `runtime/tests/bootstrap/test_ddl.py`
- `runtime/tests/bootstrap/test_durability_crash.py`
- `runtime/tests/bootstrap/test_governance_semantic_vectors.py`
- `runtime/tests/bootstrap/test_graph_partition.py`
- `runtime/tests/bootstrap/test_repository_baseline.py`
- `runtime/tests/bootstrap/test_review_semantics.py`
- `runtime/tests/bootstrap/test_schema_closure.py`
- `runtime/tests/bootstrap/test_schema_format_checker.py`
- `runtime/tests/bootstrap/test_schema_vendor.py`
- `runtime/tests/bootstrap/test_scope0_sandbox.py`
- `runtime/tests/bootstrap/test_scope0_semantics.py`
- `runtime/tests/bootstrap/test_semantic_denial.py`
- `runtime/tests/bootstrap/test_toolchains.py`
- `runtime/tests/release/test_candidate_command_registry.py`
- `runtime/tests/release/test_candidate_qualification_receipt.py`
- `runtime/tests/release/test_full_proof_coverage.py`
- `runtime/tests/release/test_post_commit_baseline.py`
- `runtime/tests/release/test_zero_parent_export.py`
- `runtime/tests/release/test_zero_parent_repository.py`
- `runtime/tests/seal/test_deterministic_seal.py`
- `runtime/tests/seal/test_governed_content_root.py`
- `runtime/tests/seal/test_pack_assembly.py`
- `runtime/tests/seal/test_self_review_binding.py`
- `runtime/tools/assemble_review_pack.py`
- `runtime/tools/build_candidate_qualification_receipt.py`
- `runtime/tools/build_self_review.py`
- `runtime/tools/compute_governed_content_root.py`
- `runtime/tools/create_zero_parent_repository.py`
- `runtime/tools/export_zero_parent_candidate.py`
- `runtime/tools/qualify_zero_parent_baseline.py`
- `runtime/tools/run_command_registry.py`
- `runtime/tools/seal_review_pack.py`
- `runtime/tools/sync_pack_assets.py`
- `runtime/tools/verify_normative_bundle.py`
- `runtime/tools/verify_toolchains.py`

### Exact symbols

- `runtime/tests/release/test_candidate_command_registry.py::test_candidate_mode_runs_every_required_command_once`
- `runtime/tests/release/test_candidate_qualification_receipt.py::test_receipt_rejects_skipped_command_live_evidence_or_production_authority`
- `runtime/tests/release/test_full_proof_coverage.py::test_every_proof_matrix_row_has_passing_evidence`
- `runtime/tests/release/test_post_commit_baseline.py::test_full_registry_replays_in_actual_committed_repository`
- `runtime/tests/release/test_zero_parent_export.py::test_export_contains_only_candidate_inventory_and_exact_modes`
- `runtime/tests/release/test_zero_parent_repository.py::test_delivered_repository_has_one_zero_parent_commit_and_no_remote`
- `runtime/tests/seal/test_deterministic_seal.py::test_independent_rebuild_is_byte_identical_and_external_attestation_matches`
- `runtime/tests/seal/test_governed_content_root.py::test_root_is_acyclic_and_exclusion_registry_is_closed`
- `runtime/tests/seal/test_pack_assembly.py::test_pack_inventory_has_no_external_review_or_final_seal_output`
- `runtime/tests/seal/test_self_review_binding.py::test_self_review_does_not_bind_future_manifest_zip_or_sidecar`
- `runtime/tools/assemble_review_pack.py::assemble_review_pack`
- `runtime/tools/build_candidate_qualification_receipt.py::main`
- `runtime/tools/build_self_review.py::main`
- `runtime/tools/compute_governed_content_root.py::compute_governed_content_root`
- `runtime/tools/create_zero_parent_repository.py::create_zero_parent_repository`
- `runtime/tools/export_zero_parent_candidate.py::export_zero_parent_candidate`
- `runtime/tools/qualify_zero_parent_baseline.py::qualify_zero_parent_baseline`
- `runtime/tools/run_command_registry.py::main`
- `runtime/tools/seal_review_pack.py::seal_review_pack`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `COMPILE_ALL_TESTS`
- `COMPILE_PRODUCTION`
- `TEST_RELEASE_TOOLS`
- `TEST_SECURITY_PY`
- `TEST_SECURITY_TS`
- `QUALIFY_INHERITED_BOOTSTRAP_PY`
- `QUALIFY_INHERITED_BOOTSTRAP_TS`
- `QUALIFY_INHERITED_CANONICAL_PY`
- `QUALIFY_SUCCESSOR_NORMATIVE_BINDINGS`
- `QUALIFY_SUCCESSOR_REGISTRY_SELF_CHECK`

### Tests

- `runtime/tests/release/test_candidate_command_registry.py`
- `runtime/tests/release/test_candidate_qualification_receipt.py`
- `runtime/tests/release/test_full_proof_coverage.py`
- `runtime/tests/release/test_post_commit_baseline.py`
- `runtime/tests/release/test_zero_parent_export.py`
- `runtime/tests/release/test_zero_parent_repository.py`
- `runtime/tests/seal/test_deterministic_seal.py`
- `runtime/tests/seal/test_governed_content_root.py`
- `runtime/tests/seal/test_pack_assembly.py`
- `runtime/tests/seal/test_self_review_binding.py`

### Positive vectors

- `V636-P05-T09-POS-01`

### Negative vectors

- `V636-P05-T09-NEG-01`
- `R633-02-REGRESSION`
- `R633-04-REGRESSION`
- `R634-PRODUCTION-BUILD-REGRESSION`
- `R634-EXPORT-INVENTORY-REGRESSION`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- All release tools and tests execute against disposable synthetic roots before P06
- Export and seal commands do not mutate qualified source or normative files
- Production authority remains NONE
- Preserve all named tests and negative cases; adapt inputs according to docs/contracts/09-inherited-baseline-qualification.md.
- Successor registry parser/runner accepts only explicit current schema, exact command order/argv/cwd/environment, approved output paths and expected exits; inherited legacy registry is test/provenance data and cannot become active execution authority.
- Keep historical archive/hash API semantics for immutable golden fixtures; successor repository receipt verification uses current command schema, current registry identity and explicit runtime/pack/evidence roots. Historical receipt acceptance cannot qualify a successor candidate.
- Reproduce R633-02 from REPAIR_MATRIX_V6_3_6.md and prove its correction; fail if the old counterexample is accepted.
- Reproduce R633-04 from REPAIR_MATRIX_V6_3_6.md and prove its correction; fail if the old counterexample is accepted.
- Production compiler runs before security exclusion test; dist inventory equals exactly emitted src outputs and contains no test/harness/tool files.
- Export rejects stale working-tree bytes even when authoring HEAD is unchanged; accepted uncommitted candidate source is copied only when bound by the P07 inventory.
- Reject the R634-PRODUCTION-BUILD predecessor counterexample described in REPAIR_MATRIX_V6_3_6.md; preserve a runnable regression fixture.
- Reject the R634-EXPORT-INVENTORY predecessor counterexample described in REPAIR_MATRIX_V6_3_6.md; preserve a runnable regression fixture.

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P05-T09.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.
