# MIG0 task contracts

Generated from docs/tasks/task-manifest.v6.3.6.json. Follow dependency order, including the recurring MIG0 tasks. Read docs/contracts/00–09 before executing.

## V636-MIG0-T01 — Verify v6.2 source baseline

Verify the immutable source runtime, receipts, locks, tree root, clean state, and absence of remotes before migration.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: DECLARED → MATERIALIZED.

### Dependencies

- `V636-P00-T05`

### Preconditions

- Dependency V636-P00-T05 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `authoring-tools/verify_v62_source.py`
- `authoring-tests/test_v62_source_identity.py`

### Exact files

- `authoring-tools/verify_v62_source.py`
- `authoring-tests/test_v62_source_identity.py`
- `pack/docs/registries/migration-source.v1.json`

### Exact symbols

- `authoring-tools/verify_v62_source.py::verify_v62_source`
- `authoring-tests/test_v62_source_identity.py::test_v62_source_matches_frozen_identity`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `VERIFY_V636_MIG0_T01`

### Tests

- `authoring-tests/test_v62_source_identity.py`

### Positive vectors

- `V636-MIG0-T01-POS-01`

### Negative vectors

- `V636-MIG0-T01-NEG-01`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- Source HEAD/tree/root match receipt
- Source working tree is clean
- No remote exists

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-MIG0-T01.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-MIG0-T02 — Populate the existing BOOT0 workspace from the pinned baseline

Copy exactly the pinned baseline runtime source inventory into the existing empty BOOT0 runtime root; do not recreate authoring Git or copy source Git/cache/evidence.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: DECLARED → MATERIALIZED.

### Dependencies

- `V636-MIG0-T01`

### Preconditions

- Dependency V636-MIG0-T01 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `authoring-tools/create_successor_workspace.py`
- `authoring-tests/test_successor_workspace.py`

### Exact files

- `authoring-tools/create_successor_workspace.py`
- `authoring-tests/test_successor_workspace.py`

### Exact symbols

- `authoring-tools/create_successor_workspace.py::create_successor_workspace`
- `authoring-tests/test_successor_workspace.py::test_successor_copy_excludes_git_cache_local_and_evidence`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `VERIFY_V636_MIG0_T02`

### Tests

- `authoring-tests/test_successor_workspace.py`

### Positive vectors

- `V636-MIG0-T02-POS-01`

### Negative vectors

- `V636-MIG0-T02-NEG-01`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- Destination roots are exact
- No source .git copied
- No live evidence copied
- Authoring repository has normal commit history

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-MIG0-T02.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-MIG0-T03 — Rebind versioned paths, IDs, and working roots

Apply the closed v6.2-to-v6.3.6 rebinding table to runtime and pack candidates.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: DECLARED → MATERIALIZED.

### Dependencies

- `V636-MIG0-T02`

### Preconditions

- Dependency V636-MIG0-T02 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `authoring-tests/test_version_rebinding.py`
- `authoring-tools/rebind_successor.py`
- `runtime/src/moj_discovery/governance.py`
- `runtime/src/moj_discovery/pack_verifier.py`
- `runtime/src/moj_discovery/vendor.py`
- `runtime/tests-red/test_canonical_hash_red.py`
- `runtime/tools/run_command_registry.py`
- `runtime/tools/sync_pack_assets.py`

### Exact files

- `authoring-tests/test_version_rebinding.py`
- `authoring-tools/rebind_successor.py`
- `pack/docs/contracts/02-successor-migration-rebinding.md`
- `pack/docs/registries/inherited-baseline-qualification.v1.json`
- `pack/docs/registries/version-rebinding.v1.json`
- `runtime/src/moj_discovery/governance.py`
- `runtime/src/moj_discovery/pack_verifier.py`
- `runtime/src/moj_discovery/vendor.py`
- `runtime/tests-red/test_canonical_hash_red.py`
- `runtime/tools/run_command_registry.py`
- `runtime/tools/sync_pack_assets.py`

### Exact symbols

