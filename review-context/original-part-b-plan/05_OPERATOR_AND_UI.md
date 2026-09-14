# Operator capture, synchronization and read-only UX

## First capture strategy
Use a fixed bundled isolated-world DOM reader, not generic CDP dispatch. This is a deliberate minimal Part B default, replacing the earlier undecided network-first/DOM fallback choice. It does not claim DOM will work on the actual site. If odds/semantic labels are inaccessible, stop at CAPTURE_UNSUPPORTED and create a separately reviewed network-adapter change; do not widen permissions automatically.

Profile must be produced from one authorized current match in PB-19. Default candidate domain from user workflow is `https://miseojeuplus.espacejeux.com`; any redirect/other origin must be observed and user-approved. No selectors, market IDs or live fixture URLs are supplied as guessed facts in this package.

## Profile schema and admission
Fields: profile_id/version/source_kind, origin, exact accepted path set or anchored path regex, permitted_fixture_ids, locale, price_parser enum DECIMAL_DOT/DECIMAL_COMMA, selectors for match root/home/away/operator IDs/score/period/market root/horizon labels/HDA selections/status, selected horizon list, observation_mode FIXED_DOM_READONLY, evidence hashes, capture_source_hash, reviewed_source_hash, validity expires_at, stage1/3/5.
A draft profile has statusDRAFT, no activation; missing selectors/evidence cannot become accepted. Active profile requires sanitized samples, actual field mapping, operator/football identity consistency and source-bound review. CSS selectors are read-only data restricted to a match-root subtree; no script, XPath executable extension, URLs, mutation expression or user/backend free-form evaluate surface. Unknown fields reject.
Exclude inputs/textareas/contenteditable/forms/password/account/balance/betslip/cashout areas. Reader never reads document.cookie, storage, fetch responses, full document HTML or arbitrary attributes. Profile cannot select an excluded node. Limit text256chars/node and captured aggregate64KiB; sanitize before runtime messages/storage. Page content is untrusted even after login.

## Capture algorithm
1. User clicks extension action on a selected tab; open Side Panel. Confirm URL against admitted origin/path; register tab ID, document ID, profile hash and binding revision.
2. Execute only bundled `live/dom_reader.js` in ISOLATED world with an already accepted bounded selector profile. No page-originated configuration.
3. In a single synchronous JS task read the entire market subtree, labels/IDs/three odds/status/context. Reading must not click or expand markets. Hidden/virtualized absent items => NOT_VISIBLE. User may manually show market; tool does not add a betslip selection.
4. Require stable identical semantic snapshots in two reads100ms apart, max3 attempts, then emit DISPLAY_COHERENT; otherwise UNSTABLE_SNAPSHOT and no current book. This is display-coherence evidence only, not native atomicity.
5. Capture on local DOM mutation with debounce250ms and maximum one emitted complete snapshot per2s;30s watchdog recapture when tab is visible. Observe whole selected root replacement and route changes. Repeated equal content logs last_observed separately; source_updated_at stays null unless supplied and verified.
6. Validate sender extension/tab/document/frame0 against pending capture request; content script is not an arbitrary browser-command interface. Discard late A data after tab becomes B. Stop when document/origin changes, tab closes, profile expires or lease ends. Hidden/discarded tab never pretends current data merely from a timer.
7. Navigation/score/card/period/market suspend creates invalidation control before any potentially stale book is reused. New tab context must be bound before output is eligible.

## Three price semantics
DISPLAY_COHERENT: three visible prices/labels read together and stable.
NATIVE_ATOMIC: only possible in later independently evidenced native-revision adapter; Part B DOM adapter cannot emit it.
ACCEPTED: never emitted by Part B. Viewing odds is not an accepted transaction.

## Synchronization reducer
ProviderState and OperatorContext are independent sources. Do not overwrite one with the other. Project MatchView keyed bybinding_id and revision; inactive source changes cannot affect other matches.
Statuses: WAITING_FOR_DATA, CURRENT_DISPLAY_ONLY, SOURCE_TIME_UNKNOWN, STALE_PROVIDER, STALE_MARKET, STATE_CONFLICT, MARKET_SUSPENDED, PROFILE_EXPIRED, OUT_OF_SCOPE, STOPPED.
H1/H2/FT book context is independent; after halftime H1 may be settled/unavailable without hiding valid FT. H2 semantics refer only to second-half goals; show no H2 derived score if HT baseline is unverified.

On observed goal/card/VAR reversal/period change/suspension/sequence gap/document change: increment local match epoch and invalidate old book eligibility. Record cause/evidence. Source timestamps may be unmapped; do not invent causal order from wall-clock equality. For read-only reopening require same binding, a new complete post-invalidation capture, a provider observation requested after invalidation, coherent available score/period and OPEN market. If operator context is unavailable, keep CONTEXT_UNVERIFIED—displayable but not action-grade. Conflict remains until actual sources converge or binding is corrected with evidence, not a fixed sleep.
UI receipt thresholds (engineering defaults): provider max(45s,2*scheduled_interval+5s); market35s if30s watchdog; source-age UNKNOWN if upstream time absent. HT60s polling therefore does not trigger an impossible45s freshness target. Display receipt age, content-change age and source-update age separately. Never label a newly reread unchanged DOM as an upstream update.

## UI deliverable
Plain TypeScript/HTML/CSS, no new React/Next migration. `panel.ts` and extension-page `workspace.ts` subscribe to one backend projection; no API key and no direct football HTTP from either. Keep full watchlist even if panel selects one match. Multi-match capacitystage1 then3 then5.

Screen fields: fixture/competition/date, verified home/away, current/HT scores, period/source minute, FT/H1/H2 tabs, H/D/A odds, market status, receipt/source ages, quality flags, API budget remaining, capture/provider connection, MODEL_NOT_QUALIFIED.
Controls: Pair local session, Start read-only with admitted run, Pause/Stop, Refresh(coalesced), Add approved fixture, Remove fixture, Open exact Mise-o-jeu match, Open verified LiveScore match, Show data evidence. No BET, BUY, SELL, recommended stake, Cashout or probability placeholders.
LiveScore is an optional link, not an API feed. Missing exact link disables that control; do not guess a route from team names. Operator link taken only from profile-approved exact match binding and opened via extension tab API, not page-provided script URLs.

## Permissions and lifecycle
Live manifest separate from offline: storage, sidePanel, scripting, activeTab; optional exact operator origin permission requested on explicit user action after profile review. Pin background service worker and extension ID derived from a public manifest key (not a secret). No debugger/cookies/webRequest/nativeMessaging permission in initial DOM adapter. Runtime CSP self only; connect-src exact local ws authority; no CDN/remote code.
Store only nonsecret watchlist intent/profile reference in storage.local; pairing secret in storage.session/memory with explicit expiry. Service worker termination must cause reconnection/revalidation, not loss of durable captures. Active WebSocket may affect worker lifetime[C2]; test actual termination separately. A manual pause stops new capture and provider polling but retains last values visiblyPAUSED. Stop closes owned session and expires pairing; no automatic startup after OS restart.
