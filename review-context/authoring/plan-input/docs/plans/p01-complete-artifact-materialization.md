# P01 task contracts

Generated from docs/tasks/task-manifest.v6.3.6.json. Follow dependency order, including the recurring MIG0 tasks. Read docs/contracts/00–09 before executing.

## V636-P01-T01 — Materialize runtime toolchains and test configuration

Create exact runtime package manifests, lock policy, pytest discovery, TypeScript build/test/harness configs, and generated boundaries.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: DECLARED → MATERIALIZED.

### Dependencies

- `V636-MIG0-T06`

### Preconditions

- Dependency V636-MIG0-T06 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `runtime/extension/package.json`
- `runtime/extension/tsconfig.build.json`
- `runtime/extension/tsconfig.harness.json`
- `runtime/extension/tsconfig.json`
- `runtime/extension/tsconfig.test.json`
- `runtime/package.json`
- `runtime/pnpm-workspace.yaml`
- `runtime/pyproject.toml`
- `runtime/tests/bootstrap/test_toolchains.py`
- `runtime/tests/materialization/test_runtime_layout.py`
- `runtime/tools/verify_toolchains.py`

### Exact files

- `pack/docs/registries/inherited-baseline-qualification.v1.json`
- `runtime/extension/package.json`
- `runtime/extension/tsconfig.build.json`
- `runtime/extension/tsconfig.harness.json`
- `runtime/extension/tsconfig.json`
- `runtime/extension/tsconfig.test.json`
- `runtime/package.json`
- `runtime/pnpm-workspace.yaml`
- `runtime/pyproject.toml`
- `runtime/tests/bootstrap/test_toolchains.py`
- `runtime/tests/materialization/test_runtime_layout.py`
- `runtime/tools/verify_toolchains.py`

### Exact symbols

- `runtime/tests/materialization/test_runtime_layout.py::test_all_test_and_harness_directories_are_discovered`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `TEST_V636_P01_T01`

### Tests

- `runtime/tests/materialization/test_runtime_layout.py`

### Positive vectors

- `V636-P01-T01-POS-01`

### Negative vectors

- `V636-P01-T01-NEG-01`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- pytest testpaths include all tests
- tsconfig.harness includes test-harness and durability/security tests
- No release test relies only on bare pytest discovery
- Preserve all named tests and negative cases; adapt inputs according to docs/contracts/09-inherited-baseline-qualification.md.
- verify_dependency_policy(root) checks exact supplied successor configuration, pinned runtime/dependency versions and MIG0-produced native-lock hashes. No trust of arbitrary current config or self-observed lock hash.

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P01-T01.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-P01-T02 — Materialize every declared source and test stub

Create every planned runtime source, test, authoring tool, review tool, config, and harness entrypoint before exact reference validation.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: DECLARED → MATERIALIZED.

### Dependencies

- `V636-P01-T01`

### Preconditions

