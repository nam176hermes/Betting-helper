PRAGMA page_size = 4096;
PRAGMA journal_mode = DELETE;
PRAGMA synchronous = FULL;
PRAGMA foreign_keys = ON;
PRAGMA trusted_schema = OFF;
PRAGMA temp_store = MEMORY;
PRAGMA auto_vacuum = NONE;
PRAGMA busy_timeout = 5000;
PRAGMA max_page_count = 32768;
PRAGMA user_version = 1;

-- Bootstrap DDL only. Runtime code must prohibit DELETE, VACUUM, ATTACH,
-- extension loading, and schema mutation. Normal ingest transaction order is:
-- RawCommit -> Application -> DerivedRevision -> ReducerCursor -> AckOutbox.
-- GAP transaction order is: GapRecord -> ShockObservation -> immutable
-- CoherenceTransition(epoch close) -> CoherenceController(SHOCKED_CLOSED) ->
-- GapEpochBinding -> predecessor generation close -> GenerationTransition ->
-- exact successor generation open. All eight statements share one transaction;
-- they create no application, revision, reducer-cursor advance, or ACK.
-- Whole-run store destruction is external and human-invoked only. It may start
-- only after the exact accepted-export GateReceipt consumption has committed
-- and the persisted external RunDestructionIntent bytes match the consumption's
-- precommitted intent ID/content hash/inventory/created-at bindings. Only then
-- may the caller move the closed run to DESTRUCTION_PENDING; row DELETE remains
-- forbidden inside this database.

CREATE TABLE run_meta (
    run_id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    run_status TEXT NOT NULL CHECK (run_status IN ('OPEN', 'CLOSED', 'DESTRUCTION_PENDING')),
    authorization_id TEXT NOT NULL,
    pack_hash TEXT NOT NULL CHECK (length(pack_hash) = 64 AND pack_hash NOT GLOB '*[^0-9a-f]*'),
    build_hash TEXT NOT NULL CHECK (length(build_hash) = 64 AND build_hash NOT GLOB '*[^0-9a-f]*'),
    created_at_us INTEGER NOT NULL CHECK (created_at_us >= 0),
    closed_at_us INTEGER CHECK (closed_at_us IS NULL OR closed_at_us >= created_at_us),
    CHECK ((run_status = 'OPEN' AND closed_at_us IS NULL) OR (run_status <> 'OPEN' AND closed_at_us IS NOT NULL))
) STRICT;

CREATE TABLE authorization_consumptions (
    consumption_id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES run_meta(run_id),
    receipt_record_type TEXT NOT NULL CHECK (receipt_record_type IN ('GateReceipt', 'DiscoveryRunAuthorization', 'BodyClassApproval', 'ProviderCallAuthorization')),
    receipt_schema_version TEXT NOT NULL CHECK (receipt_schema_version IN ('gate-receipt/v1', 'discovery-run-authorization/v1', 'body-class-approval/v1', 'provider-call-authorization/v1')),
    receipt_id TEXT NOT NULL UNIQUE,
    destruction_intent_id TEXT,
    precommitted_destruction_intent_content_hash TEXT CHECK (precommitted_destruction_intent_content_hash IS NULL OR (length(precommitted_destruction_intent_content_hash) = 64 AND precommitted_destruction_intent_content_hash NOT GLOB '*[^0-9a-f]*')),
    staged_pre_delete_inventory_hash TEXT CHECK (staged_pre_delete_inventory_hash IS NULL OR (length(staged_pre_delete_inventory_hash) = 64 AND staged_pre_delete_inventory_hash NOT GLOB '*[^0-9a-f]*')),
    staged_intent_created_at TEXT,
    intent_authorization_id TEXT,
    intent_consumption_id TEXT,
    intent_run_id TEXT REFERENCES run_meta(run_id),
    receipt_scope TEXT NOT NULL,
    gate_kind TEXT,
    gate_result TEXT,
    receipt_bound_run_id TEXT REFERENCES run_meta(run_id),
    accepted_sanitized_export_manifest_hash TEXT CHECK (accepted_sanitized_export_manifest_hash IS NULL OR (length(accepted_sanitized_export_manifest_hash) = 64 AND accepted_sanitized_export_manifest_hash NOT GLOB '*[^0-9a-f]*')),
    receipt_bound_sanitized_export_manifest_hash TEXT CHECK (receipt_bound_sanitized_export_manifest_hash IS NULL OR (length(receipt_bound_sanitized_export_manifest_hash) = 64 AND receipt_bound_sanitized_export_manifest_hash NOT GLOB '*[^0-9a-f]*')),
    issuer TEXT NOT NULL CHECK (length(issuer) BETWEEN 8 AND 128),
    issuer_key_id TEXT NOT NULL CHECK (issuer_key_id GLOB 'key:ed25519:*' AND length(issuer_key_id) = 76),
    audience TEXT NOT NULL CHECK (length(audience) BETWEEN 8 AND 128),
    scope_binding_hash TEXT NOT NULL CHECK (length(scope_binding_hash) = 64 AND scope_binding_hash NOT GLOB '*[^0-9a-f]*'),
    serial TEXT NOT NULL,
    nonce TEXT NOT NULL,
    receipt_content_hash TEXT NOT NULL UNIQUE CHECK (length(receipt_content_hash) = 64 AND receipt_content_hash NOT GLOB '*[^0-9a-f]*'),
    intent_receipt_content_hash TEXT CHECK (intent_receipt_content_hash IS NULL OR (length(intent_receipt_content_hash) = 64 AND intent_receipt_content_hash NOT GLOB '*[^0-9a-f]*')),
    signature_algorithm TEXT NOT NULL CHECK (signature_algorithm = 'Ed25519'),
    signature TEXT NOT NULL CHECK (length(signature) = 86 AND signature NOT GLOB '*[^A-Za-z0-9_-]*'),
    receipt_verification_state TEXT NOT NULL CHECK (receipt_verification_state = 'CANONICAL_BYTES_CONTENT_HASH_AND_ED25519_SIGNATURE_VERIFIED'),
    one_use INTEGER NOT NULL CHECK (one_use = 1),
    declared_use_semantics TEXT CHECK (declared_use_semantics IS NULL OR declared_use_semantics = 'SINGLE_USE'),
    consumed_before TEXT NOT NULL CHECK (consumed_before IN ('ATOMIC_LEDGER_COMMIT_BEFORE_GATE_USE', 'ATOMIC_LEDGER_COMMIT_BEFORE_DEBUGGER_ATTACH', 'ATOMIC_LEDGER_COMMIT_BEFORE_BODY_TICKET_CREATION', 'ATOMIC_LEDGER_COMMIT_BEFORE_PROVIDER_IO', 'ATOMIC_LEDGER_COMMIT_BEFORE_WHOLE_RUN_DESTRUCTION')),
    consumption_commit_state TEXT NOT NULL CHECK (consumption_commit_state IN ('COMMITTED_BEFORE_AUTHORIZED_ACTION', 'COMMITTED_BEFORE_WHOLE_RUN_DESTRUCTION')),
    explicit_human_invocation INTEGER CHECK (explicit_human_invocation IS NULL OR explicit_human_invocation = 1),
    verifier_clock_domain_id TEXT NOT NULL,
    verifier_boot_id TEXT NOT NULL,
    verifier_clock_unit TEXT NOT NULL CHECK (verifier_clock_unit = 'MICROSECOND'),
    verifier_monotonic_value INTEGER NOT NULL CHECK (verifier_monotonic_value >= 0),
    verifier_clock_resolution_us INTEGER NOT NULL CHECK (verifier_clock_resolution_us >= 1),
    consumed_at_us INTEGER NOT NULL CHECK (consumed_at_us >= 0),
    UNIQUE (issuer, issuer_key_id, audience, serial),
    UNIQUE (issuer, issuer_key_id, audience, scope_binding_hash, nonce),
    CHECK ((
      (receipt_record_type = 'DiscoveryRunAuthorization'
       AND receipt_schema_version = 'discovery-run-authorization/v1'
       AND receipt_scope = 'AUTHENTICATED_PASSIVE_DISCOVERY'
       AND gate_kind IS NULL AND gate_result IS NULL AND declared_use_semantics IS NULL
       AND destruction_intent_id IS NULL AND precommitted_destruction_intent_content_hash IS NULL
       AND staged_pre_delete_inventory_hash IS NULL AND staged_intent_created_at IS NULL
       AND intent_authorization_id IS NULL
       AND intent_consumption_id IS NULL AND intent_run_id IS NULL
       AND receipt_bound_run_id IS NULL AND accepted_sanitized_export_manifest_hash IS NULL
       AND receipt_bound_sanitized_export_manifest_hash IS NULL AND intent_receipt_content_hash IS NULL
       AND consumed_before = 'ATOMIC_LEDGER_COMMIT_BEFORE_DEBUGGER_ATTACH'
       AND consumption_commit_state = 'COMMITTED_BEFORE_AUTHORIZED_ACTION'
       AND explicit_human_invocation IS NULL AND run_id IS NOT NULL)
      OR
      (receipt_record_type = 'BodyClassApproval'
       AND receipt_schema_version = 'body-class-approval/v1'
       AND receipt_scope = 'TEST_ONLY_APPROVED_INBOUND_BODY_CLASS'
       AND gate_kind IS NULL AND gate_result IS NULL AND declared_use_semantics IS NULL
       AND destruction_intent_id IS NULL AND precommitted_destruction_intent_content_hash IS NULL
       AND staged_pre_delete_inventory_hash IS NULL AND staged_intent_created_at IS NULL
       AND intent_authorization_id IS NULL
       AND intent_consumption_id IS NULL AND intent_run_id IS NULL
       AND receipt_bound_run_id IS NULL AND accepted_sanitized_export_manifest_hash IS NULL
       AND receipt_bound_sanitized_export_manifest_hash IS NULL AND intent_receipt_content_hash IS NULL
       AND consumed_before = 'ATOMIC_LEDGER_COMMIT_BEFORE_BODY_TICKET_CREATION'
       AND consumption_commit_state = 'COMMITTED_BEFORE_AUTHORIZED_ACTION'
       AND explicit_human_invocation IS NULL AND run_id IS NOT NULL)
      OR
      (receipt_record_type = 'ProviderCallAuthorization'
       AND receipt_schema_version = 'provider-call-authorization/v1'
       AND receipt_scope = 'ONE_PROVIDER_FEASIBILITY_GET'
       AND gate_kind IS NULL AND gate_result IS NULL AND declared_use_semantics IS NULL
       AND destruction_intent_id IS NULL AND precommitted_destruction_intent_content_hash IS NULL
       AND staged_pre_delete_inventory_hash IS NULL AND staged_intent_created_at IS NULL
       AND intent_authorization_id IS NULL
       AND intent_consumption_id IS NULL AND intent_run_id IS NULL
       AND receipt_bound_run_id IS NULL AND accepted_sanitized_export_manifest_hash IS NULL
       AND receipt_bound_sanitized_export_manifest_hash IS NULL AND intent_receipt_content_hash IS NULL
       AND consumed_before = 'ATOMIC_LEDGER_COMMIT_BEFORE_PROVIDER_IO'
       AND consumption_commit_state = 'COMMITTED_BEFORE_AUTHORIZED_ACTION'
       AND explicit_human_invocation IS NULL AND run_id IS NOT NULL)
      OR
      (receipt_record_type = 'GateReceipt'
       AND receipt_schema_version = 'gate-receipt/v1'
       AND gate_kind IN ('REPO0_BASELINE_ACCEPTED', 'R0_REPAIR_ACCEPTED', 'F0A_FOUNDATION_ACCEPTED', 'DISCOVERY_SECURITY_ACCEPTED', 'OPERATOR_DISCOVERY_ACCEPTED', 'PROVIDER_FEASIBILITY_ACCEPTED', 'DISCOVERY_EVIDENCE_ACCEPTED', 'SCOPE0_FROZEN')
       AND gate_result = 'PASS' AND receipt_scope = 'IMPLEMENTATION_GATE_ONLY'
       AND declared_use_semantics = 'SINGLE_USE'
       AND destruction_intent_id IS NULL AND precommitted_destruction_intent_content_hash IS NULL
       AND staged_pre_delete_inventory_hash IS NULL AND staged_intent_created_at IS NULL
       AND intent_authorization_id IS NULL
       AND intent_consumption_id IS NULL AND intent_run_id IS NULL
       AND receipt_bound_run_id IS NULL AND accepted_sanitized_export_manifest_hash IS NULL
       AND receipt_bound_sanitized_export_manifest_hash IS NULL AND intent_receipt_content_hash IS NULL
       AND consumed_before = 'ATOMIC_LEDGER_COMMIT_BEFORE_GATE_USE'
       AND consumption_commit_state = 'COMMITTED_BEFORE_AUTHORIZED_ACTION'
       AND explicit_human_invocation IS NULL AND run_id IS NULL)
      OR
      (receipt_record_type = 'GateReceipt'
       AND receipt_schema_version = 'gate-receipt/v1'
       AND gate_kind = 'EVIDENCE_EXPORT_ACCEPTED' AND gate_result = 'PASS'
       AND receipt_scope = 'WHOLE_RUN_DESTRUCTION_AFTER_ACCEPTED_EXPORT'
       AND run_id IS NOT NULL
       AND destruction_intent_id IS NOT NULL
       AND instr(destruction_intent_id, ':') >= 2
       AND length(destruction_intent_id) - instr(destruction_intent_id, ':') = 64
       AND substr(destruction_intent_id, 1, 1) GLOB '[A-Z]'
       AND substr(destruction_intent_id, 1, instr(destruction_intent_id, ':') - 1) NOT GLOB '*[^A-Z0-9_]*'
       AND substr(destruction_intent_id, instr(destruction_intent_id, ':') + 1) NOT GLOB '*[^0-9a-f]*'
       AND precommitted_destruction_intent_content_hash IS NOT NULL
       AND staged_pre_delete_inventory_hash IS NOT NULL
       AND staged_intent_created_at IS NOT NULL
       AND length(staged_intent_created_at) = 27
       AND staged_intent_created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9][0-9][0-9][0-9]Z'
       AND substr(staged_intent_created_at, 6, 2) BETWEEN '01' AND '12'
       AND substr(staged_intent_created_at, 9, 2) BETWEEN '01' AND '31'
       AND substr(staged_intent_created_at, 12, 2) BETWEEN '00' AND '23'
       AND substr(staged_intent_created_at, 15, 2) BETWEEN '00' AND '59'
       AND substr(staged_intent_created_at, 18, 2) BETWEEN '00' AND '59'
       AND intent_authorization_id IS NOT NULL AND intent_authorization_id = receipt_id
       AND intent_consumption_id IS NOT NULL AND intent_consumption_id = consumption_id
       AND instr(consumption_id, ':') >= 2
       AND length(consumption_id) - instr(consumption_id, ':') = 64
       AND substr(consumption_id, 1, 1) GLOB '[A-Z]'
       AND substr(consumption_id, 1, instr(consumption_id, ':') - 1) NOT GLOB '*[^A-Z0-9_]*'
       AND substr(consumption_id, instr(consumption_id, ':') + 1) NOT GLOB '*[^0-9a-f]*'
       AND intent_run_id IS NOT NULL AND intent_run_id = run_id
       AND receipt_bound_run_id IS NOT NULL AND receipt_bound_run_id = run_id
       AND length(run_id) = 36 AND substr(run_id, 9, 1) = '-' AND substr(run_id, 14, 1) = '-'
       AND substr(run_id, 19, 1) = '-' AND substr(run_id, 24, 1) = '-'
       AND length(replace(run_id, '-', '')) = 32 AND replace(run_id, '-', '') NOT GLOB '*[^0-9a-f]*'
       AND substr(run_id, 15, 1) = '4' AND substr(run_id, 20, 1) IN ('8', '9', 'a', 'b')
       AND length(receipt_id) = 36 AND substr(receipt_id, 9, 1) = '-' AND substr(receipt_id, 14, 1) = '-'
       AND substr(receipt_id, 19, 1) = '-' AND substr(receipt_id, 24, 1) = '-'
       AND length(replace(receipt_id, '-', '')) = 32 AND replace(receipt_id, '-', '') NOT GLOB '*[^0-9a-f]*'
       AND substr(receipt_id, 15, 1) = '4' AND substr(receipt_id, 20, 1) IN ('8', '9', 'a', 'b')
       AND accepted_sanitized_export_manifest_hash IS NOT NULL
       AND receipt_bound_sanitized_export_manifest_hash IS NOT NULL
       AND receipt_bound_sanitized_export_manifest_hash = accepted_sanitized_export_manifest_hash
       AND intent_receipt_content_hash IS NOT NULL AND intent_receipt_content_hash = receipt_content_hash
       AND length(serial) BETWEEN 8 AND 64 AND substr(serial, 1, 1) GLOB '[A-Z0-9]'
       AND serial NOT GLOB '*[^A-Z0-9_-]*'
       AND length(nonce) = 43 AND nonce NOT GLOB '*[^A-Za-z0-9_-]*'
       AND declared_use_semantics = 'SINGLE_USE'
       AND consumed_before = 'ATOMIC_LEDGER_COMMIT_BEFORE_WHOLE_RUN_DESTRUCTION'
       AND consumption_commit_state = 'COMMITTED_BEFORE_WHOLE_RUN_DESTRUCTION'
       AND explicit_human_invocation = 1)
    ) IS TRUE)
) STRICT;

