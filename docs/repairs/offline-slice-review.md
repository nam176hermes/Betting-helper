# Offline dependency-path review

Scope: synthetic projector -> real IndexedDB Spool -> authenticated loopback
WebSocket -> durable raw/delivery journal -> shared Ingestor/RunStore -> fresh
SQLite replay -> independently reopened browser and evidence gate -> static diagnostic.
No LV/RS task, provider call, real browser profile or money action is implemented.

The read-only reviewer identified and the implementation repaired: Spool registry
cache invalidation; duplicate ACK durable-cursor validation; omitted consumed
artifact references; optimized-Python assertion bypass; and imprecise negative
control mutations. This is an independent code review, not a signed security
qualification or live approval. Formal independent security remains NOT_RUN.

Caches bind complete actual input/schema/source bytes, not mtimes. SQLite and
IndexedDB are reread after restart. Raw input and delivery/outcome evidence is
fsynced before ACK; the fixed inherited DDL/vendor is unchanged. The private
harness owns process groups and profiles. Keys travel only private IPC/memory.

Audit correction: OFF-19's 120-second limit covers the entire case, including
setup, cold readback, real replay and owned shutdown. The parent enforces this
process timeout; the independent verifier rejects over-budget command evidence
and case timings. Earlier workload-only PASS evidence does not satisfy this
corrected gate. OFF-19 now follows actual retained inputs into a separate real
Ingestor/RunStore process during delivery, then reopens all final source inputs
and compares actual projections. Independent verification still performs a new
sequential replay. No SQLite integrity check, FULL commit, schema validation,
record count or timeout threshold was removed.

The post-merge audit also adds the received-ACK/before-local-persist worker kill,
requires both worker restarts and actual duplicate recovery, scans all OFF-11
artifacts (including browser profiles) for five rejected poison inputs and their
fingerprints, and bounds reconnect attempts/backoff by one 30-second deadline
with injectable uniform jitter. Portable offline CI now runs on main pushes;
the real-browser CI job still requires the explicitly approved self-hosted runner.
The read-only reviewer checked these changes and the replay cleanup correction;
this is not a formal security receipt. Resource samples are not peak memory.

Legacy 46-crash/65-clock obligations remain a separate controller qualification.
Portable checks and the new 27-case gate do not replace them. The full legacy
controller is not run without its real configuration and authority inputs.
Production authority: NONE. Money readiness: NO.

Validation: explicit offline suite 107 passed in 524.69s; portable 85 repair tests passed in 689.57s, compile/registry/collection exit 0. After the parent-only import repair, scope/inventory/real gate tests passed 9 in 65.77s. Portable inputs for the inherited repair path are unchanged by that import-only repair; final acceptance reruns all 27 dependent cases.

Changed implementation mypy: 29 files passed. Scoped Ruff and TS compile/lint passed. Broader static scans retain 20 unrelated Ruff findings and 25 mypy errors in inherited governance modules; inherited repair-test mypy reports five errors on unchanged expressions. No global suppression or dependency churn was introduced.

Post-audit validation is recorded in `.local/offline-slice/execution-state.json`
and fresh `acceptance-fixes-*` evidence. The earlier counts above describe the
pre-audit source only. Failed load attempts are retained; the first full-case
passing probe measured 110.918 seconds, before the cleanup-only correction.
