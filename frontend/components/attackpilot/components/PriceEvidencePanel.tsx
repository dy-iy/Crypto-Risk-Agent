import React, { useId, useMemo, useState } from "react";
import { Button, Drawer, Select, Tag } from "antd";
import { ArrowUpRight, ChevronLeft, ChevronRight, CircleDollarSign } from "lucide-react";
import type { Task } from "../types";
import {
  formatEvidenceAge,
  formatEvidencePrice,
  formatEvidenceTime,
  normalizePriceEvidence,
  shortEvidenceHash,
} from "../utils/priceEvidence";
import type { OraclePriceRow, ReferencePriceRow } from "../utils/priceEvidence";
import "../price-evidence.css";

type EvidenceModel = ReturnType<typeof normalizePriceEvidence>;
type Selection = { kind: "reference"; row: ReferencePriceRow } | { kind: "observed"; row: OraclePriceRow };
type EvidenceTab = Selection["kind"];

function protocolEmptyText(model: EvidenceModel): string {
  const coverage = model.protocolCoverage;
  if (!coverage) return "本次未保存协议读取证据。";
  if (coverage.disabledCount === coverage.transactionCount) return "本次未启用 Feed 调用扫描。";
  if (coverage.unavailableCount === coverage.transactionCount) return "本次未取得可核实的 Feed 调用轨迹。";
  if (!coverage.scanComplete || coverage.disabledCount || coverage.unavailableCount) return "读取证据不完整，无法确认已配置 Feed 的调用情况。";
  return "未在已扫描轨迹中观察到已配置 Feed 的读取。";
}

function Value({ value }: { value: string | number | null | undefined }) {
  return <span className="ap-price-value">{value ?? "—"}</span>;
}

function EvidenceDetails({ selected }: { selected: Selection }) {
  const { row } = selected;
  const fields: Array<[string, string | number | null | undefined]> = [
    ["交易", row.transactionHash], ["网络", row.chain], ["Feed", row.feedAddress],
    ["交易对", row.pair], ["轮次", row.roundId], ["原始报价整数", row.answer],
    ["报价精度", row.feedDecimals], ["交易时间（UTC）", formatEvidenceTime(row.requestedTimestamp)],
    ["更新时间（UTC）", formatEvidenceTime(row.updatedAt)], ["与交易时间差", formatEvidenceAge(row.ageSeconds)],
  ];
  if (selected.kind === "reference") {
    fields.splice(1, 0, ["估值资产", selected.row.symbol], ["资产地址", selected.row.tokenAddress], ["来源", selected.row.sourceLabel]);
    if (selected.row.usesWrappedNativeReference) {
      fields.push(["报价资产", selected.row.sourceAssetSymbol], ["报价资产地址", selected.row.sourceAssetAddress]);
    }
    fields.push(["代币精度", selected.row.tokenDecimals]);
    if (selected.row.configurationOrigin) fields.push(["Feed 配置", selected.row.configurationOrigin === "official_catalog" ? "官方目录" : "自定义映射"]);
    if (selected.row.source === "chainlink") fields.push(["交易时点代理启用", selected.row.proxyActivationVerified ? "已核实" : "未核实"]);
  } else {
    fields.push(["调用方法", selected.row.method], ["轨迹位置", selected.row.tracePosition],
      ["请求轮次", selected.row.requestedRoundId], ["完成轮次", selected.row.answeredInRound]);
    if (selected.row.identityStatus) fields.push(["Feed 地址", selected.row.identityStatus === "official_catalog_proxy" ? "匹配当前官方目录" : "自定义映射，身份未核实"]);
  }
  return <div className="ap-price-details">
    <div className="ap-price-detail-status"><Tag>{row.statusLabel}</Tag>{row.reason && <span>{row.reason}</span>}</div>
    <dl>{fields.map(([label, value]) => <div key={label}><dt>{label}</dt><dd><Value value={value} /></dd></div>)}</dl>
    {selected.kind === "reference" ? <p className="ap-price-note">历史参考价格，不代表协议实际读取的轮次。</p>
      : !selected.row.precisionEstablished ? <p className="ap-price-note">该轨迹未确认报价精度，仅保留原始整数。</p> : null}
    {row.sourceUrl && <a className="ap-price-source-link" href={row.sourceUrl} target="_blank" rel="noopener noreferrer">查看数据来源 <ArrowUpRight size={14} /></a>}
  </div>;
}

