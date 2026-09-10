# Operator capability — PB-19

OPERATOR_PROFILE_ACCEPTED: NOT_EXECUTED. Status: WAITING_OPERATOR_SAMPLE.
The admitted-profile index is intentionally empty. Its passing rejection tests
prove that absence, draft selectors and synthetic fixtures cannot become real
acceptance; they do not prove any Mise-o-jeu capability.

No real tab, account, DOM sample, route, participant orientation, selection ID or
settlement label has been observed by this implementation worker. Existing
synthetic profiles remain DRAFT and inactive for operator use.

The next observation requires a dedicated Chrome Windows profile manually
logged in by the user, one exact chosen fixture tab, a separately confirmed
OPERATOR_DISCOVERY intent of at most ten minutes, and current external review of
the fixed read-only tool. Provider access is not a discovery prerequisite.
The separate `execute-discovery` launcher and `takeDiscoverySample` reader now
implement first-sample collection without an accepted profile. They require an
actual OPERATOR_DISCOVERY_TOOL review, a restricted selector field map, a one-use
terminal confirmation, and the tab selected by clicking the extension action.
The normal live capture flow still requires an accepted profile. First-sample
collection has not been executed on a real operator tab.

PB-18's exact-fixture provider probe passed for fixture 1635632 on the earlier
source; current source-bound admission must be refreshed. The user selected
this public operator route:
`https://miseojeuplus.espacejeux.com/sports/en/sports/event/1361565/soccer/european/uefa-champions-league/bodo-glimt-at-bayern-munich`.
Event ID 1361565 is parsed from that user-supplied route, not observed DOM.
Its binding to provider fixture 1635632, HOME/AWAY orientation and settlement
remain unverified. The user reports the dedicated Chrome tab ready after the
manual-login preparation instruction and names the profile `Betting-Helper`.
The browser tab/document identity has not been observed; readiness and a supplied
profile name are not capture approval.
Do not request another API key for this operator step. The existing
OPERATOR_DISCOVERY intent declaration remains inert until the keyless launcher
verifies real host review and consumes terminal consent. No real selectors are
available yet: the field map must come from observed mapping, never guessed IDs.
Review and field mapping remain external inputs before real observation.

The exchange uses only `ws://127.0.0.1:8765/operator-discovery`, the pinned
extension Origin, an ephemeral pairing ticket and a fresh challenge. AUTH, PLAN,
SAMPLE and ACK have separate HMAC purposes. The ticket goes into the existing
local pairing field; it is not an API key and is not stored as evidence.
There is one connection attempt and one bounded sample, no reconnect loop.
Ctrl+C in the user terminal stops the listener; a closed connection rejects
further exchange instead of waiting for another close event.
The fixed reader stops after the attempt. Hidden, replaced or expired documents
reject; missing or excluded fields remain null. Output is UNADMITTED_SAMPLE,
with profile_accepted=false and binding_verified=false, never a MarketBook or
an accepted extraction profile. A later actual sample/profile review is required.

The entry point is `tools/prepare_part_b_intent.py execute-discovery` with
`--config`, `--intent`, `--selectors`, `--review`, and `--profile-name`.
These paths must name actual private inputs; there is no ready real-run command
while the observed field map and external review are absent. It verifies review
before asking for ALLOW OPERATOR OBSERVATION and never requests a provider key.

Read only fixture identity/labels, participant orientation, horizon/settlement,
market and selection IDs, three displayed prices and permitted market context.
Do not collect full HTML, account/balance/betslip areas, cookies or login data,
and do not click selections. Missing or ambiguous fields remain unsupported.

Once actual samples and external receipts exist, keep their bytes private under
`.local/part-b/`. Populate the source-owned index with bounded references and
hashes only; `test_operator_profile_samples.py` reopens the samples and validates
the existing host review and exact capture-source binding. No signer, host
review launcher or self-approved receipt is provided by these tests.
