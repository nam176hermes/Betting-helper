# Hybrid Discovery v6.3.6 REPO0 runtime

The separately authorized Part B v2 read-only implementation is documented in
[PART_B_HANDOFF](docs/live/PART_B_HANDOFF.md) and the
[startup/shutdown runbook](docs/runbooks/START_LIVE_READ_ONLY.md). Its mock,
platform, provider, operator and real-session verdicts remain separate. The
legacy synthetic RawObservation contract is unchanged; no Part C or money
authority follows from local implementation or tests.

This checkout is the v6.3.6 authoring/governance runtime. Its `6.2.0` Python
and extension package versions identify compatibility with the inherited v6.2
data/schema contract; they are not the runtime release name.

The checkout contains bootstrap/governance tests plus implemented, bounded
repair tests. Tests for an intentional stub or a blocked browser prerequisite
remain visible but do not prove that behavior is implemented. Nothing here
authorizes authenticated access, browser attachment, provider calls, live
discovery, betting, deployment, or production use.

Normative assets are copied byte-for-byte from an approved v6.3.6 source pack
into `vendor/hybrid-discovery-v6.3.6/` only by `tools/sync_pack_assets.py`.
`task-command-registry.json`, `schema-lock.json`, and the vendor manifest are
generated outputs and must not be edited independently.

## Portable verification

With the pinned dependencies already installed, the portable profile uses no
network and no path outside this checkout:

```bash
uv run --frozen --offline python tools/verify_local.py --profile portable
```

It compiles the TypeScript test configuration first, runs the registry
self-check and the explicit implemented repair tests, then collects every
repo-local repair test. Collection keeps blocked and not-implemented
obligations visible; it is not execution evidence for those cases. The
pytest defaults likewise use only `tests/` and `.local/bh-repair/pytest-cache`.

The authoritative controller's actual mode is `candidate-qualification`, not
the former documented `baseline` mode:

```bash
uv run --frozen --offline python tools/run_command_registry.py --self-check
uv run --frozen --offline python tools/run_command_registry.py \
  --mode candidate-qualification --registry task-command-registry.json
```

Do not invoke the second command as a portable substitute. The full profile
delegates to it only after reporting all explicit external prerequisites as
valid.

## Full qualification

Full qualification requires explicit absolute paths for the governed source
pack, evidence/receipts, external authoring tests, uv cache, pnpm store, and a
recorded Chrome binary plus SHA-256:

```bash
uv run --frozen --offline python tools/verify_local.py --profile full \
  --pack "$PACK" \
  --evidence-root "$EVIDENCE_ROOT" \
  --authoring-tests "$AUTHORING_TESTS" \
  --uv-cache "$UV_CACHE" \
  --pnpm-store "$PNPM_STORE" \
  --chrome "$CHROME" \
  --chrome-sha256 "$CHROME_SHA256"
```

Missing, stale, mismatched, or relative inputs produce a machine-readable
`HOLD` report before any authoritative command runs. The verifier never
guesses paths, downloads dependencies, launches Chrome, reseals a pack,
rewrites receipts, or falls back to another pack version. See
`docs/repairs/external-evidence-index.md` for the obligations retained outside
the portable profile.

The current governed candidate commands target a different authoring runtime
and cannot consume every supplied pack/evidence/test/cache/browser setting
through the existing controller interface. This checkout therefore reports
`CONTROLLER_CONFIG_UNBOUND` and does not delegate. Making that interface
express the validated configuration requires a separately governed source
change; this repair does not edit or bypass the registry.

## Authority

- Portable profile: local repair evidence only.
- Full profile: legacy controller delegation only when every prerequisite is
  valid; it is separate from scoped repair acceptance.
- Bootstrap tests: governance/schema compatibility, not implemented discovery.
- Implemented repair tests: only the named behavior they execute.
- Live discovery and production authority: `NONE`.

The extension bootstrap remains inert and reports
`READY_TO_IMPLEMENT_DISCOVERY_PACK:NO`.
