"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { fetchCoinLibrary, type CoinLibraryItem } from "@/lib/api";
import { getAccountSignal } from "@/lib/browser-storage";
import { changeFollow, readGuestFollows, refreshFollows, useFollows, type Follow } from "@/lib/follows";
import { marketSymbols, normalizeMarketSymbol } from "@/lib/market-symbols";

const button = "rounded-lg border border-blue-200 px-3 py-2 text-sm font-semibold text-blue-700 hover:bg-blue-50 disabled:opacity-50 disabled:cursor-not-allowed";
export function GuestFollowImport() {
  const follows = useFollows();
  const [open, setOpen] = useState(false), [selected, setSelected] = useState<string[]>([]), [busy, setBusy] = useState(false), [message, setMessage] = useState("");
  if (follows.scope === "guest") return null;
  const candidates = readGuestFollows().filter(symbol => !follows.items.some(item => item.symbol === symbol));
  async function importSelected() {
    if (busy || !selected.length) return;
    const signal = getAccountSignal();
    setBusy(true); setMessage("");
    let count = 0;
    const failed: string[] = [];
    for (const symbol of selected) {
      if (signal.aborted) return;
      if (await changeFollow(symbol, "add")) count++; else failed.push(symbol);
    }
    if (signal.aborted) return;
    setSelected(failed); setBusy(false); setMessage(`已导入 ${count} 个币种${failed.length ? `，${failed.length} 个失败，可重试` : ""}`);
  }
  return <div className="space-y-3">
    <button className={button} aria-expanded={open} onClick={() => setOpen(value => !value)} disabled={busy}>导入本地自选</button>
    {open && <div className="rounded-lg border border-blue-100 bg-blue-50/50 p-4 space-y-3">
      <p className="text-sm text-slate-600">勾选后才会加入账号关注并用于日报；不会覆盖现有关注。</p>
      <div className="flex flex-wrap gap-4">{candidates.map(symbol => <label key={symbol} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={selected.includes(symbol)} disabled={busy} onChange={event => setSelected(values => event.target.checked ? [...values, symbol] : values.filter(value => value !== symbol))}/>{symbol}</label>)}</div>
      {!candidates.length && <p className="text-sm text-slate-500">没有尚未导入的本地自选。</p>}
      <button className={button} disabled={busy || !selected.length || follows.loading || !follows.loaded} onClick={() => void importSelected()}>{busy ? "导入中…" : "导入所选"}</button>
      {message && <p role="status" className="text-sm text-slate-700">{message}</p>}
    </div>}
  </div>;
}