CREATE TABLE revocations (
    revocation_id TEXT PRIMARY KEY,
    ledger_id TEXT NOT NULL,
    issuer TEXT NOT NULL CHECK (length(issuer) BETWEEN 8 AND 128),
    issuer_key_id TEXT NOT NULL CHECK (issuer_key_id GLOB 'key:ed25519:*' AND length(issuer_key_id) = 76),
    audience TEXT NOT NULL CHECK (audience = 'hybrid-discovery:revocation-ledger:v1'),
    subject_id TEXT NOT NULL,
    target_content_hash TEXT NOT NULL CHECK (length(target_content_hash) = 64 AND target_content_hash NOT GLOB '*[^0-9a-f]*'),
    revocation_sequence INTEGER NOT NULL CHECK (revocation_sequence >= 1),
    previous_revocation_hash TEXT NOT NULL CHECK (length(previous_revocation_hash) = 64 AND previous_revocation_hash NOT GLOB '*[^0-9a-f]*'),
    revocation_hash TEXT NOT NULL CHECK (length(revocation_hash) = 64 AND revocation_hash NOT GLOB '*[^0-9a-f]*'),
    checkpoint_sequence INTEGER NOT NULL CHECK (checkpoint_sequence = revocation_sequence),
    checkpoint_head_hash TEXT NOT NULL CHECK (checkpoint_head_hash = revocation_hash),
    effective_at_utc TEXT NOT NULL,
    signature_algorithm TEXT NOT NULL CHECK (signature_algorithm = 'Ed25519'),
    signature TEXT NOT NULL CHECK (length(signature) = 86 AND signature NOT GLOB '*[^A-Za-z0-9_-]*'),
    verification_state TEXT NOT NULL CHECK (verification_state = 'CANONICAL_BYTES_CONTENT_HASH_ED25519_TRUST_AND_CHAIN_VERIFIED'),
    UNIQUE (ledger_id, revocation_sequence),
    UNIQUE (ledger_id, target_content_hash),
    UNIQUE (revocation_hash)
) STRICT;

CREATE TABLE stream_generations (
    generation_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES run_meta(run_id),
    browser_run_id TEXT NOT NULL,
    producer_id TEXT NOT NULL,
    stream_id TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation >= 0),
    predecessor_generation INTEGER,
    generation_state TEXT NOT NULL CHECK (generation_state IN ('ACTIVE', 'QUARANTINED_GAP', 'CLOSED')),
    opened_at_us INTEGER NOT NULL CHECK (opened_at_us >= 0),
    closed_at_us INTEGER CHECK (closed_at_us IS NULL OR closed_at_us >= opened_at_us),
    close_reason TEXT CHECK (close_reason IS NULL OR close_reason IN ('MISSING_SEQUENCE', 'CONFLICTING_DUPLICATE', 'SCHEMA_REJECTION', 'LIFECYCLE_DISCONTINUITY', 'STORAGE_SAFETY_STOP', 'UNKNOWN_CONTINUITY', 'RUN_CLOSED')),
    UNIQUE (run_id, browser_run_id, producer_id, stream_id, generation),
    CHECK ((generation = 0 AND predecessor_generation IS NULL) OR (generation > 0 AND predecessor_generation = generation - 1)),
    CHECK ((generation_state = 'ACTIVE' AND closed_at_us IS NULL AND close_reason IS NULL) OR (generation_state <> 'ACTIVE' AND closed_at_us IS NOT NULL AND close_reason IS NOT NULL)),
    FOREIGN KEY (run_id, browser_run_id, producer_id, stream_id, predecessor_generation)
      REFERENCES stream_generations(run_id, browser_run_id, producer_id, stream_id, generation)
      DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE UNIQUE INDEX one_active_generation_per_stream
ON stream_generations(run_id, browser_run_id, producer_id, stream_id)
WHERE generation_state = 'ACTIVE';

CREATE TABLE raw_commits (
    raw_commit_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    browser_run_id TEXT NOT NULL,
    producer_id TEXT NOT NULL,
    stream_id TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation >= 0),
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    raw_observation_id TEXT NOT NULL UNIQUE,
    raw_observation_content_hash TEXT NOT NULL CHECK (length(raw_observation_content_hash) = 64 AND raw_observation_content_hash NOT GLOB '*[^0-9a-f]*'),
    previous_cursor_hash TEXT NOT NULL CHECK (length(previous_cursor_hash) = 64 AND previous_cursor_hash NOT GLOB '*[^0-9a-f]*'),
    cursor_hash TEXT NOT NULL CHECK (length(cursor_hash) = 64 AND cursor_hash NOT GLOB '*[^0-9a-f]*'),
    cursor_hash_verified INTEGER NOT NULL CHECK (cursor_hash_verified = 1),
    disposition TEXT NOT NULL CHECK (disposition IN ('APPLIED', 'LATE_REPAIR_ONLY', 'QUARANTINED_SCHEMA')),
    committed_at_us INTEGER NOT NULL CHECK (committed_at_us >= 0),
    UNIQUE (run_id, browser_run_id, producer_id, stream_id, generation, sequence),
    UNIQUE (raw_commit_id, run_id, browser_run_id, producer_id, stream_id, generation, sequence),
    FOREIGN KEY (run_id, browser_run_id, producer_id, stream_id, generation)
      REFERENCES stream_generations(run_id, browser_run_id, producer_id, stream_id, generation)
) STRICT;

CREATE TABLE raw_conflicts (
    raw_conflict_id TEXT PRIMARY KEY,
    existing_raw_commit_id TEXT NOT NULL REFERENCES raw_commits(raw_commit_id),
    run_id TEXT NOT NULL,
    browser_run_id TEXT NOT NULL,
    producer_id TEXT NOT NULL,
    stream_id TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation >= 0),
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    conflicting_raw_observation_id TEXT NOT NULL UNIQUE,
    conflicting_content_hash TEXT NOT NULL CHECK (length(conflicting_content_hash) = 64 AND conflicting_content_hash NOT GLOB '*[^0-9a-f]*'),
    detected_at_us INTEGER NOT NULL CHECK (detected_at_us >= 0),
    UNIQUE (run_id, browser_run_id, producer_id, stream_id, generation, sequence, conflicting_content_hash),
    FOREIGN KEY (existing_raw_commit_id, run_id, browser_run_id, producer_id, stream_id, generation, sequence)
      REFERENCES raw_commits(raw_commit_id, run_id, browser_run_id, producer_id, stream_id, generation, sequence)
) STRICT;

CREATE TABLE application_records (
    application_id TEXT PRIMARY KEY,
    raw_commit_id TEXT NOT NULL UNIQUE REFERENCES raw_commits(raw_commit_id),
    run_id TEXT NOT NULL,
    browser_run_id TEXT NOT NULL,
    producer_id TEXT NOT NULL,
    stream_id TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation >= 0),
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    raw_observation_content_hash TEXT NOT NULL CHECK (length(raw_observation_content_hash) = 64 AND raw_observation_content_hash NOT GLOB '*[^0-9a-f]*'),
    input_cursor_hash TEXT NOT NULL CHECK (length(input_cursor_hash) = 64 AND input_cursor_hash NOT GLOB '*[^0-9a-f]*'),
    application_status TEXT NOT NULL CHECK (application_status = 'APPLIED'),
    applied_at_us INTEGER NOT NULL CHECK (applied_at_us >= 0),
    UNIQUE (run_id, browser_run_id, producer_id, stream_id, generation, sequence),
    UNIQUE (application_id, run_id, browser_run_id, producer_id, stream_id, generation, sequence),
    FOREIGN KEY (raw_commit_id, run_id, browser_run_id, producer_id, stream_id, generation, sequence)
      REFERENCES raw_commits(raw_commit_id, run_id, browser_run_id, producer_id, stream_id, generation, sequence)
) STRICT;

CREATE TABLE derived_revisions (
    derived_revision_id TEXT PRIMARY KEY,
    application_id TEXT NOT NULL UNIQUE REFERENCES application_records(application_id),
    raw_commit_id TEXT NOT NULL UNIQUE REFERENCES raw_commits(raw_commit_id),
    run_id TEXT NOT NULL,
    browser_run_id TEXT NOT NULL,
    producer_id TEXT NOT NULL,
    stream_id TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation >= 0),
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    revision INTEGER NOT NULL CHECK (revision >= 1),
    previous_revision_hash TEXT,
    revision_hash TEXT NOT NULL CHECK (length(revision_hash) = 64 AND revision_hash NOT GLOB '*[^0-9a-f]*'),
    created_at_us INTEGER NOT NULL CHECK (created_at_us >= 0),
    UNIQUE (run_id, browser_run_id, producer_id, stream_id, generation, sequence),
    UNIQUE (run_id, browser_run_id, producer_id, stream_id, generation, revision),
    UNIQUE (derived_revision_id, run_id, browser_run_id, producer_id, stream_id, generation, sequence),
    CHECK (previous_revision_hash IS NULL OR (length(previous_revision_hash) = 64 AND previous_revision_hash NOT GLOB '*[^0-9a-f]*')),
    FOREIGN KEY (application_id, run_id, browser_run_id, producer_id, stream_id, generation, sequence)
      REFERENCES application_records(application_id, run_id, browser_run_id, producer_id, stream_id, generation, sequence)
) STRICT;

CREATE TABLE reducer_cursors (
    reducer_cursor_id TEXT PRIMARY KEY,
    derived_revision_id TEXT NOT NULL UNIQUE REFERENCES derived_revisions(derived_revision_id),
    run_id TEXT NOT NULL,
    browser_run_id TEXT NOT NULL,
    producer_id TEXT NOT NULL,
    stream_id TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation >= 0),
    highest_contiguous_sequence INTEGER NOT NULL CHECK (highest_contiguous_sequence >= 1),
    previous_cursor_hash TEXT NOT NULL CHECK (length(previous_cursor_hash) = 64 AND previous_cursor_hash NOT GLOB '*[^0-9a-f]*'),
    cursor_hash TEXT NOT NULL CHECK (length(cursor_hash) = 64 AND cursor_hash NOT GLOB '*[^0-9a-f]*'),
    cursor_hash_verified INTEGER NOT NULL CHECK (cursor_hash_verified = 1),
    raw_observation_content_hash TEXT NOT NULL CHECK (length(raw_observation_content_hash) = 64 AND raw_observation_content_hash NOT GLOB '*[^0-9a-f]*'),
    advanced_at_us INTEGER NOT NULL CHECK (advanced_at_us >= 0),
    UNIQUE (run_id, browser_run_id, producer_id, stream_id, generation, highest_contiguous_sequence),
    UNIQUE (reducer_cursor_id, run_id, browser_run_id, producer_id, stream_id, generation, highest_contiguous_sequence),
    FOREIGN KEY (derived_revision_id, run_id, browser_run_id, producer_id, stream_id, generation, highest_contiguous_sequence)
      REFERENCES derived_revisions(derived_revision_id, run_id, browser_run_id, producer_id, stream_id, generation, sequence)
) STRICT;

