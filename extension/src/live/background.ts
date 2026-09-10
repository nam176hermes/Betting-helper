import type {CaptureIdentity} from "./capture.js";

/** Narrow content-script notices; never an evaluation or arbitrary browser-command surface. */
export function handleCaptureMessage(message: unknown, sender: chrome.runtime.MessageSender,
  active: CaptureIdentity, extensionId: string): boolean {
  if (!message || typeof message !== "object") return false;
  const m = message as Record<string, unknown>;
  return Object.keys(m).sort().join() === "bindingRevision,captureId,code,documentEpoch,kind,profileHash" &&
    m["kind"] === "READER_NOTICE" && sender.id === extensionId && sender.tab?.id === active.tabId &&
    sender.documentId === active.documentId && sender.frameId === 0 && sender.url === active.exactUrl &&
    m["captureId"] === active.captureId && m["profileHash"] === active.profileHash &&
    m["bindingRevision"] === active.bindingRevision && m["documentEpoch"] === active.documentEpoch &&
    typeof m["code"] === "string" && ["DIRTY", "RECAPTURE", "NAVIGATED", "HIDDEN", "PROFILE_EXPIRED"].includes(m["code"]);
}
if (typeof chrome !== "undefined") {
  chrome.action.onClicked.addListener(tab => {
    if (tab.id !== undefined) void chrome.sidePanel.open({tabId: tab.id}).catch(() => undefined);
  });
}