- Dependency V636-P01-T01 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P01-T02.json`
- `runtime/.contract-stub-registry.json`
- `runtime/extension/src/contracts/clock-vectors.ts`
- `runtime/extension/src/task-contracts.ts`
- `runtime/extension/test-harness/indexeddb-crash-child.ts`
- `runtime/extension/test/clock/clock-vectors.test.ts`
- `runtime/extension/test/exactness/task-symbols.test.ts`
- `runtime/extension/test/security/cdp-reachability.test.ts`
- `runtime/extension/test/security/dynamic-dispatch.test.ts`
- `runtime/extension/test/security/message-smuggling.test.ts`
- `runtime/extension/test/security/outbound-network.test.ts`
- `runtime/extension/test/security/production-build-exclusion.test.ts`
- `runtime/extension/test/security/target-escape.test.ts`
- `runtime/extension/tsconfig.harness.json`
- `runtime/src/moj_discovery/artifact_ownership.py`
- `runtime/src/moj_discovery/clock_precedence.py`
- `runtime/src/moj_discovery/clock_vectors.py`
- `runtime/src/moj_discovery/declaration_gate.py`
- `runtime/src/moj_discovery/durability_registry.py`
- `runtime/src/moj_discovery/durability_release.py`
- `runtime/src/moj_discovery/executable_gate.py`
- `runtime/src/moj_discovery/materialization_gate.py`
- `runtime/src/moj_discovery/review_aggregation.py`
- `runtime/src/moj_discovery/review_authorization.py`
- `runtime/src/moj_discovery/symbol_inventory.py`
- `runtime/src/moj_discovery/task_contracts.py`
- `runtime/tests/clock/test_clock_parity_and_mutation.py`
- `runtime/tests/clock/test_failure_precedence_registry.py`
- `runtime/tests/clock/test_python_clock_vectors.py`
- `runtime/tests/contracts/test_artifact_dependency_semantics.py`
- `runtime/tests/contracts/test_declaration_complete_gate.py`
- `runtime/tests/contracts/test_task_manifest_semantics.py`
- `runtime/tests/coverage/test_proof_coverage_matrix.py`
- `runtime/tests/durability/test_chrome_indexeddb_environment.py`
- `runtime/tests/durability/test_crash_registry.py`
- `runtime/tests/durability/test_destruction_and_release.py`
- `runtime/tests/durability/test_gap_generation_process_crash.py`
- `runtime/tests/durability/test_indexeddb_process_crash.py`
- `runtime/tests/durability/test_loopback_ack_process_crash.py`
- `runtime/tests/durability/test_sqlite_process_crash.py`
- `runtime/tests/exactness/test_task_symbols.py`
- `runtime/tests/materialization/test_declared_stubs.py`
- `runtime/tests/materialization/test_harness_entrypoints.py`
- `runtime/tests/materialization/test_materialization_gate.py`
- `runtime/tests/materialization/test_normative_artifacts.py`
- `runtime/tests/materialization/test_review_release_tools.py`
- `runtime/tests/materialization/test_runtime_layout.py`
- `runtime/tests/release/test_candidate_command_registry.py`
- `runtime/tests/release/test_candidate_qualification_receipt.py`
- `runtime/tests/release/test_executable_complete_gate.py`
- `runtime/tests/release/test_executable_references.py`
- `runtime/tests/release/test_full_proof_coverage.py`
- `runtime/tests/release/test_post_commit_baseline.py`
- `runtime/tests/release/test_verification_topology.py`
- `runtime/tests/release/test_zero_parent_export.py`
- `runtime/tests/release/test_zero_parent_repository.py`
- `runtime/tests/review/test_review_a_runner.py`
- `runtime/tests/review/test_review_aggregation_and_self_review.py`
- `runtime/tests/review/test_review_authority_bootstrap.py`
- `runtime/tests/review/test_review_b_runner.py`
- `runtime/tests/review/test_review_launch_authorization.py`
- `runtime/tests/review/test_review_workspace_isolation.py`
- `runtime/tests/seal/test_deterministic_seal.py`
- `runtime/tests/seal/test_governed_content_root.py`
- `runtime/tests/seal/test_pack_assembly.py`
- `runtime/tests/seal/test_self_review_binding.py`
- `runtime/tests/security/test_authorization_trust.py`
- `runtime/tests/security/test_bubblewrap_isolation.py`
- `runtime/tests/security/test_canonical_hashing.py`
- `runtime/tests/security/test_capability_manifest.py`
- `runtime/tests/security/test_credential_evidence_boundary.py`
- `runtime/tests/security/test_cybersecurity_command_registry.py`
- `runtime/tests/security/test_no_archive_policy.py`
- `runtime/tests/security/test_replay_revocation.py`
- `runtime/tests/security/test_supply_chain_integrity.py`
- `runtime/tools/aggregate_reviews.py`
- `runtime/tools/assemble_review_pack.py`
- `runtime/tools/bootstrap_review_authority.py`
- `runtime/tools/build_candidate_qualification_receipt.py`
- `runtime/tools/build_self_review.py`
- `runtime/tools/compute_governed_content_root.py`
- `runtime/tools/create_zero_parent_repository.py`
- `runtime/tools/destruction_crash_child.py`
- `runtime/tools/export_zero_parent_candidate.py`
- `runtime/tools/finalize_review.py`
- `runtime/tools/gap_coherence_crash_child.py`
- `runtime/tools/inspect_restart_state.py`
- `runtime/tools/issue_review_launch_authorization.py`
- `runtime/tools/loopback_ack_crash_child.py`
- `runtime/tools/materialize_declared_stubs.py`
- `runtime/tools/prepare_review_workspace.py`
- `runtime/tools/qualify_chrome_indexeddb.py`
- `runtime/tools/qualify_zero_parent_baseline.py`
- `runtime/tools/run_clock_vector_qualification.py`
- `runtime/tools/run_destruction_crash_matrix.py`
- `runtime/tools/run_gap_coherence_crash_matrix.py`
- `runtime/tools/run_indexeddb_crash_matrix.py`
- `runtime/tools/run_loopback_ack_crash_matrix.py`
- `runtime/tools/run_review_a_checks.py`
- `runtime/tools/run_review_b_checks.py`
- `runtime/tools/run_sqlite_crash_matrix.py`
- `runtime/tools/seal_review_pack.py`
- `runtime/tools/sqlite_crash_child.py`
- `runtime/tools/verify_cybersecurity_registry.py`
- `runtime/tools/verify_executable_references.py`
- `runtime/tools/verify_proof_coverage.py`
- `runtime/tools/verify_task_symbols.py`
- `runtime/tools/verify_test_discovery.py`

### Exact files

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P01-T02.json`
- `runtime/.contract-stub-registry.json`
- `runtime/extension/src/contracts/clock-vectors.ts`
- `runtime/extension/src/task-contracts.ts`
- `runtime/extension/test-harness/indexeddb-crash-child.ts`
- `runtime/extension/test/clock/clock-vectors.test.ts`
- `runtime/extension/test/exactness/task-symbols.test.ts`
- `runtime/extension/test/security/cdp-reachability.test.ts`
- `runtime/extension/test/security/dynamic-dispatch.test.ts`
- `runtime/extension/test/security/message-smuggling.test.ts`
- `runtime/extension/test/security/outbound-network.test.ts`
- `runtime/extension/test/security/production-build-exclusion.test.ts`
- `runtime/extension/test/security/target-escape.test.ts`
- `runtime/extension/tsconfig.harness.json`
- `runtime/src/moj_discovery/artifact_ownership.py`
- `runtime/src/moj_discovery/clock_precedence.py`
- `runtime/src/moj_discovery/clock_vectors.py`
- `runtime/src/moj_discovery/declaration_gate.py`
- `runtime/src/moj_discovery/durability_registry.py`
- `runtime/src/moj_discovery/durability_release.py`
- `runtime/src/moj_discovery/executable_gate.py`
- `runtime/src/moj_discovery/materialization_gate.py`
- `runtime/src/moj_discovery/review_aggregation.py`
- `runtime/src/moj_discovery/review_authorization.py`
- `runtime/src/moj_discovery/symbol_inventory.py`
- `runtime/src/moj_discovery/task_contracts.py`
- `runtime/tests/clock/test_clock_parity_and_mutation.py`
- `runtime/tests/clock/test_failure_precedence_registry.py`
- `runtime/tests/clock/test_python_clock_vectors.py`
- `runtime/tests/contracts/test_artifact_dependency_semantics.py`
- `runtime/tests/contracts/test_declaration_complete_gate.py`
- `runtime/tests/contracts/test_task_manifest_semantics.py`
- `runtime/tests/coverage/test_proof_coverage_matrix.py`
- `runtime/tests/durability/test_chrome_indexeddb_environment.py`
- `runtime/tests/durability/test_crash_registry.py`
- `runtime/tests/durability/test_destruction_and_release.py`
- `runtime/tests/durability/test_gap_generation_process_crash.py`
- `runtime/tests/durability/test_indexeddb_process_crash.py`
- `runtime/tests/durability/test_loopback_ack_process_crash.py`
- `runtime/tests/durability/test_sqlite_process_crash.py`
- `runtime/tests/exactness/test_task_symbols.py`
- `runtime/tests/materialization/test_declared_stubs.py`
- `runtime/tests/materialization/test_harness_entrypoints.py`
- `runtime/tests/materialization/test_materialization_gate.py`
- `runtime/tests/materialization/test_normative_artifacts.py`
- `runtime/tests/materialization/test_review_release_tools.py`
- `runtime/tests/materialization/test_runtime_layout.py`
- `runtime/tests/release/test_candidate_command_registry.py`
- `runtime/tests/release/test_candidate_qualification_receipt.py`
- `runtime/tests/release/test_executable_complete_gate.py`
- `runtime/tests/release/test_executable_references.py`
- `runtime/tests/release/test_full_proof_coverage.py`
- `runtime/tests/release/test_post_commit_baseline.py`
- `runtime/tests/release/test_verification_topology.py`
- `runtime/tests/release/test_zero_parent_export.py`
- `runtime/tests/release/test_zero_parent_repository.py`
- `runtime/tests/review/test_review_a_runner.py`
- `runtime/tests/review/test_review_aggregation_and_self_review.py`
- `runtime/tests/review/test_review_authority_bootstrap.py`
- `runtime/tests/review/test_review_b_runner.py`
- `runtime/tests/review/test_review_launch_authorization.py`
- `runtime/tests/review/test_review_workspace_isolation.py`
- `runtime/tests/seal/test_deterministic_seal.py`
- `runtime/tests/seal/test_governed_content_root.py`
- `runtime/tests/seal/test_pack_assembly.py`
- `runtime/tests/seal/test_self_review_binding.py`
- `runtime/tests/security/test_authorization_trust.py`
- `runtime/tests/security/test_bubblewrap_isolation.py`
- `runtime/tests/security/test_canonical_hashing.py`
- `runtime/tests/security/test_capability_manifest.py`
- `runtime/tests/security/test_credential_evidence_boundary.py`
- `runtime/tests/security/test_cybersecurity_command_registry.py`
- `runtime/tests/security/test_no_archive_policy.py`
- `runtime/tests/security/test_replay_revocation.py`
- `runtime/tests/security/test_supply_chain_integrity.py`
- `runtime/tools/aggregate_reviews.py`
- `runtime/tools/assemble_review_pack.py`
- `runtime/tools/bootstrap_review_authority.py`
- `runtime/tools/build_candidate_qualification_receipt.py`
- `runtime/tools/build_self_review.py`
- `runtime/tools/compute_governed_content_root.py`
- `runtime/tools/create_zero_parent_repository.py`
- `runtime/tools/destruction_crash_child.py`
- `runtime/tools/export_zero_parent_candidate.py`
- `runtime/tools/finalize_review.py`
- `runtime/tools/gap_coherence_crash_child.py`
- `runtime/tools/inspect_restart_state.py`
- `runtime/tools/issue_review_launch_authorization.py`
- `runtime/tools/loopback_ack_crash_child.py`
- `runtime/tools/materialize_declared_stubs.py`
- `runtime/tools/prepare_review_workspace.py`
- `runtime/tools/qualify_chrome_indexeddb.py`
- `runtime/tools/qualify_zero_parent_baseline.py`
- `runtime/tools/run_clock_vector_qualification.py`
- `runtime/tools/run_destruction_crash_matrix.py`
- `runtime/tools/run_gap_coherence_crash_matrix.py`
- `runtime/tools/run_indexeddb_crash_matrix.py`
- `runtime/tools/run_loopback_ack_crash_matrix.py`
- `runtime/tools/run_review_a_checks.py`
- `runtime/tools/run_review_b_checks.py`
- `runtime/tools/run_sqlite_crash_matrix.py`
- `runtime/tools/seal_review_pack.py`
- `runtime/tools/sqlite_crash_child.py`
- `runtime/tools/verify_cybersecurity_registry.py`
- `runtime/tools/verify_executable_references.py`
- `runtime/tools/verify_proof_coverage.py`
- `runtime/tools/verify_task_symbols.py`
- `runtime/tools/verify_test_discovery.py`