function PriceCard({ item, kind, onOpen }: {
  item: ReferencePriceRow | OraclePriceRow;
  kind: EvidenceTab;
  onOpen: () => void;
}) {
  const reference = kind === "reference" ? item as ReferencePriceRow : null;
  const observation = kind === "observed" ? item as OraclePriceRow : null;
  const hasPrice = item.status === "available" && item.price !== null;
  return <li className="ap-price-card">
    <div className="ap-price-card-heading">
      <strong>{reference?.symbol || item.pair || (reference ? shortEvidenceHash(reference.tokenAddress) : "Feed 调用")}</strong>
      <Tag color={reference?.source === "chainlink" ? "blue" : "default"}>{reference?.sourceLabel ?? "轨迹读取"}</Tag>
    </div>
    <div className="ap-price-card-quote">
      <span className={hasPrice ? "ap-price-amount" : "ap-price-unknown"}>{hasPrice ? formatEvidencePrice(item.price, item.priceExact) : "—"}</span>
      <span className={`ap-price-status is-${item.status}`}>{item.statusLabel}</span>
    </div>
    <div className="ap-price-card-time"><span>更新于 <time>{formatEvidenceTime(item.updatedAt)}</time></span><span>{formatEvidenceAge(item.ageSeconds)}</span></div>
    {item.reason && <p className="ap-price-card-reason">{item.reason}</p>}
    {observation && !observation.precisionEstablished && observation.answer && <div className="ap-price-raw-answer">原始整数 <Value value={observation.answer} /></div>}
    <dl className="ap-price-card-meta">
      <div><dt>交易</dt><dd title={item.transactionHash}>{shortEvidenceHash(item.transactionHash)}</dd></div>
      {item.feedAddress && <div><dt>Feed</dt><dd title={item.feedAddress}>{shortEvidenceHash(item.feedAddress)}</dd></div>}
      {item.roundId && <div><dt>轮次</dt><dd>{item.roundId}</dd></div>}
    </dl>
    <button type="button" className="ap-price-detail-button" aria-label={`查看${reference?.symbol || item.pair || "Feed 调用"}在交易 ${shortEvidenceHash(item.transactionHash)} 的价格证据详情`} onClick={onOpen}>证据详情 <ArrowUpRight size={14} /></button>
  </li>;
}

function PriceEvidenceContent({ model }: { model: EvidenceModel }) {
  const id = useId();
  const [tab, setTab] = useState<EvidenceTab>(model.referenceRows.length || !model.oracleRows.length ? "reference" : "observed");
  const [transaction, setTransaction] = useState("all");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Selection | null>(null);
  const rows = tab === "reference" ? model.referenceRows : model.oracleRows;
  const transactions = Array.from(new Set([...model.referenceRows, ...model.oracleRows].map(row => row.transactionHash)));
  const filtered = transaction === "all" ? rows : rows.filter(row => row.transactionHash === transaction);
  const pageCount = Math.max(1, Math.ceil(filtered.length / 4));
  const currentPage = Math.min(page, pageCount);
  const visible = filtered.slice((currentPage - 1) * 4, currentPage * 4);
  const changeTab = (value: EvidenceTab) => { setTab(value); setPage(1); };
  const onTabKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === "Home" ? "reference" : event.key === "End" ? "observed" : tab === "reference" ? "observed" : "reference";
    changeTab(next);
    document.getElementById(`${id}-${next}`)?.focus();
  };
  return <>
    <div className="ap-price-toolbar">
      <div className="ap-price-tabs" role="tablist" aria-label="价格证据类型">
        <button id={`${id}-reference`} type="button" role="tab" aria-controls={`${id}-panel`} tabIndex={tab === "reference" ? 0 : -1} aria-selected={tab === "reference"} onKeyDown={onTabKeyDown} onClick={() => changeTab("reference")}>历史参考价 <span>{model.referenceRows.length}</span></button>
        <button id={`${id}-observed`} type="button" role="tab" aria-controls={`${id}-panel`} tabIndex={tab === "observed" ? 0 : -1} aria-selected={tab === "observed"} onKeyDown={onTabKeyDown} onClick={() => changeTab("observed")}>协议实际读取 <span>{model.oracleRows.length}</span></button>
      </div>
      {transactions.length > 1 && <Select aria-label="按交易筛选价格证据" value={transaction} onChange={value => { setTransaction(value); setPage(1); }}
        options={[{ value: "all", label: "全部交易" }, ...transactions.map(hash => ({ value: hash, label: shortEvidenceHash(hash) }))]} />}
    </div>
    <div id={`${id}-panel`} role="tabpanel" aria-labelledby={`${id}-${tab}`} tabIndex={0}>
    <p className="ap-price-scope">{tab === "reference" ? "用于历史估值的参考报价。" : "来自原始交易执行轨迹，仅识别已配置 Feed 地址。"}</p>
    {visible.length ? <ul className="ap-price-grid">
      {visible.map(item => <PriceCard key={item.key} item={item} kind={tab} onOpen={() => setSelected(tab === "reference"
        ? { kind: "reference", row: item as ReferencePriceRow } : { kind: "observed", row: item as OraclePriceRow })} />)}
    </ul> : <p className="ap-price-empty">{tab === "reference" ? "本次未保存参考报价。" : transaction !== "all" ? "当前交易没有已记录的 Feed 读取。" : protocolEmptyText(model)}</p>}
    {tab === "observed" && visible.length > 0 && model.protocolCoverage && !model.protocolCoverage.scanComplete && <p className="ap-price-note">调用扫描未完整完成。</p>}
    {filtered.length > 4 && <div className="ap-price-pagination">
      <span>{filtered.length} 条记录</span>
      <Button aria-label="上一页价格证据" size="small" icon={<ChevronLeft size={14} />} disabled={currentPage === 1} onClick={() => setPage(currentPage - 1)} />
      <span>{currentPage} / {pageCount}</span>
      <Button aria-label="下一页价格证据" size="small" icon={<ChevronRight size={14} />} disabled={currentPage === pageCount} onClick={() => setPage(currentPage + 1)} />
    </div>}
    </div>
    <Drawer title={selected?.kind === "observed" ? "协议读取证据" : "历史价格证据"} open={Boolean(selected)} onClose={() => setSelected(null)}
      size="large" className="ap-price-drawer" getContainer={() => document.querySelector<HTMLElement>(".attackpilot-root") || document.body} destroyOnHidden>
      {selected && <EvidenceDetails selected={selected} />}
    </Drawer>
  </>;
}