CREATE TABLE ack_outbox (
    ack_outbox_id TEXT PRIMARY KEY,
    raw_commit_id TEXT NOT NULL UNIQUE REFERENCES raw_commits(raw_commit_id),
    application_id TEXT NOT NULL UNIQUE REFERENCES application_records(application_id),
    derived_revision_id TEXT NOT NULL UNIQUE REFERENCES derived_revisions(derived_revision_id),
    reducer_cursor_id TEXT NOT NULL UNIQUE REFERENCES reducer_cursors(reducer_cursor_id),
    run_id TEXT NOT NULL,
    browser_run_id TEXT NOT NULL,
    producer_id TEXT NOT NULL,
    stream_id TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation >= 0),
    highest_contiguous_sequence INTEGER NOT NULL CHECK (highest_contiguous_sequence >= 1),
    cursor_hash TEXT NOT NULL CHECK (length(cursor_hash) = 64 AND cursor_hash NOT GLOB '*[^0-9a-f]*'),
    cursor_hash_verified INTEGER NOT NULL CHECK (cursor_hash_verified = 1),
    committed_at_us INTEGER NOT NULL CHECK (committed_at_us >= 0),
    UNIQUE (run_id, browser_run_id, producer_id, stream_id, generation, highest_contiguous_sequence),
    FOREIGN KEY (reducer_cursor_id, run_id, browser_run_id, producer_id, stream_id, generation, highest_contiguous_sequence)
      REFERENCES reducer_cursors(reducer_cursor_id, run_id, browser_run_id, producer_id, stream_id, generation, highest_contiguous_sequence)
) STRICT;

CREATE TABLE ack_cursors (
    ack_cursor_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    browser_run_id TEXT NOT NULL,
    producer_id TEXT NOT NULL,
    stream_id TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation >= 0),
    owner TEXT NOT NULL CHECK (owner IN ('EXTENSION', 'BACKEND')),
    highest_contiguous_sequence INTEGER NOT NULL CHECK (highest_contiguous_sequence >= 0),
    cursor_hash TEXT NOT NULL CHECK (length(cursor_hash) = 64 AND cursor_hash NOT GLOB '*[^0-9a-f]*'),
    chain_verified INTEGER NOT NULL CHECK (chain_verified = 1),
    verified_against TEXT NOT NULL CHECK (verified_against IN ('LOCAL_SPOOL_CHAIN', 'BACKEND_DURABLE_CHAIN')),
    previous_ack_cursor_id TEXT REFERENCES ack_cursors(ack_cursor_id),
    recorded_at_us INTEGER NOT NULL CHECK (recorded_at_us >= 0),
    UNIQUE (run_id, browser_run_id, producer_id, stream_id, generation, owner, highest_contiguous_sequence),
    FOREIGN KEY (run_id, browser_run_id, producer_id, stream_id, generation)
      REFERENCES stream_generations(run_id, browser_run_id, producer_id, stream_id, generation)
) STRICT;

