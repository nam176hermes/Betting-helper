# Typed live contracts, storage, transport and replay

## Source boundaries
Part A's synthetic `RawObservation` and `Spool` contract stays closed. New `BH_LIVE_READONLY_V1` events never masquerade as synthetic TERMINAL observations. Live field contract and SQLite DDL in `assets/contracts/live_readonly/v1/` are owned by PB-01/PB-07; old vendor is not changed. This explicit feature expansion must pass new tests; an old offline PASS is not a live receipt.

## Core records (exact fields, unknowns explicit)
The supplied JSON schemas are the serialization authority; this table explains meanings.

### FixtureBinding
`binding_id`, `revision`, `provider_fixture_id`, `league_id`, `season`, `kickoff_utc`, `home_id`, `away_id`, `home_name`, `away_name`, `operator_fixture_id`, `operator_home_id`, `operator_away_id`, `operator_match_url`, `livescore_match_url` nullable, `orientation_status`, `evidence_hashes`.
IDs come from admitted evidence, not guessed team name hash. URLs are exact verified routes without query secrets; raw route with token is rejected, not stored. Dates/competition/participants must agree before binding is VERIFIED. Neutral venues do not swap semantic home/away. API IDs remain stable as provider identity, but binding revision changes when observed schedule/participant facts change.

### ProviderState
`fixture_id`, `observed_at_utc`, `received_mono_us`, `clock_domain_id`, `request_id`, `batch_observation_id`, `content_revision`, `status_code`, `period`, `elapsed_minute`, `extra_minute`, `clock_precision`, `kickoff_utc`, `home_id`, `away_id`, `home_name`, `away_name`, `score_current`, `score_ht`, `score_ft`, `events`, `events_status`, `section_availability`, `red_card_state`, `provider_updated_at` nullable, `quality_flags`.
Clock precision is MINUTE or UNKNOWN, never an extrapolated source-confirmed second. `fixture.timestamp` is kickoff[A3], not `provider_updated_at`. Null score is missing, not0. `observed_at` advances on a successful fresh HTTP response; content_revision advances only on semantic change. Both facts are retained. HTTP Date is a server response timestamp, not event occurrence time.

### MarketBook
`binding_id`, `binding_revision`, `operator_fixture_id`, `market_id`, `horizon` H1/H2/FT, `settlement_basis` NORMAL_TIME_INCLUDING_STOPPAGE or UNSUPPORTED, `selections` exactly HOME/DRAW/AWAY with selection_id and decimal odds string, `market_status`, `capture_revision`, `native_revision` nullable, `observed_at_utc`, `browser_mono_us`, `clock_domain_id`, `source_updated_at` nullable, `operator_score` nullable, `operator_period` nullable, `capture_evidence_tier`, `profile_hash`, `document_epoch`, `quality_flags`.
No implied probabilities in Part B. Decimal strings >1, finite, max precision6; unsupported/ambiguous price format rejects. No merging HOME at T0 with AWAY at T1 to create a current book. Complete visible DOM snapshot can be DISPLAY_COHERENT, never automatically NATIVE_ATOMIC.

### LiveEvent envelope
`protocol`, `run_id`, `source_kind` PROVIDER/OPERATOR/CONTROL, `stream_id`, `generation`, `sequence`, `observation_id`, `observed_at_utc`, `received_mono_us`, `payload_type`, `payload`, `previous_hash`, `content_hash`.
Payload is a closed union of ProviderState, MarketBook, BindingChange, HealthChange. No generic payload dictionary. Per-source stream sequence independent; backend receive index gives deterministic arrival order for cross-source replay, not alleged real-world chronology. `CONTROL` only the closed state transitions/health events; no shell/CDP/network command.

## Reuse policy
Extract only low-level IDB transaction completion/copy/compare-and-write utilities as `extension/src/storage/durable_idb.ts`. Existing Part A Spool still invokes its existing schema/canonical logic and keeps API and DB namespace. `LiveCaptureSpool` adds a new namespace and validates a live envelope on append/readback; test-only brand cannot authorize write. Do not generalize old allowlists to accept any JSON.
Backend `LiveStore` writes one new append-only typed live journal and projection. New DDL is not a test shortcut around RunStore. It represents real multi-fixture semantics that the old singleton-coherence RunStore did not own. Numerical/cursor methods and independent actual-state testing principles remain shared. Add source impact report and rerun Part A if shared code changes.