export default function FollowManager({ onLogin }: { onLogin: () => void }) {
  const follows = useFollows();
  const [coins, setCoins] = useState<CoinLibraryItem[]>([]), [query, setQuery] = useState(""), [coinError, setCoinError] = useState(""), [retry, setRetry] = useState(0);
  const [coinsLoading, setCoinsLoading] = useState(true);
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    fetchCoinLibrary(undefined, 200, AbortSignal.any([controller.signal, AbortSignal.timeout(15_000)])).then(items => { if (!Array.isArray(items)) throw new Error("币种库格式异常"); if (active) { setCoins(items); setCoinError(""); } }).catch(() => { if (active) setCoinError("币种库读取失败，请重试"); }).finally(() => { if (active) setCoinsLoading(false); });
    return () => { active = false; controller.abort(); };
  }, [retry]);
  const needle = query.trim().toLowerCase();
  const matches = (symbol: string, name: string) => `${symbol} ${name}`.toLowerCase().includes(needle);
  const remaining = coins.filter(coin => !follows.items.some(item => item.symbol === coin.symbol) && matches(coin.symbol, coin.name));
  return <section className="space-y-4" aria-label="关注币种管理">
    <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-xl font-bold text-slate-950">我的关注</h2><p className="mt-1 text-sm text-slate-500">关注列表同步用于行情看盘与个性化日报。</p></div><Link href="/daily" className={button}>查看关注日报</Link></div>
    {follows.scope === "guest" ? <div className="rounded-lg bg-blue-50 p-3 text-sm text-blue-900">游客自选仅保存在当前浏览器。<button onClick={onLogin} className="ml-2 font-bold underline">登录后同步并生成日报</button></div> : <GuestFollowImport key={follows.scope}/>}
    {(coinError || follows.error) && <div role="alert" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">{follows.error || coinError}<button className="ml-2 underline" onClick={() => { setCoinsLoading(true); setRetry(v => v + 1); void refreshFollows(true); }}>重试</button></div>}
    <label className="block"><span className="text-sm font-semibold text-slate-700">搜索完整币种库</span><input aria-label="搜索关注币种" value={query} onChange={event => setQuery(event.target.value)} placeholder="输入币种名称或代码" className="mt-2 w-full rounded-lg border border-blue-200 bg-white px-3 py-2 text-base outline-none focus:ring-2 focus:ring-blue-200"/></label>
    <div className="flex items-center justify-between"><h3 className="font-semibold text-slate-800">已关注 · {follows.items.length}</h3><button className={button} onClick={() => void refreshFollows(true)} disabled={follows.loading}>刷新关注</button></div>
    {follows.loading && <p role="status" className="text-sm text-slate-500">正在同步关注…</p>}
    {!follows.loading && !follows.items.length && <p className="rounded-lg bg-slate-50 p-4 text-sm text-slate-500">尚未关注币种，可从下方币种库添加。</p>}
    <div className="grid gap-3 xl:grid-cols-2">{follows.items.filter(item => matches(item.symbol, item.name)).map(item => <FollowRow key={item.symbol} item={item} busy={follows.pending.includes(item.symbol)} guest={follows.scope === "guest"}/>)}</div>
    {coinsLoading && <p role="status" className="text-sm text-slate-500">正在读取币种库…</p>}
    <h3 className="font-semibold text-slate-800">添加关注 · {remaining.length} 个匹配币种</h3>
    <div className="max-h-80 overflow-y-auto rounded-lg border border-blue-100 divide-y divide-blue-50">{remaining.map(coin => <div key={coin.symbol} className="flex items-center justify-between gap-3 px-3 py-3"><div className="min-w-0"><p className="break-words text-sm font-semibold">{coin.base_asset} · {coin.name}</p><p className="text-xs text-slate-500">{marketSymbols.includes(coin.symbol) ? "支持行情看盘" : "暂不支持行情 · 可关注风险资讯"}</p></div><button className={button + " shrink-0"} disabled={follows.loading || !follows.loaded || follows.pending.includes(coin.symbol)} onClick={() => void changeFollow(coin.symbol, "add")} aria-label={`关注 ${coin.base_asset}`}>{follows.pending.includes(coin.symbol) ? "保存中" : "关注"}</button></div>)}</div>
  </section>;
}
function FollowRow({ item, busy, guest }: { item: Follow; busy: boolean; guest: boolean }) {
  const [draft, setDraft] = useState<string | null>(null);
  const threshold = draft ?? String(item.alert_threshold);
  const [message, setMessage] = useState("");
  const market = normalizeMarketSymbol(item.symbol);
  return <article className="min-w-0 rounded-lg border border-blue-100 bg-white p-4 space-y-3">
    <div className="flex items-start justify-between gap-3"><div className="min-w-0 flex-1"><h3 className="font-bold [overflow-wrap:anywhere]">{item.base_asset} <span className="text-sm font-normal text-slate-500">{item.name}</span></h3><p className="mt-1 text-xs text-slate-500">{market ? "支持行情看盘" : "暂不支持行情"}</p></div><button className={button + " shrink-0"} disabled={busy} onClick={() => void changeFollow(item.symbol, "remove")} aria-label={`取消关注 ${item.base_asset}`}>{busy ? "保存中" : "取消关注"}</button></div>
    <div className="flex flex-wrap gap-3 text-sm text-blue-700">{market && <Link href={`/market?symbol=${market}`}>查看行情</Link>}<Link href={`/coins/${encodeURIComponent(item.base_asset)}?returnTo=${encodeURIComponent("/my?tab=assets")}`}>风险信息</Link></div>
    {!guest && <form className="flex flex-wrap items-center gap-2" onSubmit={async event => { event.preventDefault(); const signal = getAccountSignal(); setMessage(""); const ok = await changeFollow(item.symbol, "threshold", Number(threshold)); if (!signal.aborted && ok) { setDraft(null); setMessage("风险阈值已保存"); } }}><label className="text-sm text-slate-600">日报风险阈值 <input aria-label={`${item.base_asset} 风险阈值`} type="number" min={0} max={100} step={1} required value={threshold} onChange={event => setDraft(event.target.value)} className="ml-2 w-20 rounded border border-blue-200 p-1"/></label><button className={button} disabled={busy}>保存</button>{message && <span role="status" className="text-sm text-emerald-700">{message}</span>}</form>}
  </article>;
}
