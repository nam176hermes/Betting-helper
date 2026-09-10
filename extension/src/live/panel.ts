/** Read-only rendering of the shared, authenticated backend projection. */
import type {CapturePlan, ObservedMarket} from "./capture.js";
import type {MarketBook, Score, Period} from "./contracts.js";
export type Horizon = MarketBook["horizon"];
export type Projection = {
  run_id: string; revision: string; model_status: "MODEL_NOT_QUALIFIED"; money_ready: false;
  binding: {binding_id: string; revision: string; home_name: string; away_name: string;
    league_id: number; season: number; kickoff_utc: string; provider_fixture_id: number;
    operator_fixture_id: string; operator_home_id: string; operator_away_id: string;
    operator_match_url: string; livescore_match_url: string | null; orientation_status: string; evidence_hashes: string[]};
  provider_state: {score_current: Score; score_ht: Score; period: Period; elapsed_minute: number | null;
    extra_minute: number | null; clock_precision: string; quality_flags: string[]} | null;
  books: MarketBook[]; health: {state: string; reason: string; evidence_hashes: string[]};
  display?: {source_kind: "MOCK" | "OBSERVED_REAL"; status: string; selected: boolean; max_matches: 1 | 3 | 5;
    provider_receipt_age_us: number | null; provider_content_age_us: number | null; source_age_us: null;
    markets: Partial<Record<Horizon, {status: string; receipt_age_us: number | null; content_age_us: number | null; source_age_us: null}>>;
    h2_score: Score; quota: {session_remaining: number; daily_remaining: number; minute_remaining: number; provider_remaining: number | null};
    provider_connection: string; capture_connection: string; notice?: string};
  capture_scope?: {stream_id: string; generation: string; exact_url: string; profile_status: "DRAFT" | "ACCEPTED";
    profile_hash: string; document_epoch: string; selectors: CapturePlan["selectors"]; price_parser: CapturePlan["priceParser"];
    markets: ObservedMarket[]; expires_at: string; max_duration_seconds: number};
};
export type Command = "START_CAPTURE" | "WATCHLIST_ADD" | "WATCHLIST_REMOVE" | "SELECT_ACTIVE" | "REFRESH" | "STOP_SESSION" | "OPEN_OPERATOR" | "OPEN_LIVESCORE";
export type SharedView = {matches: Projection[]; active: string | null; connection: string; notice?: string};
export function exactLink(value: string | null): string | null {
  if (value === null) return null;
  try { const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password && value.length <= 2048 ? value : null;
  } catch { return null; }
}
export const ageLabel = (value: number | null | undefined): string => value == null ? "UNKNOWN" : `${String(Math.floor(value / 1000000))}s`;
export const selectedBook = (snapshot: Projection, horizon: Horizon): MarketBook | null =>
  snapshot.books.find(b => b.binding_id === snapshot.binding.binding_id && b.binding_revision === snapshot.binding.revision && b.horizon === horizon) ?? null;