- `authoring-tools/rebind_successor.py::apply_rebinding_plan`
- `authoring-tests/test_version_rebinding.py::test_every_rebinding_is_declared_and_idempotent`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `VERIFY_V636_MIG0_T03`

### Tests

- `authoring-tests/test_version_rebinding.py`

### Positive vectors

- `V636-MIG0-T03-POS-01`

### Negative vectors

- `V636-MIG0-T03-NEG-01`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- No undeclared textual replacement
- Rebinding is idempotent
- Historical provenance remains unchanged
- Only exact literal rebinding executes here. Record each before/after hash in the task evidence; semantic adaptations belong to their later declared tasks.

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-MIG0-T03.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-MIG0-T04 — Synchronize one normative bundle

Make pack/docs the sole normative source and copy exact governed schemas, vectors, registries, contracts, and protocol locks into runtime/vendor.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: DECLARED → MATERIALIZED.

### Dependencies

- `V636-MIG0-T03`

### Preconditions

- Dependency V636-MIG0-T03 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `authoring-tests/test_normative_sync.py`
- `authoring-tools/sync_normative_bundle.py`
- `runtime/extension/test/schema-vendor.test.ts`
- `runtime/schema-lock.json`
- `runtime/src/moj_discovery/vendor.py`
- `runtime/tests/bootstrap/test_schema_vendor.py`
- `runtime/tools/sync_pack_assets.py`
- `runtime/tools/verify_normative_bundle.py`
- `runtime/vendor/hybrid-discovery-v6.3.6/SCHEMA_SHA256.json`

### Exact files

- `authoring-tests/test_normative_sync.py`
- `authoring-tools/sync_normative_bundle.py`
- `pack/docs/registries/inherited-baseline-qualification.v1.json`
- `runtime/extension/test/schema-vendor.test.ts`
- `runtime/schema-lock.json`
- `runtime/src/moj_discovery/vendor.py`
- `runtime/tests/bootstrap/test_schema_vendor.py`
- `runtime/tools/sync_pack_assets.py`
- `runtime/tools/verify_normative_bundle.py`
- `runtime/vendor/hybrid-discovery-v6.3.6/SCHEMA_SHA256.json`

### Exact symbols

- `authoring-tools/sync_normative_bundle.py::synchronize_normative_bundle`
- `runtime/tools/sync_pack_assets.py::synchronize_normative_assets`
- `authoring-tests/test_normative_sync.py::test_runtime_vendor_bytes_equal_pack_normative_bytes`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `VERIFY_V636_MIG0_T04`

### Tests

- `authoring-tests/test_normative_sync.py`

### Positive vectors

- `V636-MIG0-T04-POS-01`

### Negative vectors

- `V636-MIG0-T04-NEG-01`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- Pack is sole normative source
- Runtime vendor bytes match exactly
- Schema lock records every vendored file
- Preserve all named tests and negative cases; adapt inputs according to docs/contracts/09-inherited-baseline-qualification.md.
- Preserve sync_pack_assets(pack, root, check=False) compatibility; use the explicit normative source map and separate MIG0-owned command-registry generation; checks never generate or silently remove undeclared inputs.
- verify_vendored_assets(root) compares active root registry against vendor/hybrid-discovery-v6.3.6/docs/registries/task-command-registry.v1.json; manifest file-set/hash checks remain exact.
- verify_normative_bundle(pack, runtime) uses explicit roots and current normative-source-map, fixtures and current manifest schema; validates mapped schema and CDP bytes without inferred parent roots or reading v6.2 SourceProvenance/current authority through historical schema. CLI requires --pack and --runtime.

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-MIG0-T04.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-MIG0-T05 — Regenerate task command registry and config bindings

Generate a successor-only exact command registry with no v6.2 working directories, command IDs, or placeholder arguments.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: DECLARED → MATERIALIZED.

### Dependencies

- `V636-MIG0-T04`

### Preconditions

- Dependency V636-MIG0-T04 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `authoring-tests/test_command_registry_generation.py`
- `authoring-tools/build_task_command_registry.py`
- `runtime/review-config/review-a.v1.json`
- `runtime/review-config/review-aggregation.v1.json`
- `runtime/review-config/review-authority.v1.json`
- `runtime/review-config/review-b.v1.json`
- `runtime/task-command-registry.json`

