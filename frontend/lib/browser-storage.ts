/** Browser storage can be unavailable or full. Keep the current tab usable. */
export const accountScopeEvent = "cryptorisk:account-scope-changed";
export const storageWarningEvent = "cryptorisk:storage-warning";
let accountScope = "guest";
let accountController = new AbortController();
let storageUnavailable = false;
export function hasStorageWarning() { return storageUnavailable; }
const privateKeys = new Set([
  "cryptorisk.analysisRecords", "cryptorisk.selectedRecordId", "cryptorisk.chatMessages",
  "cryptorisk.activeAnalysisTask", "cryptorisk.pendingNewsAnalysis", "cryptorisk.portfolio-refresh-job-id",
]);

export function getAccountScope() { return accountScope; }
export function getAccountSignal() { return accountController.signal; }
export function setAccountScope(userId: string | null) {
  const next = userId || "guest";
  if (accountScope === next) return;
  accountController.abort();
  accountController = new AbortController();
  accountScope = next;
  if (typeof window !== "undefined") window.dispatchEvent(new Event(accountScopeEvent));
}

export function subscribeAccountScope(listener: () => void) {
  window.addEventListener(accountScopeEvent, listener);
  return () => window.removeEventListener(accountScopeEvent, listener);
}

function createStorage(kind: "localStorage" | "sessionStorage") {
  const fallback = new Map<string, string | null>();
  let warned = false;
  const resolveKey = (key: string) => privateKeys.has(key) || key.startsWith("cryptorisk.portfolio-trades:")
    ? `${key}:v2:${accountScope}` : key;
  function warn() {
    storageUnavailable = true;
    if (warned || typeof window === "undefined") return;
    warned = true;
    window.dispatchEvent(new Event(storageWarningEvent));
  }
  return {
    getItem(key: string): string | null {
      if (typeof window === "undefined") return null;
      key = resolveKey(key);
      if (fallback.has(key)) return fallback.get(key) ?? null;
      try { return window[kind].getItem(key); }
      catch { warn(); return null; }
    },
    setItem(key: string, value: string) {
      if (typeof window === "undefined") return;
      key = resolveKey(key);
      try { window[kind].setItem(key, value); fallback.delete(key); }
      catch { fallback.set(key, value); warn(); }
    },
    removeItem(key: string) {
      if (typeof window === "undefined") return;
      key = resolveKey(key);
      try { window[kind].removeItem(key); fallback.delete(key); }
      catch { fallback.set(key, null); warn(); }
    },
    keys(): string[] {
      if (typeof window === "undefined") return [];
      try { return [...new Set([...Object.keys(window[kind]), ...fallback.keys()])]; }
      catch { return [...fallback.keys()]; }
    },
  };
}

export const localStore = createStorage("localStorage");
export const sessionStore = createStorage("sessionStorage");

export function clearCurrentAccountStorage() {
  for (const key of privateKeys) { localStore.removeItem(key); sessionStore.removeItem(key); }
  localStore.removeItem(`cryptorisk.globalAssistant.sessions:${accountScope}`);
  localStore.removeItem(`cryptorisk.globalAssistant.activeSession:${accountScope}`);
  localStore.removeItem(`cryptorisk.attackpilot-input:${accountScope}`);
  for (const key of localStore.keys()) {
    if (key.startsWith(`cryptorisk.attackpilot-assistant:${accountScope}:`)) {
      localStore.removeItem(key);
    }
    if (key.startsWith("cryptorisk.portfolio-trades:") && key.endsWith(`:v2:${accountScope}`)) {
      // keys() returns the physical key; avoid applying the scope twice.
      localStore.removeItem(key.slice(0, -`:v2:${accountScope}`.length));
    }
  }
}