### Exact symbols

- `runtime/tools/materialize_declared_stubs.py::materialize_declared_stubs`
- `runtime/tests/materialization/test_declared_stubs.py::test_every_declared_path_exists_or_is_classified_external`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `TEST_V636_P01_T02`

### Tests

- `runtime/tests/materialization/test_declared_stubs.py`

### Positive vectors

- `V636-P01-T02-POS-01`

### Negative vectors

- `V636-P01-T02-NEG-01`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- Every planned internal path exists
- Every unimplemented symbol fails only with exact E_CONTRACT_NOT_IMPLEMENTED task code
- No missing import or config error

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P01-T02.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-P01-T03 — Materialize schemas, registries, vectors, and exact schema definitions

Create all planned normative schema files and resolvable JSON Pointer definitions before consumers are validated.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: DECLARED → MATERIALIZED.

### Dependencies

- `V636-P01-T02`

### Preconditions

- Dependency V636-P01-T02 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `runtime/tests/materialization/test_normative_artifacts.py`

### Exact files

- `runtime/tests/materialization/test_normative_artifacts.py`
- `pack/docs/registries/crash-harness-registry.v1.json`
- `pack/docs/registries/clock-failure-precedence.v1.json`
- `pack/docs/registries/proof-coverage-matrix.v1.json`
- `pack/docs/registries/cybersecurity-command-registry.v1.json`
- `pack/docs/registries/review-command-registry.v1.json`
- `pack/docs/registries/seal-exclusions.v1.json`
- `pack/docs/schemas/command-registry.schema.json`
- `pack/docs/schemas/proof-coverage.schema.json`
- `pack/docs/schemas/review-launch-authorization.schema.json`
- `pack/docs/schemas/review-execution-receipt.schema.json`
- `pack/docs/schemas/review-result.schema.json`
- `pack/docs/schemas/self-review-record.schema.json`
- `pack/docs/schemas/external-seal-attestation.schema.json`
- `pack/docs/schemas/migration-receipt.schema.json`
- `pack/docs/configs/review-authority.v1.json`
- `pack/docs/security/review-trust-root.v1.json`