### Exact files

- `authoring-tests/test_command_registry_generation.py`
- `authoring-tools/build_task_command_registry.py`
- `runtime/review-config/review-a.v1.json`
- `runtime/review-config/review-aggregation.v1.json`
- `runtime/review-config/review-authority.v1.json`
- `runtime/review-config/review-b.v1.json`
- `runtime/task-command-registry.json`

### Exact symbols

- `authoring-tools/build_task_command_registry.py::build_task_command_registry`
- `authoring-tests/test_command_registry_generation.py::test_registry_has_exact_successor_paths_and_no_placeholders`

### Schema pointers

- `pack/docs/schemas/command-registry.schema.json#/$defs/CommandRegistry`

### Exact command IDs

- `VERIFY_V636_MIG0_T05`
- `MIG0_UV_SYNC`
- `MIG0_PNPM_INSTALL`

### Tests

- `authoring-tests/test_command_registry_generation.py`

### Positive vectors

- `V636-MIG0-T05-POS-01`

### Negative vectors

- `V636-MIG0-T05-NEG-01`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- Every task command ID resolves
- No command contains placeholder syntax
- No command references v6.2 runtime

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-MIG0-T05.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-MIG0-T06 — Scan legacy references and issue migration receipt

Prove all active paths, hashes, roots, registry IDs, and vendor destinations are rebound while historical references remain explicitly classified.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: DECLARED → MATERIALIZED.

### Dependencies

- `V636-MIG0-T05`

### Preconditions

- Dependency V636-MIG0-T05 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `authoring-tools/verify_successor_migration.py`
- `authoring-tests/test_successor_migration_receipt.py`
- `pack/docs/receipts/migration-receipt.v1.json`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-MIG0-T06.json`

### Exact files

- `authoring-tools/verify_successor_migration.py`
- `authoring-tests/test_successor_migration_receipt.py`
- `pack/docs/receipts/migration-receipt.v1.json`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-MIG0-T06.json`

### Exact symbols

- `authoring-tools/verify_successor_migration.py::verify_successor_migration`
- `authoring-tests/test_successor_migration_receipt.py::test_migration_receipt_accounts_for_every_active_legacy_reference`

### Schema pointers

- `pack/docs/schemas/migration-receipt.schema.json#/$defs/MigrationReceipt`
- `pack/docs/schemas/migration-receipt.schema.json#/$defs/FinalMigrationReceipt`

### Exact command IDs

- `VERIFY_V636_MIG0_T06`

### Tests

- `authoring-tests/test_successor_migration_receipt.py`

### Positive vectors

- `V636-MIG0-T06-POS-01`

### Negative vectors

- `V636-MIG0-T06-NEG-01`
- `R633-01-REGRESSION`
- `R634-MIGRATION-STAGE-REGRESSION`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- Active legacy references equal zero
- Historical references are registry-approved
- Migration receipt is content-addressed
- Implement both initial exact-hash and final literal/owner/lock-policy modes of verify_successor_migration; synthetic fixtures prove changed source requires its declared modifier receipt and undeclared legacy literals fail.
- Reproduce R633-01 from REPAIR_MATRIX_V6_3_6.md and prove its correction; fail if the old counterexample is accepted.
- Reject the R634-MIGRATION-STAGE predecessor counterexample described in REPAIR_MATRIX_V6_3_6.md; preserve a runnable regression fixture.

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-MIG0-T06.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-MIG0-T07 — Synchronize fully materialized normative assets and refresh native locks

Synchronize fully materialized normative assets and refresh native locks

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: DECLARED → MATERIALIZED.

### Dependencies

- `V636-P01-T06`

### Preconditions

- Dependency V636-P01-T06 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `runtime/review-config/review-a.v1.json`
- `runtime/review-config/review-aggregation.v1.json`
- `runtime/review-config/review-authority.v1.json`
- `runtime/review-config/review-b.v1.json`
- `runtime/task-command-registry.json`
- `runtime/tools/verify_toolchains.py`

