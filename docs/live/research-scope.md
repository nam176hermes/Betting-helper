# Performance-blind research handoff

`freeze_dataset_manifest(run_refs, quality_view)` reads closed SQLite recordings,
replays them independently and hashes the actual source databases. It exposes
only identity, coverage, receipt timing, correction/quality flags, missingness,
quota, unknown cost and access-review references. The scope-selection input is
closed: `selection_basis=DATA_QUALITY_ONLY`, `historical_data`, and optional
chronological TRAIN / VALIDATION / TEST date intervals, with no overlap.
Unknown performance fields are rejected, including nested partition fields.

Actual observations stay in referenced databases outside the quality view.
Recorded scores are not asserted to be final settlement labels. FT means normal
time including stoppage; H1/H2 remain unqualified unless separately observed and
admitted. Historical data are NOT_SUPPLIED in this batch. No competition is
chosen after inspecting ROI, accuracy, profit or a model.

Optional `data_rights_refs` bind exact files for API_FOOTBALL and MISE_O_JEU by
absolute path and SHA256. Each private record has only `source`, `status`
(ACCEPTED or REVIEW_REQUIRED), `uses` ([LOCAL_RECORDING, RESEARCH]),
`reviewer_role=USER_DATA_ACCESS_REVIEW`, and `reviewed_at_utc`. These are user
access-review records, not legal opinions or independent host signatures.
No access rights or price are inferred from availability or a subscription name.

Current status: no real dataset, no supplied rights evidence,
SCOPE0_READY_FOR_REVIEW=false. Synthetic records may prove hash/replay provenance
but cannot confer real-source acceptance. Existing SCOPE0 approval and revocation
contracts remain closed. MODEL_ENABLED=false, MONEY_READY=NO; RS-01 and Part C
are not started by this handoff.

For a later release, private `.local/part-b/data-manifest-input.json` may contain
only `run_dirs` (relative `.local/` paths to frozen recordings) and `quality_view`
with the closed fields above and optional `data_rights_refs`. The release gate
reopens and requalifies these recordings and writes its own manifest. An absent
or invalid input stays WAITING_DATA_AND_RIGHTS_REVIEW.