export function buildPriceEvidenceMarkdown(task: Task | null): string {
  const model = normalizePriceEvidence(task);
  if (!model.available) return "";
  const lines = ["## 价格证据", "", "### 历史参考价", "", "以下为历史估值参考，不代表协议实际读取的轮次。", ""];
  for (const row of model.referenceRows) {
    lines.push(`- ${row.symbol || row.tokenAddress} · ${row.sourceLabel} · ${row.statusLabel}`,
      `  - 交易：${row.transactionHash}`, `  - 价格：${row.price === null ? "未知" : formatEvidencePrice(row.price, row.priceExact)}`,
      `  - 更新时间（UTC）：${formatEvidenceTime(row.updatedAt)}；与交易时间差：${formatEvidenceAge(row.ageSeconds)}`,
      `  - Feed：${row.feedAddress ?? "—"}；轮次：${row.roundId ?? "—"}`);
    if (row.usesWrappedNativeReference) lines.push(`  - 估值资产：${row.symbol}；报价资产：${row.sourceAssetSymbol ?? row.sourceAssetAddress}`);
    if (row.reason) lines.push(`  - ${row.reason}`);
  }
  lines.push("", "### 协议实际读取", "");
  lines.push("仅识别已配置 Feed 地址。", "");
  if (!model.oracleRows.length) lines.push(protocolEmptyText(model));
  for (const row of model.oracleRows) lines.push(`- 交易：${row.transactionHash} · ${row.method ?? "Feed 调用"} · ${row.statusLabel}`,
    `  - Feed：${row.feedAddress ?? "—"}；轮次：${row.roundId ?? "—"}`,
    `  - 原始报价整数：${row.answer ?? "—"}；轨迹确认的报价精度：${row.feedDecimals ?? "未知"}`,
    `  - 更新时间（UTC）：${formatEvidenceTime(row.updatedAt)}`, ...(row.reason ? [`  - ${row.reason}`] : []));
  if (model.oracleRows.length && model.protocolCoverage && !model.protocolCoverage.scanComplete) lines.push("", "调用扫描未完整完成。");
  return lines.join("\n");
}

export default function PriceEvidencePanel({ task }: { task: Task | null }) {
  const model = useMemo(() => normalizePriceEvidence(task), [task]);
  return <section className="ap-price-evidence" aria-label="价格证据">
    <div className="ap-price-heading"><h3><CircleDollarSign size={18} />价格证据</h3><span>Data Feeds</span></div>
    {model.available ? <PriceEvidenceContent key={task?.task_id} model={model} /> : <p className="ap-price-empty">{model.emptyReason ?? "本报告未保存价格证据。"}</p>}
  </section>;
}
