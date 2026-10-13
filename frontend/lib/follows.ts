"use client";

import { useEffect, useSyncExternalStore } from "react";
import { ApiRequestError, requestJson } from "./api";
import { accountScopeEvent, getAccountScope, getAccountSignal, localStore } from "./browser-storage";

export type Follow = { symbol: string; base_asset: string; name: string; alert_threshold: number; created_at: string; updated_at: string };
export type FollowSnapshot = { items: Follow[]; revision: string };
type State = FollowSnapshot & { scope: string; loading: boolean; loaded: boolean; pending: string[]; error: string };
const empty: State = { scope: "guest", items: [], revision: "", loading: false, loaded: false, pending: [], error: "" };
let state = empty;
let epoch = 0;
let lastLoad = 0;
let queue: Promise<unknown> = Promise.resolve();
const listeners = new Set<() => void>();
const guestKey = "cryptorisk.follows.guest";
let listening = false;
const emit = (update: Partial<State>) => { state = { ...state, ...update }; listeners.forEach(listener => listener()); };
const getSnapshot = () => state;
function followError(error: unknown) {
  if (error instanceof ApiRequestError && error.detail) return error.detail;
  return error instanceof Error && error.name === "TimeoutError" ? "关注请求超时，请重试" : "关注同步失败，请检查网络后重试";
}
const getServerSnapshot = () => empty;

export function parseFollowSnapshot(value: unknown): FollowSnapshot {
  if (!value || typeof value !== "object" || !("items" in value) || !Array.isArray(value.items) || !("revision" in value) || typeof value.revision !== "string") throw new Error("关注数据格式异常");
  const items: Follow[] = [];
  for (const item of value.items) {
    if (!item || typeof item.symbol !== "string" || !/^[A-Z0-9]{1,20}USDT$/.test(item.symbol) || typeof item.base_asset !== "string" || typeof item.name !== "string" || typeof item.created_at !== "string" || typeof item.updated_at !== "string" || !Number.isInteger(item.alert_threshold) || item.alert_threshold < 0 || item.alert_threshold > 100) throw new Error("关注数据格式异常");
    items.push({ symbol: item.symbol, base_asset: item.base_asset, name: item.name, created_at: item.created_at, updated_at: item.updated_at, alert_threshold: item.alert_threshold });
  }
  return { items: [...new Map(items.map(item => [item.symbol, item])).values()], revision: value.revision };
}

export function readGuestFollows(): string[] {
  try {
    const saved = localStore.getItem(guestKey);
    const legacy = JSON.parse(localStore.getItem("cryptorisk.market.preferences:guest") || "null");
    const value: unknown = saved === null ? legacy?.favorites ?? ["BTCUSDT", "ETHUSDT", "SOLUSDT"] : JSON.parse(saved);
    return Array.isArray(value) ? [...new Set(value.filter((s): s is string => typeof s === "string" && /^[A-Z0-9]{1,20}USDT$/.test(s)))].slice(0, 200) : [];
  } catch { return []; }
}
const guestItems = () => readGuestFollows().map(symbol => ({ symbol, base_asset: symbol.slice(0, -4), name: symbol.slice(0, -4), alert_threshold: 70, created_at: "", updated_at: "" }));
function synchronizeScope() {
  const scope = getAccountScope();
  if (state.scope !== scope) { epoch++; queue = Promise.resolve(); state = { ...empty, scope }; lastLoad = 0; }
  if (scope === "guest") emit({ items: guestItems(), revision: "local", loading: false, loaded: true, pending: [], error: "" });
  else void refreshFollows();
}
function subscribe(listener: () => void) {
  listeners.add(listener);
  if (!listening) {
    listening = true;
    window.addEventListener(accountScopeEvent, synchronizeScope);
    window.addEventListener("focus", () => { if (listeners.size && !document.hidden) void refreshFollows(); });
    window.addEventListener("storage", event => { if (event.key === guestKey && getAccountScope() === "guest") synchronizeScope(); });
  }
  return () => { listeners.delete(listener); };
}
export async function refreshFollows(force = false) {
  const scope = getAccountScope();
  if (state.scope !== scope) { synchronizeScope(); return; }
  if (scope === "guest" || state.loading || state.pending.length || (!force && state.loaded && Date.now() - lastLoad < 30_000)) return;
  const version = ++epoch;
  emit({ loading: true, error: "" });
  try {
    const response = await requestJson<unknown>("/api/follows", { signal: AbortSignal.any([getAccountSignal(), AbortSignal.timeout(15_000)]) });
    const result = parseFollowSnapshot(response);
    if (scope === getAccountScope() && version === epoch) { lastLoad = Date.now(); emit({ ...result, loaded: true }); }
  } catch (error) {
    if (scope === getAccountScope() && version === epoch) emit({ error: followError(error) });
  } finally { if (scope === getAccountScope() && version === epoch) emit({ loading: false }); }
}
export function useFollows() {
  const snapshot = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  useEffect(() => { synchronizeScope(); }, []);
  return snapshot;
}
export async function changeFollow(symbol: string, action: "add" | "remove" | "threshold", threshold?: number): Promise<boolean> {
  const scope = getAccountScope();
  if (state.scope !== scope || state.pending.includes(symbol) || state.loading || !state.loaded) return false;
  if (scope === "guest") {
    if (action === "threshold") { emit({ error: "登录后可保存日报风险阈值" }); return false; }
    const values = readGuestFollows();
    localStore.setItem(guestKey, JSON.stringify(action === "add" ? [...new Set([...values, symbol])] : values.filter(value => value !== symbol)));
    emit({ items: guestItems(), loaded: true, error: "" });
    return true;
  }
  epoch++; // A read begun before this mutation cannot replace the new snapshot.
  const signal = getAccountSignal();
  emit({ pending: [...state.pending, symbol], error: "" });
  let success = false;
  queue = queue.then(async () => {
    if (signal.aborted) return;
    try {
      const response = await requestJson<unknown>(action === "add" ? "/api/follows" : `/api/follows/${encodeURIComponent(symbol)}`, {
        method: action === "add" ? "POST" : action === "remove" ? "DELETE" : "PATCH",
        body: action === "remove" ? undefined : JSON.stringify(action === "add" ? { symbol } : { alert_threshold: threshold }),
        signal: AbortSignal.any([signal, AbortSignal.timeout(15_000)]),
      });
      const result = parseFollowSnapshot(response);
      if (!signal.aborted && scope === getAccountScope()) { lastLoad = Date.now(); emit({ ...result, loaded: true }); success = true; }
    } catch (error) { if (!signal.aborted && scope === getAccountScope()) emit({ error: followError(error) }); }
    finally { if (!signal.aborted && scope === getAccountScope()) emit({ pending: state.pending.filter(value => value !== symbol) }); }
  });
  await queue;
  return success;
}
