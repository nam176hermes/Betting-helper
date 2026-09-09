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

Timing interpretation for OFF-19: the 120-second bound covers the initialized
1,000-input workload, ACK, duplicate resend, cold browser readback and owned
shutdown. Setup/compilation and independent fresh replay/gate are separate phases
in timings.json. They are mandatory but not asserted to fit inside that workload
bound. No count, threshold or required case was reduced. Resource point samples
are neither peak memory nor a proof of a browser memory cap.

Legacy 46-crash/65-clock obligations remain a separate controller qualification.
Portable checks and the new 27-case gate do not replace them. The full legacy
controller is not run without its real configuration and authority inputs.
Production authority: NONE. Money readiness: NO.

Validation: explicit offline suite 107 passed in 524.69s; portable 85 repair tests passed in 689.57s, compile/registry/collection exit 0. After the parent-only import repair, scope/inventory/real gate tests passed 9 in 65.77s. Portable inputs for the inherited repair path are unchanged by that import-only repair; final acceptance reruns all 27 dependent cases.

Changed implementation mypy: 29 files passed. Scoped Ruff and TS compile/lint passed. Broader static scans retain 20 unrelated Ruff findings and 25 mypy errors in inherited governance modules; inherited repair-test mypy reports five errors on unchanged expressions. No global suppression or dependency churn was introduced.