CREATE TABLE gap_records (
    gap_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    browser_run_id TEXT NOT NULL,
    producer_id TEXT NOT NULL,
    stream_id TEXT NOT NULL,
    predecessor_generation INTEGER NOT NULL CHECK (predecessor_generation >= 0),
    successor_generation INTEGER NOT NULL CHECK (successor_generation = predecessor_generation + 1),
    missing_from_sequence INTEGER NOT NULL CHECK (missing_from_sequence >= 1),
    missing_to_sequence INTEGER NOT NULL CHECK (missing_to_sequence >= missing_from_sequence),
    detected_sequence INTEGER NOT NULL CHECK (
      (gap_reason = 'CONFLICTING_DUPLICATE'
       AND missing_from_sequence = missing_to_sequence
       AND missing_to_sequence = detected_sequence)
      OR
      (gap_reason <> 'CONFLICTING_DUPLICATE' AND detected_sequence > missing_to_sequence)
    ),
    gap_reason TEXT NOT NULL CHECK (gap_reason IN ('MISSING_SEQUENCE', 'CONFLICTING_DUPLICATE', 'SCHEMA_REJECTION', 'LIFECYCLE_DISCONTINUITY', 'STORAGE_SAFETY_STOP', 'UNKNOWN_CONTINUITY')),
    repair_status TEXT NOT NULL CHECK (repair_status IN ('OPEN', 'HISTORY_REPAIRED_EPOCH_REMAINS_CLOSED', 'RESNAPSHOT_NEW_GENERATION', 'TERMINAL')),
    ack_blocked_after_sequence INTEGER NOT NULL CHECK (ack_blocked_after_sequence >= 0 AND ack_blocked_after_sequence < missing_from_sequence),
    created_at_us INTEGER NOT NULL CHECK (created_at_us >= 0),
    UNIQUE (run_id, browser_run_id, producer_id, stream_id, predecessor_generation, missing_from_sequence, missing_to_sequence),
    FOREIGN KEY (run_id, browser_run_id, producer_id, stream_id, predecessor_generation)
      REFERENCES stream_generations(run_id, browser_run_id, producer_id, stream_id, generation)
      DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (run_id, browser_run_id, producer_id, stream_id, successor_generation)
      REFERENCES stream_generations(run_id, browser_run_id, producer_id, stream_id, generation)
      DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE gap_epoch_bindings (
    gap_epoch_binding_id TEXT PRIMARY KEY,
    gap_id TEXT NOT NULL REFERENCES gap_records(gap_id),
    predecessor_epoch_id TEXT NOT NULL REFERENCES coherence_epochs(coherence_epoch_id) DEFERRABLE INITIALLY DEFERRED,
    coherence_controller_id TEXT NOT NULL REFERENCES coherence_controllers(coherence_controller_id) DEFERRABLE INITIALLY DEFERRED,
    shock_observation_id TEXT NOT NULL REFERENCES shock_observations(shock_observation_id) DEFERRABLE INITIALLY DEFERRED,
    coherence_transition_id TEXT NOT NULL REFERENCES coherence_transitions(coherence_transition_id) DEFERRABLE INITIALLY DEFERRED,
    binding_role TEXT NOT NULL CHECK (binding_role IN ('AFFECTED_EPOCH_PERMANENTLY_CLOSED', 'SUCCESSOR_CANDIDATE')),
    bound_at_us INTEGER NOT NULL CHECK (bound_at_us >= 0),
    UNIQUE (gap_id, predecessor_epoch_id, binding_role),
    UNIQUE (gap_id, coherence_transition_id)
) STRICT;

CREATE TABLE generation_transitions (
    generation_transition_id TEXT PRIMARY KEY,
    gap_id TEXT NOT NULL UNIQUE REFERENCES gap_records(gap_id),
    run_id TEXT NOT NULL,
    browser_run_id TEXT NOT NULL,
    producer_id TEXT NOT NULL,
    stream_id TEXT NOT NULL,
    predecessor_generation INTEGER NOT NULL CHECK (predecessor_generation >= 0),
    successor_generation INTEGER NOT NULL CHECK (successor_generation = predecessor_generation + 1),
    transition_reason TEXT NOT NULL CHECK (transition_reason IN ('GAP', 'CONFLICT', 'LIFECYCLE_DISCONTINUITY', 'STORAGE_SAFETY_STOP')),
    transitioned_at_us INTEGER NOT NULL CHECK (transitioned_at_us >= 0),
    UNIQUE (run_id, browser_run_id, producer_id, stream_id, predecessor_generation, successor_generation),
    FOREIGN KEY (run_id, browser_run_id, producer_id, stream_id, predecessor_generation)
      REFERENCES stream_generations(run_id, browser_run_id, producer_id, stream_id, generation)
      DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (run_id, browser_run_id, producer_id, stream_id, successor_generation)
      REFERENCES stream_generations(run_id, browser_run_id, producer_id, stream_id, generation)
      DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE clock_observations (
    clock_observation_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES run_meta(run_id),
    clock_domain_id TEXT NOT NULL,
    boot_id TEXT NOT NULL,
    unit TEXT NOT NULL CHECK (unit = 'MICROSECOND'),
    monotonic_value INTEGER NOT NULL CHECK (monotonic_value >= 0),
    resolution_us INTEGER NOT NULL CHECK (resolution_us >= 1),
    owner TEXT NOT NULL CHECK (owner IN ('EXTENSION_SERVICE_WORKER', 'TARGET_DOCUMENT', 'CDP_BROWSER', 'RELAY_PROCESS', 'BACKEND_PROCESS')),
    observed_at_utc TEXT NOT NULL,
    UNIQUE (run_id, clock_domain_id, boot_id, monotonic_value, owner)
) STRICT;

CREATE TABLE clock_mappings (
    clock_mapping_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES run_meta(run_id),
    source_clock_domain_id TEXT NOT NULL,
    source_boot_id TEXT NOT NULL,
    source_owner TEXT NOT NULL CHECK (source_owner IN ('EXTENSION_SERVICE_WORKER', 'TARGET_DOCUMENT', 'CDP_BROWSER', 'RELAY_PROCESS', 'BACKEND_PROCESS')),
    target_clock_domain_id TEXT NOT NULL,
    target_boot_id TEXT NOT NULL,
    target_owner TEXT NOT NULL CHECK (target_owner IN ('EXTENSION_SERVICE_WORKER', 'TARGET_DOCUMENT', 'CDP_BROWSER', 'RELAY_PROCESS', 'BACKEND_PROCESS')),
    unit TEXT NOT NULL CHECK (unit = 'MICROSECOND'),
    sample_count INTEGER NOT NULL CHECK (sample_count BETWEEN 8 AND 32),
    source_anchor_us INTEGER NOT NULL CHECK (source_anchor_us >= 0),
    offset_lower_us INTEGER NOT NULL,
    offset_upper_us INTEGER NOT NULL,
    offset_midpoint_us INTEGER NOT NULL,
    base_uncertainty_us INTEGER NOT NULL CHECK (base_uncertainty_us BETWEEN 0 AND 125000),
    network_rtt_us INTEGER NOT NULL CHECK (network_rtt_us BETWEEN 0 AND 250000),
    relative_drift_ppm INTEGER NOT NULL CHECK (relative_drift_ppm = 100),
    valid_from_source_us INTEGER NOT NULL CHECK (valid_from_source_us >= 0),
    valid_until_source_us INTEGER NOT NULL CHECK (valid_until_source_us >= valid_from_source_us AND valid_until_source_us - valid_from_source_us <= 30000000),
    mapping_status TEXT NOT NULL CHECK (mapping_status = 'OPEN'),
    created_at_us INTEGER NOT NULL CHECK (created_at_us >= 0),
    CHECK (source_clock_domain_id <> target_clock_domain_id),
    CHECK (offset_lower_us <= offset_midpoint_us AND offset_midpoint_us <= offset_upper_us),
    CHECK (offset_lower_us <= 9223372036854775807 - (base_uncertainty_us * 2)),
    CHECK (offset_upper_us = offset_lower_us + (base_uncertainty_us * 2)),
    CHECK (offset_midpoint_us = offset_lower_us + base_uncertainty_us),
    UNIQUE (run_id, source_clock_domain_id, source_boot_id, target_clock_domain_id, target_boot_id, valid_from_source_us)
) STRICT;

CREATE TABLE clock_mapping_closures (
    clock_mapping_closure_id TEXT PRIMARY KEY,
    clock_mapping_id TEXT NOT NULL UNIQUE REFERENCES clock_mappings(clock_mapping_id),
    closure_reason TEXT NOT NULL CHECK (closure_reason IN ('DOMAIN_BOOT_CHANGED', 'MONOTONIC_REGRESSION', 'WALL_CLOCK_STEP', 'SLEEP_RESUME', 'MAX_DURATION', 'RTT_EXCEEDED', 'UNCERTAINTY_EXCEEDED', 'INCONSISTENT_MAPPING', 'LIFECYCLE_INVALIDATED', 'RUN_CLOSED')),
    closed_clock_domain_id TEXT NOT NULL,
    closed_boot_id TEXT NOT NULL,
    closed_at_monotonic_us INTEGER NOT NULL CHECK (closed_at_monotonic_us >= 0),
    permanent INTEGER NOT NULL CHECK (permanent = 1),
    reopen_permitted INTEGER NOT NULL CHECK (reopen_permitted = 0),
    created_at_us INTEGER NOT NULL CHECK (created_at_us >= 0)
) STRICT;

CREATE TABLE shock_observations (
    shock_observation_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES run_meta(run_id),
    fixture_id TEXT NOT NULL,
    shock_type TEXT NOT NULL CHECK (shock_type IN ('GOAL', 'RED_CARD', 'PERIOD_TRANSITION', 'SUSPENSION_MISMATCH', 'SEQUENCE_GAP', 'SCHEMA_CONFLICT', 'LIFECYCLE_INVALIDATION', 'MAPPING_CLOSURE', 'EQUIVALENT_UNKNOWN_SHOCK')),
    shock_lower_bound_us INTEGER NOT NULL,
    shock_upper_bound_us INTEGER NOT NULL CHECK (shock_upper_bound_us >= shock_lower_bound_us),
    evidence_hash TEXT NOT NULL CHECK (length(evidence_hash) = 64 AND evidence_hash NOT GLOB '*[^0-9a-f]*'),
    created_at_us INTEGER NOT NULL CHECK (created_at_us >= 0)
) STRICT;

CREATE TABLE coherence_controllers (
    coherence_controller_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES run_meta(run_id),
    fixture_id TEXT NOT NULL,
    controller_state TEXT NOT NULL CHECK (controller_state IN ('OPEN', 'SHOCKED_CLOSED', 'WAITING_FOR_RESNAPSHOT', 'NEW_EPOCH_PENDING', 'NEW_EPOCH_OPEN')),
    current_epoch_id TEXT NOT NULL REFERENCES coherence_epochs(coherence_epoch_id) DEFERRABLE INITIALLY DEFERRED,
    candidate_epoch_id TEXT REFERENCES coherence_epochs(coherence_epoch_id) DEFERRABLE INITIALLY DEFERRED,
    predecessor_epoch_id TEXT REFERENCES coherence_epochs(coherence_epoch_id) DEFERRABLE INITIALLY DEFERRED,
    active_shock_observation_id TEXT REFERENCES shock_observations(shock_observation_id),
    controller_revision INTEGER NOT NULL CHECK (controller_revision >= 0),
    updated_at_us INTEGER NOT NULL CHECK (updated_at_us >= 0),
    UNIQUE (run_id, fixture_id),
    CHECK ((controller_state = 'NEW_EPOCH_PENDING' AND candidate_epoch_id IS NOT NULL AND candidate_epoch_id <> current_epoch_id) OR
           (controller_state <> 'NEW_EPOCH_PENDING' AND candidate_epoch_id IS NULL))
) STRICT;

CREATE TABLE coherence_epochs (
    coherence_epoch_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES run_meta(run_id),
    fixture_id TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation >= 0),
    predecessor_epoch_id TEXT REFERENCES coherence_epochs(coherence_epoch_id),
    epoch_status_at_record TEXT NOT NULL CHECK (epoch_status_at_record IN ('OPEN', 'CLOSED')),
    opening_freshness_vector_id TEXT,
    opening_resnapshot_proof_id TEXT,
    opened_at_us INTEGER NOT NULL CHECK (opened_at_us >= 0),
    predecessor_permanently_closed INTEGER NOT NULL CHECK (predecessor_permanently_closed IN (0, 1)),
    UNIQUE (run_id, fixture_id, generation),
    CHECK (predecessor_epoch_id IS NULL OR predecessor_epoch_id <> coherence_epoch_id),
    CHECK ((generation = 0 AND predecessor_epoch_id IS NULL AND opening_freshness_vector_id IS NULL AND opening_resnapshot_proof_id IS NULL AND predecessor_permanently_closed = 0) OR
           (generation > 0 AND predecessor_epoch_id IS NOT NULL AND opening_freshness_vector_id IS NOT NULL AND opening_resnapshot_proof_id IS NOT NULL AND predecessor_permanently_closed = 1))
) STRICT;

CREATE TABLE coherence_transitions (
    coherence_transition_id TEXT PRIMARY KEY,
    coherence_controller_id TEXT NOT NULL REFERENCES coherence_controllers(coherence_controller_id),
    fixture_id TEXT NOT NULL,
    from_state TEXT NOT NULL CHECK (from_state IN ('OPEN', 'SHOCKED_CLOSED', 'WAITING_FOR_RESNAPSHOT', 'NEW_EPOCH_PENDING', 'NEW_EPOCH_OPEN')),
    to_state TEXT NOT NULL CHECK (to_state IN ('SHOCKED_CLOSED', 'WAITING_FOR_RESNAPSHOT', 'NEW_EPOCH_PENDING', 'NEW_EPOCH_OPEN')),
    predecessor_epoch_id TEXT NOT NULL REFERENCES coherence_epochs(coherence_epoch_id),
    candidate_epoch_id TEXT REFERENCES coherence_epochs(coherence_epoch_id),
    shock_observation_id TEXT REFERENCES shock_observations(shock_observation_id),
    input_freshness_vector_id TEXT REFERENCES input_freshness_vectors(input_freshness_vector_id) DEFERRABLE INITIALLY DEFERRED,
    resnapshot_proof_id TEXT REFERENCES authoritative_resnapshot_proofs(authoritative_resnapshot_proof_id) DEFERRABLE INITIALLY DEFERRED,
    bindings_verified INTEGER NOT NULL CHECK (bindings_verified = 1),
    transition_reason TEXT NOT NULL CHECK (transition_reason IN ('SHOCK_ATOMIC_CLOSE', 'CLOSE_RECORDED', 'RESNAPSHOT_CANDIDATE_ACCEPTED', 'RELEASE_PREDICATE_SATISFIED', 'NEW_SHOCK_CLOSED_CANDIDATE')),
    transitioned_at_us INTEGER NOT NULL CHECK (transitioned_at_us >= 0),
    CHECK (
      (from_state IN ('OPEN', 'NEW_EPOCH_OPEN') AND to_state = 'SHOCKED_CLOSED' AND transition_reason = 'SHOCK_ATOMIC_CLOSE') OR
      (from_state = 'SHOCKED_CLOSED' AND to_state = 'WAITING_FOR_RESNAPSHOT' AND transition_reason = 'CLOSE_RECORDED') OR
      (from_state = 'WAITING_FOR_RESNAPSHOT' AND to_state = 'NEW_EPOCH_PENDING' AND transition_reason = 'RESNAPSHOT_CANDIDATE_ACCEPTED') OR
      (from_state = 'NEW_EPOCH_PENDING' AND to_state = 'NEW_EPOCH_OPEN' AND transition_reason = 'RELEASE_PREDICATE_SATISFIED') OR
      (from_state = 'NEW_EPOCH_PENDING' AND to_state = 'WAITING_FOR_RESNAPSHOT' AND transition_reason = 'NEW_SHOCK_CLOSED_CANDIDATE')
    )
) STRICT;

CREATE TABLE input_freshness_vectors (
    input_freshness_vector_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES run_meta(run_id),
    fixture_id TEXT NOT NULL,
    football_state_status TEXT NOT NULL CHECK (football_state_status IN ('FRESH', 'STALE', 'UNKNOWN', 'NOT_REQUIRED_FOR_THIS_DISCOVERY_CHECK')),
    operator_state_status TEXT NOT NULL CHECK (operator_state_status IN ('FRESH', 'STALE', 'UNKNOWN', 'NOT_REQUIRED_FOR_THIS_DISCOVERY_CHECK')),
    market_book_status TEXT NOT NULL CHECK (market_book_status IN ('FRESH', 'STALE', 'UNKNOWN', 'NOT_REQUIRED_FOR_THIS_DISCOVERY_CHECK')),
    display_evidence_status TEXT NOT NULL CHECK (display_evidence_status IN ('FRESH', 'STALE', 'UNKNOWN', 'NOT_REQUIRED_FOR_THIS_DISCOVERY_CHECK')),
    betslip_evidence_status TEXT NOT NULL CHECK (betslip_evidence_status IN ('FRESH', 'STALE', 'UNKNOWN', 'NOT_REQUIRED_FOR_THIS_DISCOVERY_CHECK')),
    position_status TEXT NOT NULL CHECK (position_status IN ('FRESH', 'STALE', 'UNKNOWN', 'NOT_REQUIRED_FOR_THIS_DISCOVERY_CHECK')),
    cashout_offer_status TEXT NOT NULL CHECK (cashout_offer_status IN ('FRESH', 'STALE', 'UNKNOWN', 'NOT_REQUIRED_FOR_THIS_DISCOVERY_CHECK')),
    vector_hash TEXT NOT NULL CHECK (length(vector_hash) = 64 AND vector_hash NOT GLOB '*[^0-9a-f]*'),
    created_at_us INTEGER NOT NULL CHECK (created_at_us >= 0)
) STRICT;

CREATE TABLE authoritative_resnapshot_proofs (
    authoritative_resnapshot_proof_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES run_meta(run_id),
    fixture_id TEXT NOT NULL,
    predecessor_epoch_id TEXT NOT NULL REFERENCES coherence_epochs(coherence_epoch_id),
    candidate_epoch_id TEXT REFERENCES coherence_epochs(coherence_epoch_id),
    shock_observation_id TEXT NOT NULL REFERENCES shock_observations(shock_observation_id),
    proof_status TEXT NOT NULL CHECK (proof_status IN ('OBSERVED', 'NOT_OBSERVED', 'UNKNOWN')),
    accepted_capability_evidence_id TEXT,
    freshness_vector_id TEXT REFERENCES input_freshness_vectors(input_freshness_vector_id),
    football_mapping_id TEXT REFERENCES clock_mappings(clock_mapping_id),
    operator_mapping_id TEXT REFERENCES clock_mappings(clock_mapping_id),
    market_book_mapping_id TEXT REFERENCES clock_mappings(clock_mapping_id),
    mapping_bindings_hash TEXT,
    continuity_reducer_cursor_id TEXT REFERENCES reducer_cursors(reducer_cursor_id),
    continuity_bindings_hash TEXT,
    proof_verified INTEGER NOT NULL CHECK (proof_verified IN (0, 1)),
    predecessor_permanently_closed INTEGER NOT NULL CHECK (predecessor_permanently_closed IN (0, 1)),
    candidate_distinct_from_predecessor INTEGER NOT NULL CHECK (candidate_distinct_from_predecessor IN (0, 1)),
    release_predicate TEXT NOT NULL CHECK (release_predicate IN ('SATISFIED', 'NOT_SATISFIED')),
    proof_hash TEXT NOT NULL CHECK (length(proof_hash) = 64 AND proof_hash NOT GLOB '*[^0-9a-f]*'),
    created_at_us INTEGER NOT NULL CHECK (created_at_us >= 0),
    CHECK (
      (proof_status = 'OBSERVED' AND accepted_capability_evidence_id IS NOT NULL AND candidate_epoch_id IS NOT NULL AND candidate_epoch_id <> predecessor_epoch_id AND freshness_vector_id IS NOT NULL AND football_mapping_id IS NOT NULL AND operator_mapping_id IS NOT NULL AND market_book_mapping_id IS NOT NULL AND mapping_bindings_hash IS NOT NULL AND length(mapping_bindings_hash) = 64 AND mapping_bindings_hash NOT GLOB '*[^0-9a-f]*' AND continuity_reducer_cursor_id IS NOT NULL AND continuity_bindings_hash IS NOT NULL AND length(continuity_bindings_hash) = 64 AND continuity_bindings_hash NOT GLOB '*[^0-9a-f]*' AND proof_verified = 1 AND predecessor_permanently_closed = 1 AND candidate_distinct_from_predecessor = 1 AND release_predicate = 'SATISFIED') OR
      (proof_status IN ('NOT_OBSERVED', 'UNKNOWN') AND proof_verified = 0 AND release_predicate = 'NOT_SATISFIED')
    )
) STRICT;

CREATE INDEX raw_commits_generation_order
ON raw_commits(run_id, browser_run_id, producer_id, stream_id, generation, sequence);

CREATE INDEX ack_outbox_generation_order
ON ack_outbox(run_id, browser_run_id, producer_id, stream_id, generation, highest_contiguous_sequence);

CREATE INDEX clock_mapping_selection
ON clock_mappings(source_clock_domain_id, source_boot_id, target_clock_domain_id, target_boot_id, valid_from_source_us, valid_until_source_us);

CREATE INDEX coherence_transition_order
ON coherence_transitions(coherence_controller_id, transitioned_at_us);

CREATE TRIGGER raw_commits_position_guard
BEFORE INSERT ON raw_commits
BEGIN
  SELECT CASE
    WHEN NEW.disposition = 'APPLIED' AND NOT EXISTS (
      SELECT 1 FROM stream_generations g
      WHERE g.run_id = NEW.run_id AND g.browser_run_id = NEW.browser_run_id
        AND g.producer_id = NEW.producer_id AND g.stream_id = NEW.stream_id
        AND g.generation = NEW.generation AND g.generation_state = 'ACTIVE'
    ) THEN RAISE(ABORT, 'E_RAW_GENERATION_NOT_ACTIVE')
    WHEN NEW.disposition = 'APPLIED' AND NEW.sequence <> COALESCE((
      SELECT MAX(r.sequence) FROM raw_commits r
      WHERE r.run_id = NEW.run_id AND r.browser_run_id = NEW.browser_run_id
        AND r.producer_id = NEW.producer_id AND r.stream_id = NEW.stream_id
        AND r.generation = NEW.generation AND r.disposition = 'APPLIED'
    ), 0) + 1 THEN RAISE(ABORT, 'E_RAW_NONCONTIGUOUS')
    WHEN NEW.disposition = 'APPLIED' AND NEW.sequence = 1
      AND NEW.previous_cursor_hash <> '149300a0e3954885a1d6c0f13a9d1101227cc21cce37bd6b7c72eab641741c0c'
      THEN RAISE(ABORT, 'E_CURSOR_FIRST_STEP_NOT_H0')
    WHEN NEW.disposition = 'APPLIED' AND NEW.sequence > 1 AND NOT EXISTS (
      SELECT 1 FROM reducer_cursors c
      WHERE c.run_id = NEW.run_id AND c.browser_run_id = NEW.browser_run_id
        AND c.producer_id = NEW.producer_id AND c.stream_id = NEW.stream_id
        AND c.generation = NEW.generation
        AND c.highest_contiguous_sequence = NEW.sequence - 1
        AND c.cursor_hash = NEW.previous_cursor_hash
        AND c.cursor_hash_verified = 1
    ) THEN RAISE(ABORT, 'E_CURSOR_PREDECESSOR_LINK')
    WHEN NEW.disposition = 'LATE_REPAIR_ONLY' AND NOT EXISTS (
      SELECT 1 FROM stream_generations g
      WHERE g.run_id = NEW.run_id AND g.browser_run_id = NEW.browser_run_id
        AND g.producer_id = NEW.producer_id AND g.stream_id = NEW.stream_id
        AND g.generation = NEW.generation AND g.generation_state <> 'ACTIVE'
    ) THEN RAISE(ABORT, 'E_LATE_REPAIR_REQUIRES_CLOSED_GENERATION')
  END;
END;

CREATE TRIGGER ack_cursor_requires_durable_chain
BEFORE INSERT ON ack_cursors
BEGIN
  SELECT CASE
    WHEN (NEW.owner = 'BACKEND' AND NEW.verified_against <> 'BACKEND_DURABLE_CHAIN') OR
         (NEW.owner = 'EXTENSION' AND NEW.verified_against <> 'LOCAL_SPOOL_CHAIN')
      THEN RAISE(ABORT, 'E_ACK_VERIFICATION_OWNER')
    WHEN NEW.highest_contiguous_sequence = 0 AND
         (NEW.cursor_hash <> '149300a0e3954885a1d6c0f13a9d1101227cc21cce37bd6b7c72eab641741c0c' OR NEW.previous_ack_cursor_id IS NOT NULL)
      THEN RAISE(ABORT, 'E_ACK_ZERO_NOT_H0')
    WHEN NEW.highest_contiguous_sequence > 0 AND NOT EXISTS (
      SELECT 1 FROM ack_outbox o
      JOIN reducer_cursors c ON c.reducer_cursor_id = o.reducer_cursor_id
      JOIN raw_commits r ON r.raw_commit_id = o.raw_commit_id
      WHERE o.run_id = NEW.run_id AND o.browser_run_id = NEW.browser_run_id
        AND o.producer_id = NEW.producer_id AND o.stream_id = NEW.stream_id
        AND o.generation = NEW.generation
        AND o.highest_contiguous_sequence = NEW.highest_contiguous_sequence
        AND o.cursor_hash = NEW.cursor_hash AND o.cursor_hash_verified = 1
        AND c.cursor_hash = NEW.cursor_hash AND c.cursor_hash_verified = 1
        AND r.sequence = NEW.highest_contiguous_sequence AND r.cursor_hash = NEW.cursor_hash
        AND r.cursor_hash_verified = 1 AND r.disposition = 'APPLIED'
    ) THEN RAISE(ABORT, 'E_ACK_WITHOUT_DURABLE_CHAIN')
    WHEN EXISTS (
      SELECT 1 FROM ack_cursors p
      WHERE p.run_id = NEW.run_id AND p.browser_run_id = NEW.browser_run_id
        AND p.producer_id = NEW.producer_id AND p.stream_id = NEW.stream_id
        AND p.generation = NEW.generation AND p.owner = NEW.owner
        AND p.highest_contiguous_sequence >= NEW.highest_contiguous_sequence
    ) THEN RAISE(ABORT, 'E_ACK_REGRESSION')
    WHEN NEW.previous_ack_cursor_id IS NOT NULL AND NEW.previous_ack_cursor_id IS NOT (
      SELECT p.ack_cursor_id FROM ack_cursors p
      WHERE p.run_id = NEW.run_id AND p.browser_run_id = NEW.browser_run_id
        AND p.producer_id = NEW.producer_id AND p.stream_id = NEW.stream_id
        AND p.generation = NEW.generation AND p.owner = NEW.owner
      ORDER BY p.highest_contiguous_sequence DESC LIMIT 1
    ) THEN RAISE(ABORT, 'E_ACK_PREDECESSOR')
  END;
END;

CREATE TRIGGER application_requires_applied_raw
BEFORE INSERT ON application_records
BEGIN
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM raw_commits r
    WHERE r.raw_commit_id = NEW.raw_commit_id AND r.run_id = NEW.run_id
      AND r.browser_run_id = NEW.browser_run_id AND r.producer_id = NEW.producer_id
      AND r.stream_id = NEW.stream_id AND r.generation = NEW.generation
      AND r.sequence = NEW.sequence AND r.disposition = 'APPLIED'
      AND r.raw_observation_content_hash = NEW.raw_observation_content_hash
      AND r.previous_cursor_hash = NEW.input_cursor_hash
  ) THEN RAISE(ABORT, 'E_APPLICATION_WITHOUT_MATCHING_APPLIED_RAW') END;