const scoreLabel = (score: Score | undefined): string => score ? `${String(score.home)} – ${String(score.away)}` : "UNKNOWN";
export function element<K extends keyof HTMLElementTagNameMap>(tag: K, text?: string): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag); if (text !== undefined) node.textContent = text; return node;
}
export function button(label: string, action: () => void, disabled = false): HTMLButtonElement {
  const node = element("button", label); node.type = "button"; node.disabled = disabled; node.addEventListener("click", action); return node;
}
export function renderMatch(snapshot: Projection | null, horizon: Horizon, target: HTMLElement): void {
  const expanded = target.querySelector("details")?.open ?? false;
  const focusEvidence = target.querySelector("summary") === document.activeElement;
  target.replaceChildren();
  target.dataset["revision"] = snapshot?.revision ?? "";
  target.dataset["binding"] = snapshot?.binding.binding_id ?? "";
  if (!snapshot) { target.append(element("p", "NO_DATA — Pair an admitted local session to view data.")); return; }
  const b = snapshot.binding, p = snapshot.provider_state, d = snapshot.display;
  target.append(element("p", d?.source_kind === "MOCK" ? "SYNTHETIC — MOCK DATA" : "READ ONLY"),
    element("h2", `${b.home_name} / ${b.away_name}`),
    element("p", `Fixture ${String(b.provider_fixture_id)} · Competition ${String(b.league_id)} · ${String(b.season)}`),
    element("p", `Kickoff (UTC): ${b.kickoff_utc} · Orientation: ${b.orientation_status}`),
    element("p", `Score ${scoreLabel(p?.score_current)} · HT ${scoreLabel(p?.score_ht)} · H2 ${scoreLabel(d?.h2_score)}`),
    element("p", `${p?.period ?? "UNKNOWN"} · Source minute ${String(p?.elapsed_minute ?? "UNKNOWN")}${p?.extra_minute == null ? "" : ` +${String(p.extra_minute)}`} · Precision ${p?.clock_precision ?? "UNKNOWN"}`));
  const book = selectedBook(snapshot, horizon), market = d?.markets[horizon];
  const status = element("p", `${d?.status ?? "WAITING_FOR_DATA"} · ${horizon}: ${book ? market?.status ?? "UNVERIFIED" : "NO_DATA"}`);
  status.className = "status"; status.setAttribute("role", "status"); target.append(status);
  const odds = element("dl"); odds.className = "odds";
  for (const [side, label] of [["HOME", "H"], ["DRAW", "D"], ["AWAY", "A"]] as const) {
    const cell = element("div"); cell.append(element("dt", label), element("dd", book?.selections[side].decimal_odds ?? "—")); odds.append(cell);
  }
  target.append(odds, element("p", `Market ${book?.market_status ?? "NO_DATA"} · ${book?.capture_evidence_tier ?? "UNVERIFIED"}`),
    element("p", `Provider receipt ${ageLabel(d?.provider_receipt_age_us)} · Content change ${ageLabel(d?.provider_content_age_us)} · Source update UNKNOWN`),
    element("p", `Market receipt ${ageLabel(market?.receipt_age_us)} · Content change ${ageLabel(market?.content_age_us)} · Source update UNKNOWN`),
    element("p", `Quality: ${[...(p?.quality_flags ?? []), ...(book?.quality_flags ?? [])].join(", ") || "NONE_REPORTED"}`));
  if (d) target.append(element("p", `Budget: session ${String(d.quota.session_remaining)} · UTC day ${String(d.quota.daily_remaining)} · minute ${String(d.quota.minute_remaining)} · Last provider quota observation ${String(d.quota.provider_remaining ?? "UNKNOWN")}`),
    element("p", `Provider ${d.provider_connection} · Capture ${d.capture_connection} · Admitted capacity ${String(d.max_matches)}`));
  const details = element("details"), evidence = element("pre", JSON.stringify({run_id: snapshot.run_id, revision: snapshot.revision,
    binding: snapshot.binding, health: snapshot.health, provider: p, book}, null, 2));
  details.open = expanded; details.append(element("summary", "Show data evidence"), evidence); target.append(details);
  if (focusEvidence) details.querySelector("summary")?.focus();
}
export function connectWorkspace(onView: (view: SharedView) => void): Pick<chrome.runtime.Port, "postMessage" | "disconnect"> {
  let port: chrome.runtime.Port | undefined, stopped = false, attempts = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const connect = (): void => {
    if (stopped || port) return;
    const next = chrome.runtime.connect({name: "BH_LIVE_UI"}); port = next;
    next.onMessage.addListener((view: SharedView) => { attempts = 0; onView(view); });
    next.onDisconnect.addListener(() => {
      if (port !== next) return;
      port = undefined; onView({matches: [], active: null, connection: "DISCONNECTED — pair again"});
      // Restore display subscriptions only; the new worker still needs a fresh manual ticket.
      if (!stopped && attempts++ < 3) timer = setTimeout(connect, 250 * attempts);
    });
  };
  const disconnect = (): void => { stopped = true; clearTimeout(timer); port?.disconnect(); port = undefined; };
  window.addEventListener("pagehide", disconnect, {once: true});
  connect();
  return {disconnect, postMessage: (message: unknown): void => {
    if (stopped) throw Error("E_UI_CLOSED");
    clearTimeout(timer); connect(); port?.postMessage(message);
  }};
}
export function mountWorkspace(watchlist: (view: SharedView, target: HTMLElement, command: (command: Command, id: string) => void) => void): void {
  const root = document.querySelector<HTMLElement>("main"); if (!root) throw Error("E_PANEL_ROOT");
  const connection = element("p", "DISCONNECTED"), list = element("nav"), tabs = element("nav"), match = element("section"), controls = element("div");
  list.setAttribute("aria-label", "Approved fixtures"); tabs.setAttribute("aria-label", "Market horizon");
  controls.className = "controls";
  let view: SharedView = {matches: [], active: null, connection: "DISCONNECTED"}, horizon: Horizon = "FT";
  let lastTabs = "", lastControls = "";
  const current = (): Projection | null => view.matches.find(m => m.binding.binding_id === view.active) ?? null;
  const command = (operation: Command, id: string): void => { port.postMessage({operation, bindingId: id}); };
  const render = (): void => {
    connection.textContent = view.connection + (view.notice ? " — " + view.notice : "");
    watchlist(view, list, command); renderMatch(current(), horizon, match);
    if (lastTabs !== horizon) {
      tabs.replaceChildren(...(["FT", "H1", "H2"] as const).map(h => {
        const tab = button(h, () => { horizon = h; render(); tabs.querySelector<HTMLButtonElement>(`[data-horizon="${h}"]`)?.focus(); });
        tab.dataset["horizon"] = h; tab.setAttribute("aria-pressed", String(h === horizon)); return tab;
      })); lastTabs = horizon;
    }
    const m = current(), key = JSON.stringify([view.active, m?.display?.selected, view.connection, m?.capture_scope?.profile_hash]);
    if (key === lastControls) return; lastControls = key;
    const id = m?.binding.binding_id ?? "", ready = !!m?.display && view.connection === "CONNECTED";
    const start = button("Start read-only", () => {
      const selected = current(), url = selected && exactLink(selected.binding.operator_match_url);
      if (!selected?.capture_scope || !url || selected.capture_scope.profile_status !== "ACCEPTED") return;
      // Native permission request is directly inside the explicit button gesture.
      void chrome.permissions.request({origins: [new URL(url).origin + "/*"]}).then(granted => {
        if (granted) command("START_CAPTURE", selected.binding.binding_id);
      }).catch(() => { connection.textContent = "PERMISSION_DENIED"; });
    }, !ready || m.capture_scope?.profile_status !== "ACCEPTED");
    controls.replaceChildren(start, button(m?.display?.selected ? "Pause / Remove fixture" : "Add approved fixture", () => {
      command(m?.display?.selected ? "WATCHLIST_REMOVE" : "WATCHLIST_ADD", id);
    }, !ready), button("Refresh", () => { command("REFRESH", id); }, !ready),
    button("Stop session", () => { command("STOP_SESSION", id); }, !ready),
    button("Open Mise-o-jeu match", () => { command("OPEN_OPERATOR", id); }, !ready || !exactLink(m.binding.operator_match_url)),
    button("Open LiveScore match", () => { command("OPEN_LIVESCORE", id); }, !ready || !exactLink(m.binding.livescore_match_url)));
  };
  const port = connectWorkspace(next => { view = next; render(); });
  const form = element("form"), label = element("label", "Local session pairing ticket (not an API key)"), input = element("input"), pair = element("button", "Pair local session");
  input.type = "password"; input.id = "pairing-ticket"; input.autocomplete = "off"; input.maxLength = 4096; label.htmlFor = input.id;
  pair.type = "submit"; form.append(label, input, pair);
  form.addEventListener("submit", event => {
    event.preventDefault(); const ticket = input.value; input.value = "";
    port.postMessage({operation: "PAIR", ticket});
  });
  root.append(form, connection, list, tabs, controls, match); render();
}
