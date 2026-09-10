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
Real host tool review and separate bounded observation consent remain external inputs.
An observed field map is no longer required for the selected-region mapping mode.

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
`--config`, `--intent`, `--review`, `--profile-name`, and exactly one of
`--selectors` or `--selected-region`.
These paths must name actual private inputs; there is no ready real-run command
while current external host review is absent. It verifies review
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

## Selected-region bootstrap candidate

`--selected-region` binds the reviewed selector policy to the exact closed marker
`{"selection_mode":"USER_SELECTED_REGION_V1"}`. It does not accept free-form code
or silently reuse a selector-bound review. After the separately confirmed intent,
the operator manually highlights only the visible match/market text in the chosen
tab, clicks the extension action, and pairs in its panel. No automated market
expansion or account interaction is provided.

The fixed reader uses the selected range's common ancestor, never widens the
capture root to its parents, requires a unique ID/data-attribute-anchored selector,
and refuses body/document selection or excluded/hidden descendants. It emits at
most 32 candidates wholly inside the selected range, at most 256 characters per
value and 10,000 UTF-8 bytes for the map. Candidates contain only an observed
restricted selector, leaf visible text, and the fixed `data-market-id` attribute.
No HTML, arbitrary attributes, cookies or storage are read. No stable selector,
empty selection, unprojectable root, changed selection or excessive size rejects.

Candidate selectors are derived from observed permitted identifiers/classes and
must pass the existing restricted CSS grammar again at the backend. They are not
assigned semantic roles automatically. Page DOM and selection remain untrusted:
the tool cannot certify that a script did not change a selection, nor infer
HOME/AWAY, fixture binding or settlement from it. Review the actual candidate
text and field mapping before creating a draft profile; a separate actual
profile review is still required for acceptance. Unknown/inaccessible IDs remain
unsupported. This candidate is not proof of feasibility on the actual operator.

Stop is enabled during discovery and aborts outside the serialized live-command
queue. It closes the socket and cancels pending browser reads, sending STOP to
an initialized reader. Socket closure and the ten-minute ceiling also cancel;
there is no automatic reconnect. Cancellation cannot retract an already saved
unadmitted sample. Prior raw evidence and review HOLD findings remain immutable.