### Exact symbols

- `runtime/tests/materialization/test_normative_artifacts.py::test_all_schema_pointers_registries_and_vectors_resolve`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `TEST_V636_P01_T03`

### Tests

- `runtime/tests/materialization/test_normative_artifacts.py`

### Positive vectors

- `V636-P01-T03-POS-01`

### Negative vectors

- `V636-P01-T03-NEG-01`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- Every schema reference resolves to an existing $defs member
- Every registry conforms to its schema
- No generic unresolved anchor

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P01-T03.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-P01-T04 — Materialize all crash and clock harness entrypoints

Create compilable test-only child entrypoints and runner stubs for every crash family and both clock evaluators.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: DECLARED → MATERIALIZED.

### Dependencies

- `V636-P01-T03`

### Preconditions

- Dependency V636-P01-T03 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `runtime/tests/materialization/test_harness_entrypoints.py`
- `runtime/extension/test-harness/indexeddb-crash-child.ts`
- `runtime/tools/loopback_ack_crash_child.py`
- `runtime/tools/sqlite_crash_child.py`
- `runtime/tools/gap_coherence_crash_child.py`
- `runtime/tools/destruction_crash_child.py`
- `runtime/src/moj_discovery/clock_vectors.py`
- `runtime/extension/src/contracts/clock-vectors.ts`