END;

CREATE TRIGGER derived_revision_requires_application
BEFORE INSERT ON derived_revisions
BEGIN
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM application_records a
    WHERE a.application_id = NEW.application_id AND a.raw_commit_id = NEW.raw_commit_id
      AND a.run_id = NEW.run_id AND a.browser_run_id = NEW.browser_run_id
      AND a.producer_id = NEW.producer_id AND a.stream_id = NEW.stream_id
      AND a.generation = NEW.generation AND a.sequence = NEW.sequence
  ) THEN RAISE(ABORT, 'E_REVISION_WITHOUT_MATCHING_APPLICATION') END;
END;

CREATE TRIGGER reducer_cursor_requires_revision_and_raw
BEFORE INSERT ON reducer_cursors
BEGIN
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM derived_revisions d
    JOIN raw_commits r ON r.raw_commit_id = d.raw_commit_id
    WHERE d.derived_revision_id = NEW.derived_revision_id
      AND d.run_id = NEW.run_id AND d.browser_run_id = NEW.browser_run_id
      AND d.producer_id = NEW.producer_id AND d.stream_id = NEW.stream_id
      AND d.generation = NEW.generation AND d.sequence = NEW.highest_contiguous_sequence
      AND r.raw_observation_content_hash = NEW.raw_observation_content_hash
      AND r.previous_cursor_hash = NEW.previous_cursor_hash
      AND r.cursor_hash = NEW.cursor_hash
  ) THEN RAISE(ABORT, 'E_CURSOR_WITHOUT_MATCHING_REVISION_CHAIN') END;
END;

CREATE TRIGGER ack_outbox_requires_complete_position
BEFORE INSERT ON ack_outbox
BEGIN
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1
    FROM raw_commits r
    JOIN application_records a ON a.raw_commit_id = r.raw_commit_id
    JOIN derived_revisions d ON d.application_id = a.application_id AND d.raw_commit_id = r.raw_commit_id
    JOIN reducer_cursors c ON c.derived_revision_id = d.derived_revision_id
    WHERE r.raw_commit_id = NEW.raw_commit_id
      AND a.application_id = NEW.application_id
      AND d.derived_revision_id = NEW.derived_revision_id
      AND c.reducer_cursor_id = NEW.reducer_cursor_id
      AND r.run_id = NEW.run_id AND r.browser_run_id = NEW.browser_run_id
      AND r.producer_id = NEW.producer_id AND r.stream_id = NEW.stream_id
      AND r.generation = NEW.generation AND r.sequence = NEW.highest_contiguous_sequence
      AND r.disposition = 'APPLIED'
      AND c.cursor_hash = NEW.cursor_hash
      AND c.highest_contiguous_sequence = NEW.highest_contiguous_sequence
  ) THEN RAISE(ABORT, 'E_ACK_WITHOUT_COMPLETE_POSITION') END;
END;

CREATE TRIGGER stream_generation_update_guard
BEFORE UPDATE ON stream_generations
BEGIN
  SELECT CASE WHEN
    NEW.generation_id <> OLD.generation_id OR NEW.run_id <> OLD.run_id OR
    NEW.browser_run_id <> OLD.browser_run_id OR NEW.producer_id <> OLD.producer_id OR
    NEW.stream_id <> OLD.stream_id OR NEW.generation <> OLD.generation OR
    NEW.predecessor_generation IS NOT OLD.predecessor_generation OR NEW.opened_at_us <> OLD.opened_at_us OR
    NOT ((OLD.generation_state = 'ACTIVE' AND NEW.generation_state IN ('QUARANTINED_GAP', 'CLOSED')) OR
         (OLD.generation_state = 'QUARANTINED_GAP' AND NEW.generation_state = 'CLOSED'))
  THEN RAISE(ABORT, 'E_INVALID_GENERATION_MUTATION') END;
END;

CREATE TRIGGER stream_generation_gap_close_requires_coherence
BEFORE UPDATE ON stream_generations
WHEN OLD.generation_state = 'ACTIVE' AND NEW.generation_state <> 'ACTIVE' AND NEW.close_reason <> 'RUN_CLOSED'
BEGIN
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1
    FROM gap_records g
    JOIN gap_epoch_bindings b ON b.gap_id = g.gap_id AND b.binding_role = 'AFFECTED_EPOCH_PERMANENTLY_CLOSED'
    JOIN coherence_transitions t ON t.coherence_transition_id = b.coherence_transition_id
    JOIN coherence_controllers c ON c.coherence_controller_id = b.coherence_controller_id
    WHERE g.run_id = NEW.run_id AND g.browser_run_id = NEW.browser_run_id
      AND g.producer_id = NEW.producer_id AND g.stream_id = NEW.stream_id
      AND g.predecessor_generation = NEW.generation AND g.gap_reason = NEW.close_reason
      AND t.coherence_controller_id = c.coherence_controller_id
      AND t.predecessor_epoch_id = b.predecessor_epoch_id
      AND t.shock_observation_id = b.shock_observation_id
      AND t.from_state IN ('OPEN', 'NEW_EPOCH_OPEN') AND t.to_state = 'SHOCKED_CLOSED'
      AND t.transition_reason = 'SHOCK_ATOMIC_CLOSE' AND t.bindings_verified = 1
      AND c.current_epoch_id = b.predecessor_epoch_id AND c.controller_state = 'SHOCKED_CLOSED'
      AND c.active_shock_observation_id = b.shock_observation_id
  ) THEN RAISE(ABORT, 'E_GENERATION_CLOSE_WITHOUT_COHERENCE_CLOSURE') END;
END;

CREATE TRIGGER successor_generation_requires_coherence_closure
BEFORE INSERT ON stream_generations
WHEN NEW.generation > 0
BEGIN
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1
    FROM generation_transitions gt
    JOIN gap_records g ON g.gap_id = gt.gap_id
    JOIN gap_epoch_bindings b ON b.gap_id = g.gap_id AND b.binding_role = 'AFFECTED_EPOCH_PERMANENTLY_CLOSED'
    JOIN coherence_transitions t ON t.coherence_transition_id = b.coherence_transition_id
    JOIN coherence_controllers c ON c.coherence_controller_id = b.coherence_controller_id
    JOIN stream_generations p ON p.run_id = NEW.run_id AND p.browser_run_id = NEW.browser_run_id
      AND p.producer_id = NEW.producer_id AND p.stream_id = NEW.stream_id
      AND p.generation = NEW.predecessor_generation
    WHERE gt.run_id = NEW.run_id AND gt.browser_run_id = NEW.browser_run_id
      AND gt.producer_id = NEW.producer_id AND gt.stream_id = NEW.stream_id
      AND gt.predecessor_generation = NEW.predecessor_generation
      AND gt.successor_generation = NEW.generation
      AND p.generation_state <> 'ACTIVE'
      AND t.predecessor_epoch_id = b.predecessor_epoch_id
      AND t.shock_observation_id = b.shock_observation_id
      AND t.to_state = 'SHOCKED_CLOSED' AND t.bindings_verified = 1
      AND c.controller_state = 'SHOCKED_CLOSED' AND c.current_epoch_id = b.predecessor_epoch_id
  ) THEN RAISE(ABORT, 'E_GENERATION_OPEN_WITHOUT_COHERENCE_CLOSURE') END;
END;

CREATE TRIGGER gap_epoch_binding_requires_atomic_coherence_close
BEFORE INSERT ON gap_epoch_bindings
BEGIN
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1
    FROM gap_records g
    JOIN coherence_transitions t ON t.coherence_transition_id = NEW.coherence_transition_id
    JOIN coherence_controllers c ON c.coherence_controller_id = NEW.coherence_controller_id
    JOIN shock_observations s ON s.shock_observation_id = NEW.shock_observation_id
    WHERE g.gap_id = NEW.gap_id
      AND NEW.binding_role = 'AFFECTED_EPOCH_PERMANENTLY_CLOSED'
      AND t.coherence_controller_id = NEW.coherence_controller_id
      AND t.predecessor_epoch_id = NEW.predecessor_epoch_id
      AND t.shock_observation_id = NEW.shock_observation_id
      AND t.from_state IN ('OPEN', 'NEW_EPOCH_OPEN') AND t.to_state = 'SHOCKED_CLOSED'
      AND t.transition_reason = 'SHOCK_ATOMIC_CLOSE' AND t.bindings_verified = 1
      AND c.run_id = g.run_id AND c.fixture_id = s.fixture_id
      AND c.current_epoch_id = NEW.predecessor_epoch_id AND c.controller_state = 'SHOCKED_CLOSED'
      AND c.active_shock_observation_id = NEW.shock_observation_id
      AND s.run_id = g.run_id
      AND s.shock_type IN ('SEQUENCE_GAP', 'SCHEMA_CONFLICT', 'LIFECYCLE_INVALIDATION', 'EQUIVALENT_UNKNOWN_SHOCK')
  ) THEN RAISE(ABORT, 'E_GAP_WITHOUT_ATOMIC_COHERENCE_CLOSE') END;
END;

CREATE TRIGGER stream_generations_no_delete
BEFORE DELETE ON stream_generations BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_DELETE'); END;

