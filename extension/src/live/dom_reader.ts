/** Fixed classic content script. Compile with --moduleDetection legacy; no imports. */
(() => {
  const global = globalThis as unknown as Record<string, unknown>;
  if (global["BH_LIVE_READER_V1"]) return;
  global["BH_LIVE_READER_V1"] = true;
  const fields = ["fixture_id", "home_team", "away_team", "home_id", "away_id", "market_root",
    "horizon_label", "home_selection", "draw_selection", "away_selection", "home_odds",
    "draw_odds", "away_odds", "market_status", "score", "period"];
  const excluded = /password|passwd|token|cookie|account|balance|betslip|cashout|login|email|username|wallet|form|input|textarea|iframe|contenteditable/i;
  const identifier = "[A-Za-z_][A-Za-z0-9_-]{0,127}";
  const suffix = `(?:[.#]${identifier}|\\[data-(?:testid|role|fixture-id|market-id|selection-id)=["'][A-Za-z0-9_-]{1,128}["']\\])`;
  const compound = new RegExp(`^(?:(?:div|span|section|article|header|h[1-6]|p|strong|em|label)(?:${suffix})*|(?:${suffix})+)$`);
  type Scope = {captureId: string; profileHash: string; bindingRevision: string; documentEpoch: string;
    exactUrl: string; leaseMs: number; selectors: Record<string, string | null>};
  let mapRange: Range | null = null;
  let scope: Scope | null = null;
  let root: Element | null = null;
  let observer: MutationObserver | null = null;
  let topology: MutationObserver | null = null;
  let debounce: ReturnType<typeof setTimeout> | undefined;
  let watchdog: ReturnType<typeof setInterval> | undefined;
  let lease: ReturnType<typeof setTimeout> | undefined;
  let stopped = true, reading = false, discovery = false, lastEmit = -Infinity, startWall = 0, deadline = 0;
  function notice(code: string): void {
    if (scope) void chrome.runtime.sendMessage({kind: "READER_NOTICE", captureId: scope.captureId,
      profileHash: scope.profileHash, bindingRevision: scope.bindingRevision,
      documentEpoch: scope.documentEpoch, code}).catch(() => { stop(); });
  }
  function stop(code?: string): void {
    stopped = true; observer?.disconnect(); topology?.disconnect();
    clearTimeout(debounce); clearTimeout(lease); clearInterval(watchdog);
    if (code) notice(code);
  }
  function guarded(): boolean {
    if (stopped || !scope) return false;
    if (Date.now() < startWall || performance.now() >= deadline) { stop("PROFILE_EXPIRED"); return false; }
    if (location.href !== scope.exactUrl || !root?.isConnected ||
        document.querySelectorAll(scope.selectors["match_root"] ?? "").length !== 1 ||
        document.querySelector(scope.selectors["match_root"] ?? "") !== root) {
      stop("NAVIGATED"); return false;
    }
    if (document.visibilityState !== "visible") { stop("HIDDEN"); return false; }
    return true;
  }
  function visible(node: Element): boolean {
    for (let p: Element | null = node; p; p = p.parentElement) {
      const style = getComputedStyle(p);
      if (style.display === "none" || style.visibility !== "visible" || Number(style.opacity) === 0 ||
          p.hasAttribute("hidden") || p.getAttribute("aria-hidden") === "true") return false;
    }
    const rect = node.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.right > 0 &&
      rect.top < innerHeight && rect.left < innerWidth;
  }
  function unsafe(node: Element): boolean {
    // Check fixed identifying metadata before text; never read arbitrary attributes or HTML.
    const bad = (p: Element): boolean => excluded.test(p.tagName + " " + p.id + " " + p.className) || p.hasAttribute("contenteditable");
    for (let p: Element | null = node; p; p = p.parentElement) if (bad(p)) return true;
    const children = node.querySelectorAll("*");
    if (children.length > 256) return true;
    return Array.from(children).some(p => bad(p) || !visible(p));
  }
  function selectedRegion(): boolean {
    return !!mapRange;
  }
  function stableSelector(node: Element, within: Document | Element): string | null {
    let cursor: Element | null = node, tail = "";
    for (let depth = 0; cursor && cursor !== within && depth < 8; depth++, cursor = cursor.parentElement) {
      const choices: string[] = [];
      if (new RegExp(`^${identifier}$`).test(cursor.id)) choices.push("#" + cursor.id);
      for (const name of ["testid", "role", "fixture-id", "market-id", "selection-id"]) {
        const value = cursor.getAttribute("data-" + name);
        if (value && /^[A-Za-z0-9_-]{1,128}$/.test(value)) choices.push(`[data-${name}="${value}"]`);
      }
      const tag = cursor.tagName.toLowerCase();
      for (const name of cursor.classList) if (new RegExp(`^${identifier}$`).test(name)) choices.push(tag + "." + name);
      choices.push(tag);
      const valid = choices.filter(part => compound.test(part) && !excluded.test(part));
      for (const part of valid) {
        const selector = part + tail;
        if (selector.length <= 512 && within.querySelectorAll(selector).length === 1 && within.querySelector(selector) === node) return selector;
      }
      const part = valid[0];
      if (!part) return null;
      tail = " > " + part + tail;
    }
    return null;
  }
  function readSelectionMap(): {status: string; fields?: Record<string, unknown>} {
    if (!guarded() || !root || !scope || !mapRange || !visible(root) || unsafe(root)) return {status: "CAPTURE_UNSUPPORTED"};
    const current = getSelection();
    if (!current || current.rangeCount !== 1 || current.isCollapsed) return {status: "CAPTURE_REJECTED"};
    const range = current.getRangeAt(0);
    if (range.compareBoundaryPoints(Range.START_TO_START, mapRange) || range.compareBoundaryPoints(Range.END_TO_END, mapRange)) return {status: "CAPTURE_REJECTED"};
    const candidates: {selector: string; text: string | null; market_id: string | null}[] = [];
    for (const node of root.querySelectorAll("*")) {
      if (node.childElementCount && !node.hasAttribute("data-market-id")) continue;
      const texts = Array.from(node.childNodes).filter((child): child is Text => child instanceof Text);
      const first = node.childElementCount ? undefined : texts[0], last = node.childElementCount ? undefined : texts.at(-1);
      if (range.comparePoint(first ?? node, 0) !== 0 ||
          range.comparePoint(last ?? node, last?.length ?? node.childNodes.length) !== 0) continue;
      if (!visible(node) || unsafe(node)) return {status: "CAPTURE_UNSUPPORTED"};
      const selector = stableSelector(node, root);
      if (!selector) continue;
      const text = node.childElementCount ? null : node.textContent.trim() || null;
      const market_id = node.getAttribute("data-market-id");
      if (text === null && market_id === null) continue;
      for (const value of [text, market_id]) if (value !== null && (!value || value.length > 256 || value !== value.normalize("NFC") || Array.from(value).some(c => c.charCodeAt(0) < 32 || c.charCodeAt(0) === 127))) return {status: "CAPTURE_UNSUPPORTED"};
      candidates.push({selector, text, market_id});
      if (candidates.length > 32) return {status: "CAPTURE_UNSUPPORTED"};
    }
    const fields = {match_root_selector: scope.selectors["match_root"], candidates};
    if (!candidates.length || new TextEncoder().encode(JSON.stringify(fields)).length > 10000) return {status: "CAPTURE_UNSUPPORTED"};
    return {status: "OK", fields};
  }
  function readVisibleBook(): {status: string; fields?: Record<string, string | null>} {
    if (!guarded() || !root || !scope) return {status: "NOT_VISIBLE"};
    const values: Record<string, string | null> = {};
    for (const name of fields) {
      const selector = scope.selectors[name];
      if (selector === null && (discovery || name === "score" || name === "period")) { values[name] = null; continue; }
      const nodes = root.querySelectorAll(selector ?? "");
      if (nodes.length !== 1 || !nodes[0] || !visible(nodes[0])) {
        if (discovery) { values[name] = null; continue; }
        return {status: "NOT_VISIBLE"};
      }
      const node = nodes[0];
      if (unsafe(node)) {
        if (discovery) { values[name] = null; continue; }
        return {status: "CAPTURE_UNSUPPORTED"};
      }
      const value = name === "market_root" ? node.getAttribute("data-market-id") : node.textContent;
      if (value === null) return {status: "CAPTURE_UNSUPPORTED"};
      const clean = value.trim();
      if (!clean || clean.length > 256 || clean !== clean.normalize("NFC") ||
          Array.from(clean).some(c => c.charCodeAt(0) < 32 || c.charCodeAt(0) === 127)) return {status: "CAPTURE_UNSUPPORTED"};
      values[name] = clean;
    }
    return {status: "OK", fields: values};
  }
  function schedule(): void {
    if (!guarded()) return;
    notice("DIRTY");
    clearTimeout(debounce);
    debounce = setTimeout(() => { if (guarded()) notice("RECAPTURE"); }, Math.max(250, 2000 - (performance.now() - lastEmit)));
  }
  function init(value: unknown, isDiscovery = false): void {
    if (!value || typeof value !== "object") throw Error();
    const s = structuredClone(value) as Scope;
    let selection: Range | null = null;
    if (isDiscovery && Object.keys(s.selectors).join() === "selection_mode" && s.selectors["selection_mode"] === "USER_SELECTED_REGION_V1") {
      const selected = getSelection();
      if (!selected || selected.isCollapsed || selected.rangeCount !== 1) throw Error();
      selection = selected.getRangeAt(0).cloneRange();
      const common = selection.commonAncestorContainer;
      const element = common instanceof Element ? common : common.parentElement;
      // Never climb from the user's selected subtree into a broader page region.
      if (!element || !visible(element) || unsafe(element)) throw Error();
      const selector = stableSelector(element, document);
      if (!selector || (!selector.includes("#") && !selector.includes("[data-"))) throw Error();
      s.selectors = Object.fromEntries(fields.map(name => [name, null]));
      s.selectors["match_root"] = selector;
    }
    if (Object.keys(s).sort().join() !== ["captureId", "profileHash", "bindingRevision", "documentEpoch", "exactUrl", "leaseMs", "selectors"].sort().join() ||
        !/^[0-9a-f-]{36}$/.test(s.captureId) || !/^[0-9a-f]{64}$/.test(s.profileHash) ||
        !/^(0|[1-9][0-9]{0,18})$/.test(s.bindingRevision) || !/^[0-9a-f-]{36}$/.test(s.documentEpoch) ||
        typeof s.exactUrl !== "string" || s.exactUrl !== location.href ||
        !Number.isSafeInteger(s.leaseMs) || s.leaseMs <= 0 || s.leaseMs > (isDiscovery ? 600000 : 7200000) ||
        typeof s.selectors !== "object" || Object.keys(s.selectors).sort().join() !== [...fields, "match_root"].sort().join()) throw Error();
    for (const [field, selector] of Object.entries(s.selectors)) {
      if (selector === null && ((isDiscovery && field !== "match_root") || field === "score" || field === "period")) continue;
      if (typeof selector !== "string" || !selector || selector.length > 512 || excluded.test(selector)) throw Error();
      const parts = selector.split(/\s*>\s*|\s+/);
      if (parts.length > 8 || parts.some(p => !compound.test(p))) throw Error();
    }
    const selector = s.selectors["match_root"] ?? "";
    if (!selector.includes("#") && !selector.includes("[data-")) throw Error();
    stop(); mapRange = selection; discovery = isDiscovery; scope = structuredClone(s); root = document.querySelector(selector);
    stopped = false; startWall = Date.now(); deadline = performance.now() + s.leaseMs;
    if (!guarded() || !root) throw Error();
    observer = new MutationObserver(schedule);
    observer.observe(root, {subtree: true, childList: true, characterData: true, attributes: true});
    topology = new MutationObserver(() => { if (guarded() && root && !visible(root)) schedule(); });
    topology.observe(document.documentElement, {subtree: true, childList: true, attributes: true});
    watchdog = setInterval(() => { if (guarded()) notice("RECAPTURE"); }, 30000);
    lease = setTimeout(() => { stop("PROFILE_EXPIRED"); }, s.leaseMs);
  }
  async function read(challenge: unknown): Promise<Record<string, unknown>> {
    if (typeof challenge !== "string" || !/^[0-9a-f]{64}$/.test(challenge) || reading ||
        !guarded() || performance.now() - lastEmit < 2000) return {status: "CAPTURE_REJECTED"};
    reading = true;
    const owner = scope;
    try {
      for (let attempt = 0; attempt < 3; attempt++) {
        const firstMono = Math.ceil(performance.now() * 1000);
        const first = selectedRegion() ? readSelectionMap() : readVisibleBook();
        if (first.status !== "OK") return first;
        await new Promise<void>(resolve => setTimeout(resolve, 100));
        const second = selectedRegion() ? readSelectionMap() : readVisibleBook();
        const mono = Math.ceil(performance.now() * 1000);
        if (scope !== owner || stopped) return {status: "CAPTURE_REJECTED"};
        if (second.status !== "OK") return second;
        if (mono - firstMono <= 1000000 && JSON.stringify(first) === JSON.stringify(second)) {
          lastEmit = performance.now();
          return {status: discovery ? "DISCOVERY_SAMPLE" : "DISPLAY_COHERENT", challenge, first: first.fields, second: second.fields,
            firstReadMonoUs: String(firstMono), browserMonoUs: String(mono), observedAtUtc: new Date().toISOString()};
        }
      }
      return {status: "UNSTABLE_SNAPSHOT"};
    } finally { reading = false; }
  }
  document.addEventListener("visibilitychange", () => { guarded(); });
  addEventListener("pagehide", () => { stop("NAVIGATED"); });
  addEventListener("popstate", () => { guarded(); });
  addEventListener("hashchange", () => { guarded(); });
  chrome.runtime.onMessage.addListener((message: unknown, sender, reply) => {
    if (sender.id !== chrome.runtime.id || sender.tab || sender.url !== chrome.runtime.getURL("src/live/background.js")) return false;
    const m = message as Record<string, unknown> | null;
    if (!m || m["kind"] !== "FIXED_DOM_READONLY" || Object.keys(m).sort().join() !== "kind,operation,value") return false;
    if (m["operation"] === "INIT" || m["operation"] === "DISCOVERY_INIT") {
      try { init(m["value"], m["operation"] === "DISCOVERY_INIT"); reply({status: "READY"}); } catch { stop(); reply({status: "CAPTURE_REJECTED"}); }
    } else if (m["operation"] === "READ") { void read(m["value"]).then(reply).catch(() => { reply({status: "CAPTURE_REJECTED"}); }); return true;
    } else if (m["operation"] === "STOP" && m["value"] === scope?.captureId) { stop(); reply({status: "STOPPED"}); }
    return false;
  });
})();