### Exact files

- `runtime/tests/materialization/test_harness_entrypoints.py`
- `runtime/extension/test-harness/indexeddb-crash-child.ts`
- `runtime/tools/loopback_ack_crash_child.py`
- `runtime/tools/sqlite_crash_child.py`
- `runtime/tools/gap_coherence_crash_child.py`
- `runtime/tools/destruction_crash_child.py`
- `runtime/src/moj_discovery/clock_vectors.py`
- `runtime/extension/src/contracts/clock-vectors.ts`

### Exact symbols

- `runtime/tests/materialization/test_harness_entrypoints.py::test_all_registered_harness_entrypoints_compile_and_emit_contract_not_implemented`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `TEST_V636_P01_T04`

### Tests

- `runtime/tests/materialization/test_harness_entrypoints.py`

### Positive vectors

- `V636-P01-T04-POS-01`

### Negative vectors

- `V636-P01-T04-NEG-01`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- All child entrypoints exist and compile
- No harness vector is left without an entrypoint
- Test-only privileged code is isolated from production build

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P01-T04.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-P01-T05 — Materialize review, cybersecurity, aggregation, export, and sealing tools

Create all review and release tooling before candidate qualification or zero-parent export.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: DECLARED → MATERIALIZED.

### Dependencies

- `V636-P01-T04`

