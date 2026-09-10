# Live admission — PB-20

Status: WAITING_REVIEW; real provider and operator evidence are also absent.
No real fixture is currently admitted. The local tests reject transplanted mock
bindings, truthy profile flags and key presence before provider I/O.

The existing PB-16 gate loads only configured private nonsecret references.
It matches selected provider IDs, league, season, kickoff, HOME/AWAY IDs,
operator IDs, observed routes and profile/source hashes. There is no name-fuzzy
approval. Missing provider observations, synthetic/draft profiles, modified
scope, stale source or absent current host review keep admission closed.

Before one real run, the external review described in
`docs/pre-live-security-review.md` must cover current provider, profile, capture,
platform and Part A artifacts and the exact config/source bytes. The worker
does not sign its own approval or launch protected host review. Preserve the
actual external authorization/result/receipt; changing a reference or current
source invalidates the binding.

After those inputs are accepted, run network-free preflight, prepare the exact
one-fixture intent including the observed operator URL, and confirm separately
in the user's own terminal. The user-terminal live launcher previews at most
120 minutes and 600 attempts and requires `START READ ONLY`. Preflight success
alone starts nothing. A restart needs a new intent, key entry and local pairing.

PB-21's observed run, three manual complete FT comparisons and fresh replay are
still required for LIVE_READ_ONLY_PASS_ONE. Three/five scopes remain separately
gated. MODEL_ENABLED: false. MONEY_READY: NO.