CREATE TRIGGER coherence_controller_update_guard
BEFORE UPDATE ON coherence_controllers
BEGIN
  SELECT CASE WHEN
    NEW.coherence_controller_id <> OLD.coherence_controller_id OR NEW.run_id <> OLD.run_id OR
    NEW.fixture_id <> OLD.fixture_id OR NEW.controller_revision <> OLD.controller_revision + 1 OR
    NOT (
      (OLD.controller_state IN ('OPEN', 'NEW_EPOCH_OPEN') AND NEW.controller_state = 'SHOCKED_CLOSED'
        AND NEW.current_epoch_id = OLD.current_epoch_id AND NEW.candidate_epoch_id IS NULL
        AND NEW.predecessor_epoch_id IS OLD.predecessor_epoch_id AND NEW.active_shock_observation_id IS NOT NULL
        AND EXISTS (SELECT 1 FROM coherence_transitions t
          WHERE t.coherence_controller_id = OLD.coherence_controller_id
            AND t.from_state = OLD.controller_state AND t.to_state = 'SHOCKED_CLOSED'
            AND t.predecessor_epoch_id = OLD.current_epoch_id
            AND t.shock_observation_id = NEW.active_shock_observation_id
            AND t.transition_reason = 'SHOCK_ATOMIC_CLOSE' AND t.bindings_verified = 1)) OR
      (OLD.controller_state = 'SHOCKED_CLOSED' AND NEW.controller_state = 'WAITING_FOR_RESNAPSHOT'
        AND NEW.current_epoch_id = OLD.current_epoch_id AND NEW.candidate_epoch_id IS NULL
        AND NEW.predecessor_epoch_id IS OLD.predecessor_epoch_id
        AND NEW.active_shock_observation_id = OLD.active_shock_observation_id) OR
      (OLD.controller_state = 'WAITING_FOR_RESNAPSHOT' AND NEW.controller_state = 'NEW_EPOCH_PENDING'
        AND NEW.current_epoch_id = OLD.current_epoch_id AND NEW.candidate_epoch_id IS NOT NULL
        AND NEW.candidate_epoch_id <> OLD.current_epoch_id
        AND NEW.active_shock_observation_id = OLD.active_shock_observation_id
        AND EXISTS (SELECT 1 FROM coherence_transitions t
          WHERE t.coherence_controller_id = OLD.coherence_controller_id
            AND t.from_state = 'WAITING_FOR_RESNAPSHOT' AND t.to_state = 'NEW_EPOCH_PENDING'
            AND t.predecessor_epoch_id = OLD.current_epoch_id
            AND t.candidate_epoch_id = NEW.candidate_epoch_id
            AND t.shock_observation_id = OLD.active_shock_observation_id
            AND t.input_freshness_vector_id IS NOT NULL AND t.resnapshot_proof_id IS NOT NULL
            AND t.transition_reason = 'RESNAPSHOT_CANDIDATE_ACCEPTED' AND t.bindings_verified = 1)) OR
      (OLD.controller_state = 'NEW_EPOCH_PENDING' AND NEW.controller_state = 'NEW_EPOCH_OPEN'
        AND OLD.candidate_epoch_id IS NOT NULL AND NEW.current_epoch_id = OLD.candidate_epoch_id
        AND NEW.current_epoch_id <> OLD.current_epoch_id AND NEW.candidate_epoch_id IS NULL
        AND NEW.predecessor_epoch_id = OLD.current_epoch_id
        AND NEW.active_shock_observation_id = OLD.active_shock_observation_id
        AND EXISTS (SELECT 1 FROM coherence_transitions t
          JOIN authoritative_resnapshot_proofs p ON p.authoritative_resnapshot_proof_id = t.resnapshot_proof_id
          JOIN coherence_epochs e ON e.coherence_epoch_id = t.candidate_epoch_id
          JOIN input_freshness_vectors f ON f.input_freshness_vector_id = t.input_freshness_vector_id
          JOIN shock_observations s ON s.shock_observation_id = t.shock_observation_id
          JOIN clock_mappings fm ON fm.clock_mapping_id = p.football_mapping_id
          JOIN clock_mappings om ON om.clock_mapping_id = p.operator_mapping_id
          JOIN clock_mappings bm ON bm.clock_mapping_id = p.market_book_mapping_id
          JOIN reducer_cursors rc ON rc.reducer_cursor_id = p.continuity_reducer_cursor_id
          JOIN stream_generations cg ON cg.run_id = rc.run_id AND cg.browser_run_id = rc.browser_run_id
            AND cg.producer_id = rc.producer_id AND cg.stream_id = rc.stream_id AND cg.generation = rc.generation
          WHERE t.coherence_controller_id = OLD.coherence_controller_id
            AND t.from_state = 'NEW_EPOCH_PENDING' AND t.to_state = 'NEW_EPOCH_OPEN'
            AND t.predecessor_epoch_id = OLD.current_epoch_id
            AND t.candidate_epoch_id = OLD.candidate_epoch_id
            AND t.shock_observation_id = OLD.active_shock_observation_id
            AND t.transition_reason = 'RELEASE_PREDICATE_SATISFIED' AND t.bindings_verified = 1
            AND e.run_id = OLD.run_id AND e.fixture_id = OLD.fixture_id
            AND e.predecessor_epoch_id = OLD.current_epoch_id
            AND e.opening_freshness_vector_id = t.input_freshness_vector_id
            AND e.opening_resnapshot_proof_id = t.resnapshot_proof_id
            AND e.predecessor_permanently_closed = 1
            AND p.run_id = OLD.run_id AND p.fixture_id = OLD.fixture_id
            AND p.proof_status = 'OBSERVED' AND p.proof_verified = 1
            AND p.predecessor_epoch_id = t.predecessor_epoch_id AND p.candidate_epoch_id = t.candidate_epoch_id
            AND p.shock_observation_id = t.shock_observation_id AND p.freshness_vector_id = t.input_freshness_vector_id
            AND p.accepted_capability_evidence_id IS NOT NULL
            AND p.predecessor_permanently_closed = 1 AND p.candidate_distinct_from_predecessor = 1
            AND p.release_predicate = 'SATISFIED'
            AND p.mapping_bindings_hash IS NOT NULL AND p.continuity_bindings_hash IS NOT NULL
            AND f.run_id = OLD.run_id AND f.fixture_id = OLD.fixture_id
            AND f.football_state_status = 'FRESH' AND f.operator_state_status = 'FRESH' AND f.market_book_status = 'FRESH'
            AND s.run_id = OLD.run_id AND s.fixture_id = OLD.fixture_id
            AND fm.run_id = OLD.run_id AND fm.mapping_status = 'OPEN'
            AND om.run_id = OLD.run_id AND om.mapping_status = 'OPEN'
            AND bm.run_id = OLD.run_id AND bm.mapping_status = 'OPEN'
            AND NOT EXISTS (SELECT 1 FROM clock_mapping_closures mc WHERE mc.clock_mapping_id IN (fm.clock_mapping_id, om.clock_mapping_id, bm.clock_mapping_id))
            AND rc.run_id = OLD.run_id AND rc.generation = e.generation AND rc.cursor_hash_verified = 1
            AND cg.generation_state = 'ACTIVE')) OR
      (OLD.controller_state = 'NEW_EPOCH_PENDING' AND NEW.controller_state = 'WAITING_FOR_RESNAPSHOT'
        AND NEW.current_epoch_id = OLD.current_epoch_id AND NEW.candidate_epoch_id IS NULL
        AND NEW.active_shock_observation_id IS NOT NULL
        AND NEW.active_shock_observation_id <> OLD.active_shock_observation_id)
    )
  THEN RAISE(ABORT, 'E_INVALID_COHERENCE_TRANSITION') END;
END;

CREATE TRIGGER coherence_transition_binding_guard
BEFORE INSERT ON coherence_transitions
BEGIN
  SELECT CASE
    WHEN NEW.transition_reason = 'SHOCK_ATOMIC_CLOSE' AND NOT EXISTS (
      SELECT 1 FROM coherence_controllers c
      JOIN shock_observations s ON s.shock_observation_id = NEW.shock_observation_id
      WHERE c.coherence_controller_id = NEW.coherence_controller_id
        AND c.fixture_id = NEW.fixture_id AND c.current_epoch_id = NEW.predecessor_epoch_id
        AND c.controller_state = NEW.from_state AND NEW.to_state = 'SHOCKED_CLOSED'
        AND s.run_id = c.run_id AND s.fixture_id = c.fixture_id
        AND NEW.candidate_epoch_id IS NULL AND NEW.input_freshness_vector_id IS NULL
        AND NEW.resnapshot_proof_id IS NULL AND NEW.bindings_verified = 1
    ) THEN RAISE(ABORT, 'E_SHOCK_TRANSITION_BINDING')
    WHEN NEW.transition_reason = 'RESNAPSHOT_CANDIDATE_ACCEPTED' AND NOT EXISTS (
      SELECT 1 FROM coherence_controllers c
      JOIN coherence_epochs e ON e.coherence_epoch_id = NEW.candidate_epoch_id
      JOIN authoritative_resnapshot_proofs p ON p.authoritative_resnapshot_proof_id = NEW.resnapshot_proof_id
      JOIN input_freshness_vectors f ON f.input_freshness_vector_id = NEW.input_freshness_vector_id
      JOIN shock_observations s ON s.shock_observation_id = NEW.shock_observation_id
      JOIN clock_mappings fm ON fm.clock_mapping_id = p.football_mapping_id
      JOIN clock_mappings om ON om.clock_mapping_id = p.operator_mapping_id
      JOIN clock_mappings bm ON bm.clock_mapping_id = p.market_book_mapping_id
      JOIN reducer_cursors rc ON rc.reducer_cursor_id = p.continuity_reducer_cursor_id
      WHERE c.coherence_controller_id = NEW.coherence_controller_id
        AND c.fixture_id = NEW.fixture_id AND c.controller_state = 'WAITING_FOR_RESNAPSHOT'
        AND c.current_epoch_id = NEW.predecessor_epoch_id AND c.candidate_epoch_id IS NULL
        AND c.active_shock_observation_id = NEW.shock_observation_id
        AND NEW.candidate_epoch_id <> NEW.predecessor_epoch_id
        AND e.run_id = c.run_id AND e.fixture_id = c.fixture_id
        AND e.predecessor_epoch_id = NEW.predecessor_epoch_id
        AND e.opening_freshness_vector_id = NEW.input_freshness_vector_id
        AND e.opening_resnapshot_proof_id = NEW.resnapshot_proof_id
        AND e.predecessor_permanently_closed = 1
        AND p.run_id = c.run_id AND p.fixture_id = c.fixture_id
        AND p.proof_status = 'OBSERVED' AND p.proof_verified = 1
        AND p.predecessor_epoch_id = NEW.predecessor_epoch_id
        AND p.candidate_epoch_id = NEW.candidate_epoch_id
        AND p.shock_observation_id = NEW.shock_observation_id
        AND p.freshness_vector_id = NEW.input_freshness_vector_id
        AND p.accepted_capability_evidence_id IS NOT NULL
        AND p.predecessor_permanently_closed = 1
        AND p.candidate_distinct_from_predecessor = 1
        AND p.release_predicate = 'SATISFIED'
        AND p.mapping_bindings_hash IS NOT NULL AND p.continuity_bindings_hash IS NOT NULL
        AND f.run_id = c.run_id AND f.fixture_id = c.fixture_id
        AND f.football_state_status = 'FRESH' AND f.operator_state_status = 'FRESH' AND f.market_book_status = 'FRESH'
        AND s.run_id = c.run_id AND s.fixture_id = c.fixture_id
        AND fm.run_id = c.run_id AND fm.mapping_status = 'OPEN'
        AND om.run_id = c.run_id AND om.mapping_status = 'OPEN'
        AND bm.run_id = c.run_id AND bm.mapping_status = 'OPEN'
        AND NOT EXISTS (SELECT 1 FROM clock_mapping_closures mc WHERE mc.clock_mapping_id IN (fm.clock_mapping_id, om.clock_mapping_id, bm.clock_mapping_id))
        AND rc.run_id = c.run_id AND rc.generation = e.generation AND rc.cursor_hash_verified = 1
        AND NEW.bindings_verified = 1
    ) THEN RAISE(ABORT, 'E_RESNAPSHOT_CANDIDATE_BINDING')
    WHEN NEW.transition_reason = 'RELEASE_PREDICATE_SATISFIED' AND NOT EXISTS (
      SELECT 1 FROM coherence_controllers c
      JOIN coherence_epochs e ON e.coherence_epoch_id = NEW.candidate_epoch_id
      JOIN authoritative_resnapshot_proofs p ON p.authoritative_resnapshot_proof_id = NEW.resnapshot_proof_id
      JOIN input_freshness_vectors f ON f.input_freshness_vector_id = NEW.input_freshness_vector_id
      JOIN shock_observations s ON s.shock_observation_id = NEW.shock_observation_id
      JOIN clock_mappings fm ON fm.clock_mapping_id = p.football_mapping_id
      JOIN clock_mappings om ON om.clock_mapping_id = p.operator_mapping_id
      JOIN clock_mappings bm ON bm.clock_mapping_id = p.market_book_mapping_id
      JOIN reducer_cursors rc ON rc.reducer_cursor_id = p.continuity_reducer_cursor_id
      JOIN stream_generations cg ON cg.run_id = rc.run_id AND cg.browser_run_id = rc.browser_run_id
        AND cg.producer_id = rc.producer_id AND cg.stream_id = rc.stream_id AND cg.generation = rc.generation
      WHERE c.coherence_controller_id = NEW.coherence_controller_id
        AND c.fixture_id = NEW.fixture_id AND c.controller_state = 'NEW_EPOCH_PENDING'
        AND c.current_epoch_id = NEW.predecessor_epoch_id
        AND c.candidate_epoch_id = NEW.candidate_epoch_id
        AND c.active_shock_observation_id = NEW.shock_observation_id
        AND NEW.candidate_epoch_id <> NEW.predecessor_epoch_id
        AND e.run_id = c.run_id AND e.fixture_id = c.fixture_id
        AND e.predecessor_epoch_id = NEW.predecessor_epoch_id
        AND e.opening_freshness_vector_id = NEW.input_freshness_vector_id
        AND e.opening_resnapshot_proof_id = NEW.resnapshot_proof_id
        AND e.predecessor_permanently_closed = 1
        AND p.run_id = c.run_id AND p.fixture_id = c.fixture_id
        AND p.proof_status = 'OBSERVED' AND p.proof_verified = 1
        AND p.predecessor_epoch_id = NEW.predecessor_epoch_id
        AND p.candidate_epoch_id = NEW.candidate_epoch_id
        AND p.shock_observation_id = NEW.shock_observation_id
        AND p.freshness_vector_id = NEW.input_freshness_vector_id
        AND p.accepted_capability_evidence_id IS NOT NULL
        AND p.predecessor_permanently_closed = 1
        AND p.candidate_distinct_from_predecessor = 1
        AND p.release_predicate = 'SATISFIED'
        AND p.mapping_bindings_hash IS NOT NULL AND p.continuity_bindings_hash IS NOT NULL
        AND f.run_id = c.run_id AND f.fixture_id = c.fixture_id
        AND f.football_state_status = 'FRESH' AND f.operator_state_status = 'FRESH' AND f.market_book_status = 'FRESH'
        AND s.run_id = c.run_id AND s.fixture_id = c.fixture_id
        AND fm.run_id = c.run_id AND fm.mapping_status = 'OPEN'
        AND om.run_id = c.run_id AND om.mapping_status = 'OPEN'
        AND bm.run_id = c.run_id AND bm.mapping_status = 'OPEN'
        AND NOT EXISTS (SELECT 1 FROM clock_mapping_closures mc WHERE mc.clock_mapping_id IN (fm.clock_mapping_id, om.clock_mapping_id, bm.clock_mapping_id))
        AND rc.run_id = c.run_id AND rc.generation = e.generation AND rc.cursor_hash_verified = 1
        AND cg.generation_state = 'ACTIVE'
        AND NEW.bindings_verified = 1
    ) THEN RAISE(ABORT, 'E_RELEASE_BINDING')
  END;
END;