### Preconditions

- Dependency V636-P01-T04 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `runtime/tests/materialization/test_review_release_tools.py`
- `runtime/tools/prepare_review_workspace.py`
- `runtime/tools/run_review_a_checks.py`
- `runtime/tools/run_review_b_checks.py`
- `runtime/tools/finalize_review.py`
- `runtime/tools/aggregate_reviews.py`
- `runtime/tools/build_self_review.py`
- `runtime/tools/verify_executable_references.py`
- `runtime/tools/verify_proof_coverage.py`
- `runtime/tools/export_zero_parent_candidate.py`
- `runtime/tools/seal_review_pack.py`

### Exact files

- `runtime/tests/materialization/test_review_release_tools.py`
- `runtime/tools/prepare_review_workspace.py`
- `runtime/tools/run_review_a_checks.py`
- `runtime/tools/run_review_b_checks.py`
- `runtime/tools/finalize_review.py`
- `runtime/tools/aggregate_reviews.py`
- `runtime/tools/build_self_review.py`
- `runtime/tools/verify_executable_references.py`
- `runtime/tools/verify_proof_coverage.py`
- `runtime/tools/export_zero_parent_candidate.py`
- `runtime/tools/seal_review_pack.py`

### Exact symbols

- `runtime/tests/materialization/test_review_release_tools.py::test_all_review_release_tools_exist_before_candidate_qualification`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `TEST_V636_P01_T05`

### Tests

- `runtime/tests/materialization/test_review_release_tools.py`

### Positive vectors

- `V636-P01-T05-POS-01`

### Negative vectors

- `V636-P01-T05-NEG-01`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- All release/review tools exist before P06
- Review configs reference executable tools, not prompt files
- Aggregator exists before reviews

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P01-T05.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-P01-T06 — Issue MATERIALIZATION_COMPLETE gate

Prove all declared internal artifacts are present, compilable, schema-resolvable, and owned while allowing intentional contract stubs.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: DECLARED → MATERIALIZED.

### Dependencies

- `V636-P01-T05`

### Preconditions

- Dependency V636-P01-T05 is ACCEPTED

### Inputs

- .bootstrap/authoring-workspace-receipt.json
- Verified immutable plan-input and the task-specific registered command inputs
- plan-input/MANIFEST_SHA256.json
- plan-input/docs/registries/artifact-ownership.v1.json
- plan-input/docs/schemas/artifact-ownership.schema.json
- plan-input/docs/tasks/task-manifest.v6.3.6.json

### Outputs

- `runtime/src/moj_discovery/materialization_gate.py`
- `runtime/tests/materialization/test_materialization_gate.py`

### Exact files

- `runtime/src/moj_discovery/materialization_gate.py`
- `runtime/tests/materialization/test_materialization_gate.py`

### Exact symbols

- `runtime/src/moj_discovery/materialization_gate.py::validate_materialization_complete`
- `runtime/tests/materialization/test_materialization_gate.py::test_materialization_gate_rejects_missing_or_unowned_artifact`

### Schema pointers

- `pack/docs/schemas/artifact-ownership.schema.json#/$defs/ArtifactOwnershipRegistry`

### Exact command IDs

- `TYPECHECK_MATERIALIZED_TS`
- `TEST_V636_P01_T06`

### Tests

- `runtime/tests/materialization/test_materialization_gate.py`

### Positive vectors

- `V636-P01-T06-POS-01`

### Negative vectors

- `V636-P01-T06-NEG-01`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- All internal artifacts are materialized
- External review/seal outputs are classified and not required yet
- Gate receipt records exact artifact root

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P01-T06.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.