### Exact files

- `pack/docs/registries/inherited-baseline-qualification.v1.json`
- `runtime/review-config/review-a.v1.json`
- `runtime/review-config/review-aggregation.v1.json`
- `runtime/review-config/review-authority.v1.json`
- `runtime/review-config/review-b.v1.json`
- `runtime/task-command-registry.json`
- `runtime/tools/verify_toolchains.py`

### Exact symbols

- `authoring-tools/sync_normative_bundle.py::synchronize_normative_bundle`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `V636_MIG0_T07_SYNC`
- `V636_MIG0_T07_CHECK`
- `MIG0_UV_LOCK`
- `MIG0_PNPM_LOCK`
- `MIG0_UV_SYNC_REFRESH`
- `MIG0_PNPM_INSTALL_REFRESH`
- `COMPILE_CRASH_HARNESS`
- `V636_MIG0_T07_BINDINGS`

### Tests

None; this task consumes previously created artifacts.

### Positive vectors

- `V636-MIG0-T07-POS-01`

### Negative vectors

- `V636-MIG0-T07-NEG-01`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- Every vendor byte matches the closed normative-source registry
- uv and pnpm regenerate locks without changing dependency versions
- No direct lockfile edit
- verify_dependency_policy(root) checks exact supplied successor configuration, pinned runtime/dependency versions and MIG0-produced native-lock hashes. No trust of arbitrary current config or self-observed lock hash.

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-MIG0-T07.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-MIG0-T08 — Finalize normative synchronization and lock source/config bindings

Finalize normative synchronization and lock source/config bindings

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: DECLARED → MATERIALIZED.

### Dependencies

- `V636-P03-T07`
- `V636-P04-T04`
- `V636-P05-T09`

### Preconditions