## SQLite persistence
`assets/contracts/live_readonly/v1/live-store.sql` creates run_meta, live_events, stream_cursors, projection_versions, request_links, run_closures. Every source event transaction:
1. Validate canonical live envelope, run/binding/source scope, seq and hash before insert.
2. `BEGIN IMMEDIATE`; check existing position; identical bytes duplicate=return prior post-commit receipt; different bytes=conflict, freeze source and append control evidence via backend control stream.
3. Insert actual canonical payload and hash, advance per-stream contiguous cursor, compute read model by pure reducer, insert projection revision, link request ID where appropriate; COMMIT.
4. Emit transport ACK only after commit and canonical payload exists in live_events. No external blob store needed for normalized records<=64KiB.
5. Forward sequence gap: do not ACK missing data. Record source health GAP on backend control stream, suspend that capture stream; source may resend exact missing frames after reconnect only in same document/run context. New document requires generation/binding review; never grant current market by a timer alone.
Store JSON canonical payload bytes, not only hashes. API response extras not retained; sanitized field projection is the replay input. Event content hashes use `BH-LIVE-READONLY/Event/v1\0`+JCS excluding onlycontent_hash. Initial previous_hash=64 zeros in this new protocol, not a replacement for old H0. Hash chain per source; backend receive_index is strictly increasing.
SQLite DELETE journal, FULL synchronous, foreign_keys ON, trusted_schema OFF; live dir0700/db0600 on WSL ext4; no automatic archival/deletion/backup.512MiB run cap (engineering bound), at cap stop source intake visibly and preserve evidence. No claims against power loss beyond tested filesystem/hardware.

## Live wire and pairing
Use existing locked websockets library and native browser WebSocket. New path`/live` on127.0.0.1:8765; offline listener must be stopped first. Exact Host and extension Origin; max_frame=262144, queue8, max2 sockets; one extension-service-worker producer multiplexes<=5 fixture streams. No LAN/0.0.0.0 binding.
Reuse canonical MAC/handshake implementation only by an explicit parameterized core with fixed protocol/domain enum OFFLINE/LIVE, never arbitrary domain input. New live messages/domain cannot be accepted by offline server. Live HMAC preimage `BH-LIVE-WIRE/v1\0`+JCS(frame withoutmac). Fields protocol/session_id/direction/counter/message_type/body/mac; each body has a closed schema.
HELLO/WELCOME/READY/READY_ACK bind nonce/run/role. Operator manually pastes a one-time **local pairing secret**, never API key, from host terminal into extension pairing page. Secret random32bytes, expires120s until consumed, run lease<=120min. Extension holds it only in service-worker memory/storage.session, never page or account data. It authenticates the local process, not the remote operator.
Allowed producer messages: CAPTURE_BATCH (live operator envelopes only,1..32), HEALTH, PING, STOP_CAPTURE. Backend messages: ACK (source/generation/seq/hash), NACK finitecode, PONG, PROJECTION. Typed UI requests: WATCHLIST_ADD/REMOVE, SELECT_ACTIVE, REFRESH, STOP_SESSION; validate config allowlist, do not transmit arbitrary URLs/selectors/executable code. API polling remains backend-owned.
UI subscriber role is read-only except these explicit user actions. Changes to scope beyond accepted stage require admission, not a WebSocket message alone. Session and counters reset only with new random session/key; stored observation identity does not reset. Worker restart invalidates old live eligibility until re-pair/current capture; panel closing never ends the backend poller, but if no watchlist/subscriber intent remains the explicit lifecycle ends sources.
Provider API key is never in this wire. Test-only fault operations absent from live module graph. Outgoing message limits enforced before enqueue; retained operator envelopes go to real IDB before send; ACK never deletes individual rows.8MiB transport backlog/127MiB spool cap; stop capture on cap and show health, not unbounded accumulation.

## Replay
Read frozen live_events in receive_index order, independently validate every source chain and canonical payload. Create fresh LiveStore, replay through same reducer with recorded observation times and separately recorded clock/wake/invalidation controls. Never make API/browser calls, never read expected fixture to fill missing event. Compare typed projection versions/logical state/cursors; omit only current replay process IDs and new physical storage-write timestamps. Original observed times, identity, scores, odds, gaps and quality flags are NOT omitted. Different capture receipt order can change projection; preserve actual receive order.
Missing row, modified odds with unchanged hash, missing binding revision, or fabricated source freshness must fail. Repeated equal provider responses retain observation receipts but do not fabricate semantic revisions. Proof links to source tree+config+profile hashes and platform evidence; no self-containing ZIP hash.
