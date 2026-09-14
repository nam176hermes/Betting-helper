# Checks for an external source reviewer

Use the pinned project versions: Python 3.12.3, uv 0.11.7, Node 22.23.0 and
pnpm 10.33.2. These are repository requirements, not a claim that every external
machine already has them. Do not silently rewrite lockfiles or change versions.

After provisioning those tools, installing existing locked dependencies requires
package-registry network access, but no API-Football or operator access:

```bash
uv sync --frozen
pnpm install --frozen-lockfile --ignore-scripts
```

A small source-only slice (no actual Windows/browser gate):

```bash
uv run --frozen --offline python -B -m pytest -q \
  tests/live/test_bundle_poller.py \
  tests/live/test_provider_budget.py \
  tests/live/test_live_contracts.py \
  tests/live/test_live_store.py \
  -o cache_dir=.local/ai-review/pytest-cache
uv run --frozen --offline python tools/run_command_registry.py --self-check
pnpm --dir extension exec tsc -p tsconfig.live.json --noEmit
```

The explicit cache override avoids the original machine-specific pytest cache
path. Preserve `cacheprovider`; disabling it conflicts with strict configuration.
The actual export check records identify which commands were run on this branch;
the full historical audit command lists are under `evidence/latest-audit/`.

Host/controller qualifications, authoring migration checks and isolated Windows
Chrome tests require their declared environment. Copying source/config JSON to a
different path does not reproduce those host conditions. Several configs contain
original absolute paths; do not edit them merely to turn HOLD into PASS.

The copied authoring tree has no nested Git metadata. Pure authoring unit tests
may be inspected or run where portable; source-custody/migration checks need an
appropriately provisioned authoritative workspace and cannot be established by
the flattened snapshot alone.

Do not invoke provider probes, operator capture, live launch, authority bootstrap,
sealing or review signing as part of this advisory source review.
