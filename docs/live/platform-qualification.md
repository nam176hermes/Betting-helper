# Part B platform qualification

Selected by the user: **Windows Chrome → WSL2 backend**. The qualifier uses a fresh
owned Windows profile and the existing native Windows Job Object controller.
Only its own process handles are terminated. The listener remains 127.0.0.1:8765
at `/live`; no firewall, WSL networking mode or broad listener change is attempted.

`tools/qualify_live_platform.py` owns the production extension build. It compiles
the live modules with the pinned TypeScript compiler, composes static standalone
Ajv validators into the MV3 worker, and retains build hashes outside tracked code.
The classic isolated DOM reader stays a classic script. The test-only page and
fixed worker-stop CDP driver are added to a private copy after binding that graph;
neither is shipped in the production extension.

Run from this checkout with a validated nonsecret v2 config selecting the platform:

```bash
uv run --frozen --offline python tools/qualify_live_platform.py --config config/live.local.json --output .local/part-b/platform-candidate
```

The output directory must be new. No provider key is read. The actual browser
executable hash, native handle/CIM identity, extension Origin, authenticated WSL
projection, wrong-path rejection, panel closure/reopen, service-worker termination
and explicit pairing repair are observed. Both display pages share the same worker
and projection; opening them creates no additional provider requests. Provider
responses and fixture identities in this test are explicitly synthetic.

Worker termination clears current eligibility. UI pages restore display ports with
at most three attempts; fresh authentication still requires the user's new local
pairing ticket. During an admitted live run, type `PAIR` in the same controlling
terminal to issue that ticket. Existing expiry, ticket count and run scope apply;
this does not restart or extend the run and never asks for another provider key.

This is an isolated headless Windows Chrome bridge check. Native Side Panel toolbar
interaction, real operator capture, OS sleep/wake, physical power loss and account
browser crash drills remain **NOT_OBSERVED**. Linux browser tests are separate
evidence. A failed Windows check remains WAITING_PLATFORM; Linux cannot replace it.

Reports and failed runs remain in `.local/part-b/` and the referenced owned Windows
directories. The report's SYNTHETIC label describes fixture data; browser/WSL
transport and process observations are real. It grants no live or security authority.