CREATE TRIGGER authoritative_resnapshot_proof_binding_guard
BEFORE INSERT ON authoritative_resnapshot_proofs
WHEN NEW.proof_status = 'OBSERVED'
BEGIN
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1
    FROM coherence_epochs candidate
    JOIN coherence_epochs predecessor ON predecessor.coherence_epoch_id = NEW.predecessor_epoch_id
    JOIN input_freshness_vectors f ON f.input_freshness_vector_id = NEW.freshness_vector_id
    JOIN shock_observations s ON s.shock_observation_id = NEW.shock_observation_id
    JOIN clock_mappings fm ON fm.clock_mapping_id = NEW.football_mapping_id
    JOIN clock_mappings om ON om.clock_mapping_id = NEW.operator_mapping_id
    JOIN clock_mappings bm ON bm.clock_mapping_id = NEW.market_book_mapping_id
    JOIN reducer_cursors rc ON rc.reducer_cursor_id = NEW.continuity_reducer_cursor_id
    JOIN coherence_transitions close_t ON close_t.predecessor_epoch_id = predecessor.coherence_epoch_id
      AND close_t.shock_observation_id = s.shock_observation_id
      AND close_t.to_state = 'SHOCKED_CLOSED'
      AND close_t.transition_reason = 'SHOCK_ATOMIC_CLOSE'
      AND close_t.bindings_verified = 1
    WHERE candidate.coherence_epoch_id = NEW.candidate_epoch_id
      AND candidate.coherence_epoch_id <> predecessor.coherence_epoch_id
      AND candidate.predecessor_epoch_id = predecessor.coherence_epoch_id
      AND candidate.predecessor_permanently_closed = 1
      AND candidate.opening_freshness_vector_id = NEW.freshness_vector_id
      AND candidate.opening_resnapshot_proof_id = NEW.authoritative_resnapshot_proof_id
      AND candidate.run_id = NEW.run_id AND predecessor.run_id = NEW.run_id
      AND f.run_id = NEW.run_id AND s.run_id = NEW.run_id
      AND f.football_state_status = 'FRESH' AND f.operator_state_status = 'FRESH' AND f.market_book_status = 'FRESH'
      AND fm.run_id = NEW.run_id AND fm.mapping_status = 'OPEN'
      AND om.run_id = NEW.run_id AND om.mapping_status = 'OPEN'
      AND bm.run_id = NEW.run_id AND bm.mapping_status = 'OPEN'
      AND NOT EXISTS (SELECT 1 FROM clock_mapping_closures mc WHERE mc.clock_mapping_id IN (fm.clock_mapping_id, om.clock_mapping_id, bm.clock_mapping_id))
      AND rc.run_id = NEW.run_id AND rc.cursor_hash_verified = 1
      AND rc.generation = candidate.generation
      AND candidate.fixture_id = NEW.fixture_id AND predecessor.fixture_id = NEW.fixture_id
      AND f.fixture_id = NEW.fixture_id AND s.fixture_id = NEW.fixture_id
      AND NEW.proof_verified = 1 AND NEW.predecessor_permanently_closed = 1
      AND NEW.candidate_distinct_from_predecessor = 1
      AND NEW.mapping_bindings_hash IS NOT NULL AND NEW.continuity_bindings_hash IS NOT NULL
      AND NEW.release_predicate = 'SATISFIED'
  ) THEN RAISE(ABORT, 'E_RESNAPSHOT_PROOF_BINDING') END;
END;

CREATE TRIGGER coherence_controllers_no_delete
BEFORE DELETE ON coherence_controllers BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_DELETE'); END;

CREATE TRIGGER authorization_consumption_binding_guard
BEFORE INSERT ON authorization_consumptions
BEGIN
  SELECT CASE WHEN
    (NEW.gate_kind IS 'EVIDENCE_EXPORT_ACCEPTED'
     OR NEW.receipt_scope IS 'WHOLE_RUN_DESTRUCTION_AFTER_ACCEPTED_EXPORT'
     OR NEW.destruction_intent_id IS NOT NULL
     OR NEW.precommitted_destruction_intent_content_hash IS NOT NULL
     OR NEW.staged_pre_delete_inventory_hash IS NOT NULL
     OR NEW.staged_intent_created_at IS NOT NULL
     OR NEW.intent_authorization_id IS NOT NULL
     OR NEW.intent_consumption_id IS NOT NULL
     OR NEW.intent_run_id IS NOT NULL
     OR NEW.receipt_bound_run_id IS NOT NULL
     OR NEW.accepted_sanitized_export_manifest_hash IS NOT NULL
     OR NEW.receipt_bound_sanitized_export_manifest_hash IS NOT NULL
     OR NEW.intent_receipt_content_hash IS NOT NULL
     OR NEW.explicit_human_invocation IS NOT NULL
     OR NEW.consumption_commit_state IS 'COMMITTED_BEFORE_WHOLE_RUN_DESTRUCTION')
    AND (NEW.receipt_record_type IS NOT 'GateReceipt'
         OR NEW.gate_kind IS NOT 'EVIDENCE_EXPORT_ACCEPTED')
    THEN RAISE(ABORT, 'E_DESTRUCTION_AUTHORITY_TYPE') END;
  SELECT CASE WHEN NEW.receipt_record_type IS 'GateReceipt'
                    AND NEW.gate_kind IS 'EVIDENCE_EXPORT_ACCEPTED'
                    AND NEW.receipt_schema_version IS NOT 'gate-receipt/v1'
    THEN RAISE(ABORT, 'E_DESTRUCTION_AUTHORITY_TYPE') END;
  SELECT CASE WHEN NEW.receipt_record_type IS 'GateReceipt'
                    AND NEW.gate_kind IS 'EVIDENCE_EXPORT_ACCEPTED'
                    AND NEW.receipt_scope IS NOT 'WHOLE_RUN_DESTRUCTION_AFTER_ACCEPTED_EXPORT'
    THEN RAISE(ABORT, 'E_DESTRUCTION_AUTHORITY_SCOPE') END;
  SELECT CASE WHEN NEW.receipt_record_type IS 'GateReceipt'
                    AND NEW.gate_kind IS 'EVIDENCE_EXPORT_ACCEPTED'
                    AND (NEW.intent_run_id IS NOT NEW.run_id
                         OR NEW.receipt_bound_run_id IS NOT NEW.run_id
                         OR length(NEW.run_id) <> 36
                         OR substr(NEW.run_id, 9, 1) <> '-'
                         OR substr(NEW.run_id, 14, 1) <> '-'
                         OR substr(NEW.run_id, 19, 1) <> '-'
                         OR substr(NEW.run_id, 24, 1) <> '-'
                         OR length(replace(NEW.run_id, '-', '')) <> 32
                         OR replace(NEW.run_id, '-', '') GLOB '*[^0-9a-f]*'
                         OR substr(NEW.run_id, 15, 1) <> '4'
                         OR substr(NEW.run_id, 20, 1) NOT IN ('8', '9', 'a', 'b'))
    THEN RAISE(ABORT, 'E_DESTRUCTION_AUTHORITY_RUN') END;
  SELECT CASE WHEN NEW.receipt_record_type IS 'GateReceipt'
                    AND NEW.gate_kind IS 'EVIDENCE_EXPORT_ACCEPTED'
                    AND (NEW.destruction_intent_id IS NULL
                         OR NEW.receipt_id IS NULL
                         OR NEW.intent_authorization_id IS NULL
                         OR NEW.intent_authorization_id IS NOT NEW.receipt_id
                         OR NEW.consumption_id IS NULL
                         OR NEW.intent_consumption_id IS NULL
                         OR NEW.intent_consumption_id IS NOT NEW.consumption_id
                         OR instr(NEW.destruction_intent_id, ':') < 2
                         OR length(NEW.destruction_intent_id) - instr(NEW.destruction_intent_id, ':') <> 64
                         OR substr(NEW.destruction_intent_id, 1, 1) NOT GLOB '[A-Z]'
                         OR substr(NEW.destruction_intent_id, 1, instr(NEW.destruction_intent_id, ':') - 1) GLOB '*[^A-Z0-9_]*'
                         OR substr(NEW.destruction_intent_id, instr(NEW.destruction_intent_id, ':') + 1) GLOB '*[^0-9a-f]*'
                         OR instr(NEW.consumption_id, ':') < 2
                         OR length(NEW.consumption_id) - instr(NEW.consumption_id, ':') <> 64
                         OR substr(NEW.consumption_id, 1, 1) NOT GLOB '[A-Z]'
                         OR substr(NEW.consumption_id, 1, instr(NEW.consumption_id, ':') - 1) GLOB '*[^A-Z0-9_]*'
                         OR substr(NEW.consumption_id, instr(NEW.consumption_id, ':') + 1) GLOB '*[^0-9a-f]*'
                         OR length(NEW.receipt_id) <> 36
                         OR substr(NEW.receipt_id, 9, 1) <> '-'
                         OR substr(NEW.receipt_id, 14, 1) <> '-'
                         OR substr(NEW.receipt_id, 19, 1) <> '-'
                         OR substr(NEW.receipt_id, 24, 1) <> '-'
                         OR length(replace(NEW.receipt_id, '-', '')) <> 32
                         OR replace(NEW.receipt_id, '-', '') GLOB '*[^0-9a-f]*'
                         OR substr(NEW.receipt_id, 15, 1) <> '4'
                         OR substr(NEW.receipt_id, 20, 1) NOT IN ('8', '9', 'a', 'b'))
    THEN RAISE(ABORT, 'E_DESTRUCTION_AUTHORITY_ID') END;
  SELECT CASE WHEN NEW.receipt_record_type IS 'GateReceipt'
                    AND NEW.gate_kind IS 'EVIDENCE_EXPORT_ACCEPTED'
                    AND (NEW.precommitted_destruction_intent_content_hash IS NULL
                         OR length(NEW.precommitted_destruction_intent_content_hash) <> 64
                         OR NEW.precommitted_destruction_intent_content_hash GLOB '*[^0-9a-f]*'
                         OR NEW.staged_pre_delete_inventory_hash IS NULL
                         OR length(NEW.staged_pre_delete_inventory_hash) <> 64
                         OR NEW.staged_pre_delete_inventory_hash GLOB '*[^0-9a-f]*'
                         OR NEW.staged_intent_created_at IS NULL
                         OR length(NEW.staged_intent_created_at) <> 27
                         OR NEW.staged_intent_created_at NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9][0-9][0-9][0-9]Z'
                         OR substr(NEW.staged_intent_created_at, 6, 2) NOT BETWEEN '01' AND '12'
                         OR substr(NEW.staged_intent_created_at, 9, 2) NOT BETWEEN '01' AND '31'
                         OR substr(NEW.staged_intent_created_at, 12, 2) NOT BETWEEN '00' AND '23'
                         OR substr(NEW.staged_intent_created_at, 15, 2) NOT BETWEEN '00' AND '59'
                         OR substr(NEW.staged_intent_created_at, 18, 2) NOT BETWEEN '00' AND '59')
    THEN RAISE(ABORT, 'E_DESTRUCTION_INTENT_PRECOMMIT') END;
  SELECT CASE WHEN NEW.receipt_record_type IS 'GateReceipt'
                    AND NEW.gate_kind IS 'EVIDENCE_EXPORT_ACCEPTED'
                    AND (NEW.receipt_bound_sanitized_export_manifest_hash IS NOT NEW.accepted_sanitized_export_manifest_hash
                         OR NEW.accepted_sanitized_export_manifest_hash IS NULL
                         OR NEW.receipt_bound_sanitized_export_manifest_hash IS NULL
                         OR length(NEW.accepted_sanitized_export_manifest_hash) <> 64
                         OR NEW.accepted_sanitized_export_manifest_hash GLOB '*[^0-9a-f]*'
                         OR length(NEW.receipt_bound_sanitized_export_manifest_hash) <> 64
                         OR NEW.receipt_bound_sanitized_export_manifest_hash GLOB '*[^0-9a-f]*'
                         OR NEW.receipt_content_hash IS NULL
                         OR NEW.intent_receipt_content_hash IS NULL
                         OR NEW.intent_receipt_content_hash IS NOT NEW.receipt_content_hash
                         OR length(NEW.receipt_content_hash) <> 64
                         OR NEW.receipt_content_hash GLOB '*[^0-9a-f]*'
                         OR length(NEW.intent_receipt_content_hash) <> 64
                         OR NEW.intent_receipt_content_hash GLOB '*[^0-9a-f]*')
    THEN RAISE(ABORT, 'E_DESTRUCTION_AUTHORITY_HASH') END;
  SELECT CASE WHEN NEW.receipt_record_type IS 'GateReceipt'
                    AND NEW.gate_kind IS 'EVIDENCE_EXPORT_ACCEPTED'
                    AND (NEW.gate_result IS NOT 'PASS'
                         OR NEW.signature_algorithm IS NOT 'Ed25519'
                         OR NEW.signature IS NULL
                         OR length(NEW.signature) <> 86
                         OR NEW.signature GLOB '*[^A-Za-z0-9_-]*'
                         OR NEW.receipt_verification_state IS NOT 'CANONICAL_BYTES_CONTENT_HASH_AND_ED25519_SIGNATURE_VERIFIED'
                         OR NEW.one_use IS NOT 1
                         OR NEW.declared_use_semantics IS NOT 'SINGLE_USE'
                         OR NEW.consumed_before IS NOT 'ATOMIC_LEDGER_COMMIT_BEFORE_WHOLE_RUN_DESTRUCTION'
                         OR NEW.consumption_commit_state IS NOT 'COMMITTED_BEFORE_WHOLE_RUN_DESTRUCTION'
                         OR NEW.serial IS NULL
                         OR length(NEW.serial) NOT BETWEEN 8 AND 64
                         OR substr(NEW.serial, 1, 1) NOT GLOB '[A-Z0-9]'
                         OR NEW.serial GLOB '*[^A-Z0-9_-]*'
                         OR NEW.nonce IS NULL
                         OR length(NEW.nonce) <> 43
                         OR NEW.nonce GLOB '*[^A-Za-z0-9_-]*'
                         OR NEW.issuer IS NULL
                         OR NEW.issuer_key_id IS NULL
                         OR NEW.audience IS NULL
                         OR NEW.scope_binding_hash IS NULL
                         OR NEW.verifier_clock_domain_id IS NULL
                         OR NEW.verifier_boot_id IS NULL
                         OR NEW.verifier_clock_unit IS NOT 'MICROSECOND'
                         OR NEW.verifier_monotonic_value IS NULL
                         OR NEW.verifier_monotonic_value < 0
                         OR NEW.verifier_clock_resolution_us IS NULL
                         OR NEW.verifier_clock_resolution_us < 1
                         OR NEW.consumed_at_us IS NULL
                         OR NEW.consumed_at_us < 0)
    THEN RAISE(ABORT, 'E_DESTRUCTION_AUTHORITY_UNVERIFIED') END;
  SELECT CASE WHEN NEW.receipt_record_type IS 'GateReceipt'
                    AND NEW.gate_kind IS 'EVIDENCE_EXPORT_ACCEPTED'
                    AND NEW.explicit_human_invocation IS NOT 1
    THEN RAISE(ABORT, 'E_DESTRUCTION_HUMAN_INVOCATION_REQUIRED') END;
  SELECT CASE WHEN NEW.receipt_record_type IS 'GateReceipt'
                    AND NEW.gate_kind IS 'EVIDENCE_EXPORT_ACCEPTED'
                    AND NOT EXISTS (
    SELECT 1 FROM run_meta r
    WHERE r.run_id = NEW.run_id AND r.run_status = 'CLOSED'
  ) THEN RAISE(ABORT, 'E_DESTRUCTION_RUN_NOT_CLOSED') END;
  SELECT CASE WHEN
    (NEW.receipt_record_type IS 'DiscoveryRunAuthorization'
     AND (NEW.receipt_schema_version IS NOT 'discovery-run-authorization/v1'
          OR NEW.receipt_scope IS NOT 'AUTHENTICATED_PASSIVE_DISCOVERY'
          OR NEW.consumed_before IS NOT 'ATOMIC_LEDGER_COMMIT_BEFORE_DEBUGGER_ATTACH'))
    OR
    (NEW.receipt_record_type IS 'BodyClassApproval'
     AND (NEW.receipt_schema_version IS NOT 'body-class-approval/v1'
          OR NEW.receipt_scope IS NOT 'TEST_ONLY_APPROVED_INBOUND_BODY_CLASS'
          OR NEW.consumed_before IS NOT 'ATOMIC_LEDGER_COMMIT_BEFORE_BODY_TICKET_CREATION'))
    OR
    (NEW.receipt_record_type IS 'ProviderCallAuthorization'
     AND (NEW.receipt_schema_version IS NOT 'provider-call-authorization/v1'
          OR NEW.receipt_scope IS NOT 'ONE_PROVIDER_FEASIBILITY_GET'
          OR NEW.consumed_before IS NOT 'ATOMIC_LEDGER_COMMIT_BEFORE_PROVIDER_IO'))
    OR
    (NEW.receipt_record_type IS 'GateReceipt'
     AND NEW.gate_kind IS NOT 'EVIDENCE_EXPORT_ACCEPTED'
     AND (NEW.receipt_schema_version IS NOT 'gate-receipt/v1'
          OR NEW.gate_kind NOT IN ('REPO0_BASELINE_ACCEPTED', 'R0_REPAIR_ACCEPTED', 'F0A_FOUNDATION_ACCEPTED', 'DISCOVERY_SECURITY_ACCEPTED', 'OPERATOR_DISCOVERY_ACCEPTED', 'PROVIDER_FEASIBILITY_ACCEPTED', 'DISCOVERY_EVIDENCE_ACCEPTED', 'SCOPE0_FROZEN')
          OR NEW.receipt_scope IS NOT 'IMPLEMENTATION_GATE_ONLY'
          OR NEW.consumed_before IS NOT 'ATOMIC_LEDGER_COMMIT_BEFORE_GATE_USE'))
    THEN RAISE(ABORT, 'E_AUTHORIZATION_CONSUMPTION_BINDING') END;
  SELECT CASE WHEN NEW.receipt_record_type IS 'GateReceipt'
                    AND NEW.gate_kind IS 'EVIDENCE_EXPORT_ACCEPTED'
                    AND EXISTS (
    SELECT 1 FROM authorization_consumptions used
    WHERE used.receipt_id = NEW.receipt_id
       OR (used.issuer = NEW.issuer
           AND used.issuer_key_id = NEW.issuer_key_id
           AND used.audience = NEW.audience
           AND used.serial = NEW.serial)
       OR (used.issuer = NEW.issuer
           AND used.issuer_key_id = NEW.issuer_key_id
           AND used.audience = NEW.audience
           AND used.scope_binding_hash = NEW.scope_binding_hash
           AND used.nonce = NEW.nonce)
       OR used.receipt_content_hash = NEW.receipt_content_hash
  ) THEN RAISE(ABORT, 'E_DESTRUCTION_AUTHORITY_REPLAY') END;
  SELECT CASE WHEN NOT (NEW.receipt_record_type IS 'GateReceipt'
                        AND NEW.gate_kind IS 'EVIDENCE_EXPORT_ACCEPTED')
                    AND EXISTS (
    SELECT 1 FROM authorization_consumptions used
    WHERE used.receipt_id = NEW.receipt_id
       OR (used.issuer = NEW.issuer
           AND used.issuer_key_id = NEW.issuer_key_id
           AND used.audience = NEW.audience
           AND used.serial = NEW.serial)
       OR (used.issuer = NEW.issuer
           AND used.issuer_key_id = NEW.issuer_key_id
           AND used.audience = NEW.audience
           AND used.scope_binding_hash = NEW.scope_binding_hash
           AND used.nonce = NEW.nonce)
       OR used.receipt_content_hash = NEW.receipt_content_hash
  ) THEN RAISE(ABORT, 'E_AUTHORIZATION_REPLAY') END;