- Dependency V636-P03-T07 is ACCEPTED
- Dependency V636-P04-T04 is ACCEPTED
- Dependency V636-P05-T09 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/bootstrap/authoring-repository-receipt-descendant-source-v1.json`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/bootstrap/authoring-repository-receipt-descendant-source-v2.json`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/bootstrap/authoring-repository-receipt.json`
- `authoring-fixtures/part-b-compiler-inputs.json`
- `authoring-fixtures/part-b-one-ready-predecessor.json`
- `authoring-fixtures/part-b-review-launch-source.json`
- `authoring-fixtures/part-b-review-predecessor.json`
- `authoring-fixtures/part-b-security-surface-source.json`
- `authoring-tests/test_command_registry_generation.py`
- `authoring-tests/test_current_authoring_receipt.py`
- `authoring-tests/test_current_phase_inputs.py`
- `authoring-tests/test_declaration_gate.py`
- `authoring-tests/test_descendant_qualification_followup.py`
- `authoring-tests/test_full_verifier_controller_config.py`
- `authoring-tests/test_full_verifier_followup_amendment.py`
- `authoring-tests/test_one_ready_inputs.py`
- `authoring-tests/test_part_b_review_inputs.py`
- `authoring-tests/test_task_manifest_semantics.py`
- `authoring-tools/apply_descendant_qualification_followup.py`
- `authoring-tools/apply_full_verifier_followup.py`
- `authoring-tools/build_task_command_registry.py`
- `authoring-tools/issue_current_authoring_repository_receipt.py`
- `authoring-tools/issue_declaration_gate.py`
- `authoring-tools/prepare_one_ready_inputs.py`
- `authoring-tools/prepare_part_b_review_inputs.py`
- `authoring-tools/validate_current_phase_inputs.py`
- `pack/BOOTSTRAP.md`
- `pack/docs/configs/full-verifier-controller.v1.json`
- `pack/docs/configs/review-a.v2.json`
- `pack/docs/configs/review-aggregation.v2.json`
- `pack/docs/configs/review-b.v2.json`
- `pack/docs/contracts/07-command-and-config-lifecycle.md`
- `pack/docs/contracts/10-part-b-security-surface.md`
- `pack/docs/contracts/part-b-one-ready.v1.json`
- `pack/docs/receipts/migration-final-receipt.v1.json`
- `pack/docs/registries/artifact-ownership.v1.json`
- `pack/docs/registries/command-io.v1.json`
- `pack/docs/registries/delivery-map.v1.json`
- `pack/docs/registries/inherited-baseline-qualification.v1.json`
- `pack/docs/registries/normative-source-map.v1.json`
- `pack/docs/registries/proof-coverage-matrix.v1.json`
- `pack/docs/registries/review-command-registry.v1.json`
- `pack/docs/registries/schema-reference-registry.v1.json`
- `pack/docs/registries/task-command-registry.v1.json`
- `pack/docs/schemas/descendant-repository-qualification-receipt.schema.json`
- `pack/docs/schemas/external-seal-attestation.schema.json`
- `pack/docs/schemas/review-execution-receipt.schema.json`
- `pack/docs/schemas/review-launch-authorization.schema.json`
- `pack/docs/schemas/review-result.schema.json`
- `pack/docs/schemas/self-review-record.schema.json`
- `pack/docs/tasks/task-manifest.v6.3.6.json`
- `runtime/review-config/review-a.v1.json`
- `runtime/review-config/review-a.v2.json`
- `runtime/review-config/review-aggregation.v1.json`
- `runtime/review-config/review-aggregation.v2.json`
- `runtime/review-config/review-authority.v1.json`
- `runtime/review-config/review-b.v1.json`
- `runtime/review-config/review-b.v2.json`
- `runtime/task-command-registry.json`
- `runtime/vendor/hybrid-discovery-v6.3.6/docs/contracts/part-b-one-ready.v1.json`
- `runtime/vendor/hybrid-discovery-v6.3.6/docs/contracts/10-part-b-security-surface.md`
- `runtime/vendor/hybrid-discovery-v6.3.6/docs/configs/full-verifier-controller.v1.json`
- `runtime/vendor/hybrid-discovery-v6.3.6/docs/configs/full-verifier-controller.v2.json`
- `runtime/vendor/hybrid-discovery-v6.3.6/docs/configs/review-a.v2.json`
- `runtime/vendor/hybrid-discovery-v6.3.6/docs/configs/review-aggregation.v2.json`
- `runtime/vendor/hybrid-discovery-v6.3.6/docs/configs/review-b.v2.json`
- `runtime/vendor/hybrid-discovery-v6.3.6/docs/schemas/descendant-repository-qualification-receipt.schema.json`
- `runtime/vendor/hybrid-discovery-v6.3.6/docs/schemas/full-verifier-controller.schema.json`

### Exact files

- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/bootstrap/authoring-repository-receipt-descendant-source-v1.json`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/bootstrap/authoring-repository-receipt-descendant-source-v2.json`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/bootstrap/authoring-repository-receipt.json`
- `authoring-fixtures/part-b-one-ready-predecessor.json`
- `authoring-fixtures/part-b-review-launch-source.json`
- `authoring-fixtures/part-b-security-surface-source.json`
- `authoring-tests/test_command_registry_generation.py`
- `authoring-tests/test_current_authoring_receipt.py`
- `authoring-tests/test_current_phase_inputs.py`
- `authoring-tests/test_declaration_gate.py`
- `authoring-tests/test_descendant_qualification_followup.py`
- `authoring-tests/test_full_verifier_controller_config.py`
- `authoring-tests/test_full_verifier_followup_amendment.py`
- `authoring-tests/test_one_ready_inputs.py`
- `authoring-tests/test_task_manifest_semantics.py`
- `authoring-tools/apply_descendant_qualification_followup.py`
- `authoring-tools/apply_full_verifier_followup.py`
- `authoring-tools/build_task_command_registry.py`
- `authoring-tools/issue_current_authoring_repository_receipt.py`
- `authoring-tools/issue_declaration_gate.py`
- `authoring-tools/prepare_one_ready_inputs.py`
- `authoring-tools/validate_current_phase_inputs.py`
- `pack/BOOTSTRAP.md`
- `pack/docs/configs/full-verifier-controller.v1.json`
- `pack/docs/configs/review-a.v2.json`
- `pack/docs/configs/review-aggregation.v2.json`
- `pack/docs/configs/review-b.v2.json`
- `pack/docs/contracts/07-command-and-config-lifecycle.md`
- `pack/docs/contracts/10-part-b-security-surface.md`
- `pack/docs/contracts/part-b-one-ready.v1.json`
- `pack/docs/registries/artifact-ownership.v1.json`
- `pack/docs/registries/command-io.v1.json`
- `pack/docs/registries/delivery-map.v1.json`
- `pack/docs/registries/inherited-baseline-qualification.v1.json`
- `pack/docs/registries/normative-source-map.v1.json`
- `pack/docs/registries/proof-coverage-matrix.v1.json`
- `pack/docs/registries/review-command-registry.v1.json`
- `pack/docs/registries/schema-reference-registry.v1.json`
- `pack/docs/registries/task-command-registry.v1.json`
- `pack/docs/schemas/descendant-repository-qualification-receipt.schema.json`
- `pack/docs/schemas/external-seal-attestation.schema.json`
- `pack/docs/schemas/review-execution-receipt.schema.json`
- `pack/docs/schemas/review-launch-authorization.schema.json`
- `pack/docs/schemas/review-result.schema.json`
- `pack/docs/schemas/self-review-record.schema.json`
- `pack/docs/tasks/task-manifest.v6.3.6.json`
- `runtime/review-config/review-a.v1.json`
- `runtime/review-config/review-a.v2.json`
- `runtime/review-config/review-aggregation.v1.json`
- `runtime/review-config/review-aggregation.v2.json`
- `runtime/review-config/review-authority.v1.json`
- `runtime/review-config/review-b.v1.json`
- `runtime/review-config/review-b.v2.json`
- `runtime/task-command-registry.json`
- `runtime/vendor/hybrid-discovery-v6.3.6/docs/contracts/part-b-one-ready.v1.json`
- `runtime/vendor/hybrid-discovery-v6.3.6/docs/contracts/10-part-b-security-surface.md`
- `runtime/vendor/hybrid-discovery-v6.3.6/docs/configs/full-verifier-controller.v1.json`
- `runtime/vendor/hybrid-discovery-v6.3.6/docs/configs/full-verifier-controller.v2.json`
- `runtime/vendor/hybrid-discovery-v6.3.6/docs/configs/review-a.v2.json`
- `runtime/vendor/hybrid-discovery-v6.3.6/docs/configs/review-aggregation.v2.json`
- `runtime/vendor/hybrid-discovery-v6.3.6/docs/configs/review-b.v2.json`
- `runtime/vendor/hybrid-discovery-v6.3.6/docs/schemas/descendant-repository-qualification-receipt.schema.json`
- `runtime/vendor/hybrid-discovery-v6.3.6/docs/schemas/full-verifier-controller.schema.json`

### Exact symbols

- `authoring-tools/sync_normative_bundle.py::synchronize_normative_bundle`

### Schema pointers

- `pack/docs/schemas/migration-receipt.schema.json#/$defs/FinalMigrationReceipt`

### Exact command IDs

- `ISSUE_CURRENT_AUTHORING_REPOSITORY_RECEIPT`
- `V636_MIG0_T08_BINDINGS`
- `V636_MIG0_T08_CHECK`
- `V636_MIG0_T08_SYNC`
- `VERIFY_FINAL_MIGRATION`
- `VALIDATE_CURRENT_DECLARATION`
- `VALIDATE_CURRENT_DESCENDANT_MIGRATION`

### Tests

None; this task consumes previously created artifacts.

### Positive vectors

- `V636-MIG0-T08-POS-01`

### Negative vectors

- `V636-MIG0-T08-NEG-01`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- Normative source bytes are frozen
- All generated vendor, config and command bindings match
- Subsequent P06 tasks may implement only their owned validation sources; copied baseline, configuration, dependencies and normative files remain frozen

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-MIG0-T08.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.
