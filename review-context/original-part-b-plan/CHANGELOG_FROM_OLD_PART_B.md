# Changes from the supplied Part B

| Old assumption | New explicit decision |
|---|---|
| fixtures30s + events30s | one shared batched ids poll,15s active, events fallbackOFF |
| max500requests for one run | example600hard cap, budget modelincludes480periodic+5overhead+20%reserve |
| min30s in old preflight | newv2config and newbatchedpreflight; oldv1unchanged |
| operator discovery technique undecided | initialfixedDOMreadonly; network/CDP only separate evidencedchange |
| transport reuse without payload seam | newclosedlivewire/events/spool/store; sharedlowlevelprimitives plusregressions |
| API key provided vaguely | PB-02 securelauncher; PB-18 asksusergetpass inprivate terminal; nochat/noenvdump |
| generic endpoint guesses | officialidsbatching, sourcefieldmap; actualselectedcoverageprobe stillrequired |
| key means live ready | keyauth, providerfeasibility, operatorprofile, platform, security, runconsent separate |
| onefixture then3/5 | retained, eachactualrunqualified; API20limitnotproduct20permission |
| potential source freshness doubled | samplingintervalhalved, no providerlatencyguarantee |
| fullruntime readiness fromoffline | still evidence-gated, noPartC/transactionactivation |

The seven NEXT_LIVE_INPUTS requirements remain. This plan does not assert the final
OS-15 artifact was independently inspected during authoring. Metadata/source reads
and math validation are not a real browser/API or live security test.

The active capture profile uses exact observed path entries, not a guessed route pattern. Local intent schema/consumption is owned by PB-14; its receipts are local consent, never fabricated independent signatures. Provider names are display-only bounded fields; stable IDs remain identity authority.