END;

CREATE TRIGGER revocation_chain_guard
BEFORE INSERT ON revocations
BEGIN
  SELECT CASE WHEN
    NEW.checkpoint_sequence <> NEW.revocation_sequence
    OR NEW.checkpoint_head_hash <> NEW.revocation_hash
    OR NEW.signature_algorithm <> 'Ed25519'
    OR NEW.verification_state <> 'CANONICAL_BYTES_CONTENT_HASH_ED25519_TRUST_AND_CHAIN_VERIFIED'
    OR length(NEW.effective_at_utc) <> 27
    OR NEW.effective_at_utc NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9][0-9][0-9][0-9]Z'
  THEN RAISE(ABORT, 'E_REVOCATION_UNVERIFIED') END;
  SELECT CASE WHEN NEW.revocation_sequence = 1 AND EXISTS (
    SELECT 1 FROM revocations prior WHERE prior.ledger_id = NEW.ledger_id
  ) THEN RAISE(ABORT, 'E_REVOCATION_SEQUENCE') END;
  SELECT CASE WHEN NEW.revocation_sequence > 1 AND NOT EXISTS (
    SELECT 1 FROM revocations prior
    WHERE prior.ledger_id = NEW.ledger_id
      AND prior.revocation_sequence = NEW.revocation_sequence - 1
      AND prior.revocation_hash = NEW.previous_revocation_hash
  ) THEN RAISE(ABORT, 'E_REVOCATION_CHAIN') END;
END;

CREATE TRIGGER run_meta_update_guard
BEFORE UPDATE ON run_meta
BEGIN
  SELECT CASE WHEN OLD.run_status = 'CLOSED'
                    AND NEW.run_status = 'DESTRUCTION_PENDING'
                    AND NOT EXISTS (
                      SELECT 1 FROM authorization_consumptions consumed
                      WHERE consumed.run_id = OLD.run_id
                        AND consumed.receipt_record_type = 'GateReceipt'
                        AND consumed.receipt_schema_version = 'gate-receipt/v1'
                        AND consumed.gate_kind = 'EVIDENCE_EXPORT_ACCEPTED'
                        AND consumed.gate_result = 'PASS'
                        AND consumed.destruction_intent_id IS NOT NULL
                        AND consumed.precommitted_destruction_intent_content_hash IS NOT NULL
                        AND consumed.staged_pre_delete_inventory_hash IS NOT NULL
                        AND consumed.staged_intent_created_at IS NOT NULL
                        AND consumed.intent_authorization_id = consumed.receipt_id
                        AND consumed.intent_consumption_id = consumed.consumption_id
                        AND consumed.intent_run_id = OLD.run_id
                        AND consumed.receipt_scope = 'WHOLE_RUN_DESTRUCTION_AFTER_ACCEPTED_EXPORT'
                        AND consumed.receipt_bound_run_id = OLD.run_id
                        AND consumed.accepted_sanitized_export_manifest_hash IS NOT NULL
                        AND consumed.receipt_bound_sanitized_export_manifest_hash IS NOT NULL
                        AND consumed.receipt_bound_sanitized_export_manifest_hash = consumed.accepted_sanitized_export_manifest_hash
                        AND consumed.receipt_content_hash IS NOT NULL
                        AND consumed.intent_receipt_content_hash IS NOT NULL
                        AND consumed.intent_receipt_content_hash = consumed.receipt_content_hash
                        AND consumed.signature_algorithm = 'Ed25519'
                        AND consumed.signature IS NOT NULL
                        AND consumed.receipt_verification_state = 'CANONICAL_BYTES_CONTENT_HASH_AND_ED25519_SIGNATURE_VERIFIED'
                        AND consumed.one_use = 1
                        AND consumed.declared_use_semantics = 'SINGLE_USE'
                        AND consumed.consumed_before = 'ATOMIC_LEDGER_COMMIT_BEFORE_WHOLE_RUN_DESTRUCTION'
                        AND consumed.consumption_commit_state = 'COMMITTED_BEFORE_WHOLE_RUN_DESTRUCTION'
                        AND consumed.explicit_human_invocation = 1
                    )
    THEN RAISE(ABORT, 'E_DESTRUCTION_AUTHORITY_REQUIRED') END;
  SELECT CASE WHEN
    NEW.run_id <> OLD.run_id OR NEW.schema_version <> OLD.schema_version OR
    NEW.authorization_id <> OLD.authorization_id OR NEW.pack_hash <> OLD.pack_hash OR
    NEW.build_hash <> OLD.build_hash OR NEW.created_at_us <> OLD.created_at_us OR
    NOT ((OLD.run_status = 'OPEN' AND NEW.run_status = 'CLOSED') OR
         (OLD.run_status = 'CLOSED' AND NEW.run_status = 'DESTRUCTION_PENDING'))
  THEN RAISE(ABORT, 'E_INVALID_RUN_MUTATION') END;
END;

CREATE TRIGGER run_meta_no_delete
BEFORE DELETE ON run_meta BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_DELETE'); END;

CREATE TRIGGER authorization_consumptions_no_update BEFORE UPDATE ON authorization_consumptions BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_UPDATE'); END;
CREATE TRIGGER authorization_consumptions_no_delete BEFORE DELETE ON authorization_consumptions BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_DELETE'); END;
CREATE TRIGGER revocations_no_update BEFORE UPDATE ON revocations BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_UPDATE'); END;
CREATE TRIGGER revocations_no_delete BEFORE DELETE ON revocations BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_DELETE'); END;
CREATE TRIGGER raw_commits_no_update BEFORE UPDATE ON raw_commits BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_UPDATE'); END;
CREATE TRIGGER raw_commits_no_delete BEFORE DELETE ON raw_commits BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_DELETE'); END;
CREATE TRIGGER raw_conflicts_no_update BEFORE UPDATE ON raw_conflicts BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_UPDATE'); END;
CREATE TRIGGER raw_conflicts_no_delete BEFORE DELETE ON raw_conflicts BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_DELETE'); END;
CREATE TRIGGER application_records_no_update BEFORE UPDATE ON application_records BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_UPDATE'); END;
CREATE TRIGGER application_records_no_delete BEFORE DELETE ON application_records BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_DELETE'); END;
CREATE TRIGGER derived_revisions_no_update BEFORE UPDATE ON derived_revisions BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_UPDATE'); END;
CREATE TRIGGER derived_revisions_no_delete BEFORE DELETE ON derived_revisions BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_DELETE'); END;
CREATE TRIGGER reducer_cursors_no_update BEFORE UPDATE ON reducer_cursors BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_UPDATE'); END;
CREATE TRIGGER reducer_cursors_no_delete BEFORE DELETE ON reducer_cursors BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_DELETE'); END;
CREATE TRIGGER ack_outbox_no_update BEFORE UPDATE ON ack_outbox BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_UPDATE'); END;
CREATE TRIGGER ack_outbox_no_delete BEFORE DELETE ON ack_outbox BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_DELETE'); END;
CREATE TRIGGER ack_cursors_no_update BEFORE UPDATE ON ack_cursors BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_UPDATE'); END;
CREATE TRIGGER ack_cursors_no_delete BEFORE DELETE ON ack_cursors BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_DELETE'); END;
CREATE TRIGGER gap_records_no_update BEFORE UPDATE ON gap_records BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_UPDATE'); END;
CREATE TRIGGER gap_records_no_delete BEFORE DELETE ON gap_records BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_DELETE'); END;
CREATE TRIGGER gap_epoch_bindings_no_update BEFORE UPDATE ON gap_epoch_bindings BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_UPDATE'); END;
CREATE TRIGGER gap_epoch_bindings_no_delete BEFORE DELETE ON gap_epoch_bindings BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_DELETE'); END;
CREATE TRIGGER generation_transitions_no_update BEFORE UPDATE ON generation_transitions BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_UPDATE'); END;
CREATE TRIGGER generation_transitions_no_delete BEFORE DELETE ON generation_transitions BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_DELETE'); END;
CREATE TRIGGER clock_observations_no_update BEFORE UPDATE ON clock_observations BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_UPDATE'); END;
CREATE TRIGGER clock_observations_no_delete BEFORE DELETE ON clock_observations BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_DELETE'); END;
CREATE TRIGGER clock_mappings_no_update BEFORE UPDATE ON clock_mappings BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_UPDATE'); END;
CREATE TRIGGER clock_mappings_no_delete BEFORE DELETE ON clock_mappings BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_DELETE'); END;
CREATE TRIGGER clock_mapping_closures_no_update BEFORE UPDATE ON clock_mapping_closures BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_UPDATE'); END;
CREATE TRIGGER clock_mapping_closures_no_delete BEFORE DELETE ON clock_mapping_closures BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_DELETE'); END;
CREATE TRIGGER shock_observations_no_update BEFORE UPDATE ON shock_observations BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_UPDATE'); END;
CREATE TRIGGER shock_observations_no_delete BEFORE DELETE ON shock_observations BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_DELETE'); END;
CREATE TRIGGER coherence_epochs_no_update BEFORE UPDATE ON coherence_epochs BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_UPDATE'); END;
CREATE TRIGGER coherence_epochs_no_delete BEFORE DELETE ON coherence_epochs BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_DELETE'); END;
CREATE TRIGGER coherence_transitions_no_update BEFORE UPDATE ON coherence_transitions BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_UPDATE'); END;
CREATE TRIGGER coherence_transitions_no_delete BEFORE DELETE ON coherence_transitions BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_DELETE'); END;
CREATE TRIGGER input_freshness_vectors_no_update BEFORE UPDATE ON input_freshness_vectors BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_UPDATE'); END;
CREATE TRIGGER input_freshness_vectors_no_delete BEFORE DELETE ON input_freshness_vectors BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_DELETE'); END;
CREATE TRIGGER authoritative_resnapshot_proofs_no_update BEFORE UPDATE ON authoritative_resnapshot_proofs BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_UPDATE'); END;
CREATE TRIGGER authoritative_resnapshot_proofs_no_delete BEFORE DELETE ON authoritative_resnapshot_proofs BEGIN SELECT RAISE(ABORT, 'E_IMMUTABLE_DELETE'); END;
