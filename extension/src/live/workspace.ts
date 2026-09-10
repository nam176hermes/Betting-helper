import {button, mountWorkspace} from "./panel.js";
import type {SharedView, Command} from "./panel.js";
export function renderWatchlist(view: SharedView, target: HTMLElement, command: (command: Command, id: string) => void): void {
  // Preserve native keyboard focus while receipt ages change on the same projection.
  const key = JSON.stringify([view.active, view.matches.map(m => [m.binding.binding_id, m.binding.home_name, m.binding.away_name, m.display?.selected])]);
  if (target.dataset["key"] !== key) {
    target.dataset["key"] = key;
    target.replaceChildren(...view.matches.map(m => {
      const item = button(`${m.binding.home_name} / ${m.binding.away_name}`, () => { command("SELECT_ACTIVE", m.binding.binding_id); });
      item.dataset["binding"] = m.binding.binding_id; item.setAttribute("aria-current", String(view.active === m.binding.binding_id)); return item;
    }));
  }
  for (const item of target.querySelectorAll<HTMLElement>("[data-binding]")) {
    item.dataset["revision"] = view.matches.find(m => m.binding.binding_id === item.dataset["binding"])?.revision ?? "";
  }
}
if (typeof document !== "undefined" && document.body.dataset["liveWorkspace"] === "true") mountWorkspace(renderWatchlist);
