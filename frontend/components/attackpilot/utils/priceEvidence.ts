import type { Task } from "../types";

type RecordValue = Record<string, unknown>;
export type ReferencePriceStatus = "available" | "stale" | "ambiguous" | "unavailable";

export interface ReferencePriceRow {
  key: string;
  transactionHash: string;
  tokenAddress: string;
  chain: string;
  symbol: string;
  sourceAssetAddress: string | null;
  sourceAssetSymbol: string | null;
  usesWrappedNativeReference: boolean;
  pair: string | null;
  source: "chainlink" | "defillama" | "unavailable";
  sourceLabel: string;
  status: ReferencePriceStatus;
  statusLabel: string;
  reasonCode: string | null;
  reason: string | null;
  price: number | null;
  priceExact: string | null;
  requestedTimestamp: number | null;
  updatedAt: number | null;
  ageSeconds: number | null;
  feedAddress: string | null;
  roundId: string | null;
  answer: string | null;
  answeredInRound: string | null;
  feedDecimals: number | null;
  tokenDecimals: number | null;
  sourceUrl: string | null;
  configurationOrigin: string | null;
  transactionStateVerified: boolean;
  proxyActivationVerified: boolean;
}

export interface OraclePriceRow {
  key: string;
  transactionHash: string;
  feedAddress: string | null;
  pair: string | null;
  chain: string;
  method: string;
  tracePosition: string | null;
  sourceUrl: string | null;
  roundId: string | null;
  answer: string | null;
  answeredInRound: string | null;
  requestedRoundId: string | null;
  feedDecimals: number | null;
  configuredFeedDecimals: number | null;
  precisionEstablished: boolean;
  price: number | null;
  priceExact: string | null;
  requestedTimestamp: number | null;
  updatedAt: number | null;
  ageSeconds: number | null;
  status: "available" | "unavailable" | "stale" | "future" | "invalid";
  statusLabel: string;
  reasonCode: string | null;
  reason: string | null;
  identityStatus: string | null;
  identityScope: string | null;
  roundIntegrityCheck: string | null;
  freshnessCheck: string | null;
  simulationId: string | null;
}

export interface PriceEvidenceCoverage {
  transactionCount: number;
  observedTransactionCount: number;
  notObservedCount: number;
  unavailableCount: number;
  disabledCount: number;
  incompleteCount: number;
  scanComplete: boolean;
  configuredProxiesOnly: boolean;
  absenceIsNotProof: boolean;
}

export interface PriceEvidencePresentation {
  available: boolean;
  referenceRows: ReferencePriceRow[];
  oracleRows: OraclePriceRow[];
  protocolCoverage: PriceEvidenceCoverage | null;
  emptyReason: string | null;
}

function record(value: unknown): RecordValue | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as RecordValue : null;
}

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function lower(value: unknown): string | null {
  return text(value)?.toLowerCase() ?? null;
}

function integer(value: unknown, minimum = 0, maximum = Number.MAX_SAFE_INTEGER): number | null {
  if (typeof value !== "number" && (typeof value !== "string" || !/^\d+$/.test(value))) return null;
  const number = Number(value);
  return Number.isSafeInteger(number) && number >= minimum && number <= maximum ? number : null;
}

function timestamp(value: unknown): number | null {
  // Millisecond conversion must also remain within JavaScript Date's range.
  return integer(value, 1, 8_640_000_000_000);
}

function identifier(value: unknown, signed = false): string | null {
  if (typeof value === "number") return Number.isSafeInteger(value) && (signed || value >= 0) ? String(value) : null;
  const raw = text(value);
  if (!raw || !(signed ? /^-?\d+$/ : /^\d+$/).test(raw)) return null;
  return raw;
}

function positive(value: unknown): number | null {
  if (typeof value !== "number" && (typeof value !== "string" || !/^(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$/i.test(value))) return null;
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : null;
}

function exactPrice(value: unknown): string | null {
  const raw = text(value);
  return raw && positive(raw) !== null ? raw : null;
}

function chainName(value: unknown): string {
  const name = lower(value);
  if (["1", "ethereum", "eth"].includes(name ?? "") || value === 1) return "Ethereum";
  if (["56", "bsc", "bnbchain", "bnb", "bscchain"].includes(name ?? "") || value === 56) return "BNB Chain";
  return text(value) ?? "未知网络";
}

const nativeAliases = new Set(["0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee", "0x0000000000000000000000000000000000000000"]);
const nativeAssets: Record<string, { symbol: string; wrapped: string }> = {
  Ethereum: { symbol: "ETH", wrapped: "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2" },
  "BNB Chain": { symbol: "BNB", wrapped: "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c" },
};

/** Only documented public sources may become links; RPC URLs never do. */
export function safePriceEvidenceUrl(value: unknown): string | null {
  const raw = text(value);
  if (!raw) return null;
  try {
    const url = new URL(raw);
    if (url.protocol !== "https:" || url.username || url.password || (url.port && url.port !== "443")) return null;
    const allowed = ["data.chain.link", "docs.chain.link", "reference-data-directory.vercel.app", "coins.llama.fi"];
    if (!allowed.includes(url.hostname) || url.hash) return null;
    if (url.hostname !== "coins.llama.fi" && url.search) return null;
    if (url.hostname === "coins.llama.fi") {
      if (!url.pathname.startsWith("/prices/historical/")) return null;
      for (const [key, item] of url.searchParams) {
        if (key !== "searchWidth" || !/^[1-9]\d*[mhd]$/.test(item)) return null;
      }
    }
    return url.href;
  } catch {
    return null;
  }
}

const reasonLabels: Record<string, string> = {
  missing_quote: "未取得历史报价",
  historical_aggregator_metadata_unavailable: "历史聚合器元数据接口不可读取，不能确认该阶段的历史参考价",
  historical_block_context_mismatch: "历史区块信息与交易不一致",
  invalid_block_context: "缺少有效历史区块信息",
  contract_call_reverted: "预言机合约调用回滚",
  missing_timestamp: "缺少实际报价时间",
  invalid_timestamp: "交易时间无效",
  future_quote: "报价晚于交易时间",
  future_timestamp: "请求时间晚于查询区块",
  stale_quote: "报价超过时效规则",
  stale_reference_round: "参考轮次超过时效规则",
  unsupported_asset: "未覆盖该资产",
  feed_not_configured: "未配置对应 Feed",
  chainlink_disabled: "Chainlink 查询未启用",
  configuration_error: "喂价配置异常",
  invalid_feed_configuration: "喂价配置异常",
  price_service_unavailable: "价格服务暂不可用",
  quote_deadline_exceeded: "历史报价查询超时",
  rpc_budget_exceeded: "历史报价查询达到请求上限",
  no_usable_rpc: "没有可用的查询节点",
  invalid_answer: "报价返回值无效",
  invalid_price: "报价返回值无效",
  invalid_round: "轮次数据无效",
  invalid_round_timestamp: "轮次时间异常",
  invalid_response: "报价返回数据异常",
  missing_trace: "缺少可核实的执行轨迹",
  oracle_call_reverted: "预言机调用回退",
  invalid_oracle_output: "预言机返回数据无效",
  precision_not_established: "轨迹中未核实喂价精度",
  round_integrity_invalid: "轮次完整性校验未通过",
  freshness_unknown: "无法核实报价时效",
  temporal_ambiguity: "时间精度不足以确定先后顺序",
  timestamp_order_ambiguous: "时间精度不足以确定先后顺序",
  exact_timestamp_ambiguous: "时间精度不足以确定先后顺序",
  incomplete_evidence: "报价证据不完整",
  invalid_evidence: "报价证据存在冲突",
};

function reasonText(code: string | null): string | null {
  if (!code) return null;
  if (Object.hasOwn(reasonLabels, code)) return reasonLabels[code];
  if (/ambig|same_second/.test(code)) return "时间精度不足以确定先后顺序";
  if (/^rpc_|unavailable|missing_|not_found|history_|phase_|round_/.test(code)) return "历史报价证据不足";
  return "当前报价无法核实";
}

function referenceRow(transactionHash: string, tokenAddress: string, quote: RecordValue): ReferencePriceRow {
  const sourceValue = lower(quote.source);
  const source = sourceValue === "chainlink" || sourceValue === "defillama" ? sourceValue : "unavailable";
  const oracle = record(quote.chainlink);
  const details = source === "chainlink" ? { ...oracle, ...quote } : quote;
  const chain = chainName(details.chain ?? details.chain_id ?? details.network_id);
  const valuationAsset = record(quote.valuation_asset);
  const sourceAsset = record(quote.source_asset);
  const sourceAssetAddress = lower(sourceAsset?.contract_address) ?? lower(details.contract_address);
  const sourceAssetSymbol = text(sourceAsset?.symbol) ?? text(details.symbol) ?? text(details.token_symbol);
  const isNative = nativeAliases.has(tokenAddress);
  const nativeAsset = Object.hasOwn(nativeAssets, chain) ? nativeAssets[chain] : null;
  const knownChains = [details.chain, details.chain_id, details.network_id, sourceAsset?.chain, valuationAsset?.chain]
    .filter(value => value !== undefined && value !== null).map(chainName);
  const sourceMatchesNative = nativeAsset !== null && sourceAssetAddress !== null
    && (nativeAliases.has(sourceAssetAddress) || sourceAssetAddress === nativeAsset.wrapped);
  const valuationAddress = lower(valuationAsset?.contract_address);
  const nativeIdentityConflicts = isNative && (!sourceMatchesNative || knownChains.some(value => value !== chain)
    || (valuationAddress !== null && !nativeAliases.has(valuationAddress)));
  const requestedTimestamp = timestamp(details.requested_timestamp);
  const updatedAt = timestamp(details.timestamp ?? details.updated_at);
  const price = positive(quote.price);
  const ageSeconds = requestedTimestamp !== null && updatedAt !== null ? requestedTimestamp - updatedAt : null;
  const quoteStatus = lower(quote.quote_status);
  const backendStatus = lower(details.status);
  const roundId = identifier(details.round_id);
  const answer = identifier(details.answer, true);
  const answeredInRound = identifier(details.answered_in_round);
  const priceExact = exactPrice(details.price_exact);
  let reasonCode = lower(quote.reason_code) ?? lower(details.reason_code) ?? lower(details.reason);
  let available = source !== "unavailable" && lower(quote.valuation_status) === "available"
    && price !== null && ageSeconds !== null && ageSeconds >= 0
    && (quoteStatus === null || quoteStatus === "available");
  if (source === "chainlink") {
    available = available && backendStatus === "available" && (!oracle || lower(oracle.status) === "available");
    // Reject contradictory returned evidence even if an upstream flag says
    // available. Large identifiers are compared without Number conversion.
    const invalidRound = (details.round_id !== undefined && (roundId === null || BigInt(roundId) <= BigInt(0)))
      || (details.answer !== undefined && (answer === null || BigInt(answer) <= BigInt(0)))
      || (details.answered_in_round !== undefined && (answeredInRound === null
        || (roundId !== null && BigInt(answeredInRound) < BigInt(roundId))));
    const reportedUpdatedAt = timestamp(details.updated_at);
    const startedAt = timestamp(details.started_at);
    if (invalidRound || (reportedUpdatedAt !== null && updatedAt !== null && reportedUpdatedAt !== updatedAt)
      || (startedAt !== null && updatedAt !== null && startedAt > updatedAt)
      || (priceExact !== null && price !== null && Number(priceExact) !== price)) {
      available = false;
      reasonCode = "invalid_evidence";
    }
  }
  if (nativeIdentityConflicts) {
    available = false;
    reasonCode = "invalid_evidence";
  }
  if (ageSeconds !== null && ageSeconds < 0) {
    available = false;
    reasonCode = "future_quote";
  }
  const maxAge = integer(details.max_age_seconds, 1);
  if (ageSeconds !== null && maxAge !== null && ageSeconds > maxAge) {
    available = false;
    reasonCode = "stale_reference_round";
  }
  const explicitCaveat = reasonCode !== null || [backendStatus, quoteStatus].some((status) => status !== null && status !== "available");
  if (explicitCaveat) available = false;
  if (!available && reasonCode === null) reasonCode = "incomplete_evidence";
  const status: ReferencePriceStatus = available ? "available"
    : /stale/.test(reasonCode ?? "") || backendStatus === "stale" || quoteStatus === "stale" ? "stale"
      : /ambig|same_second/.test(reasonCode ?? "") || backendStatus === "ambiguous" || quoteStatus === "ambiguous" ? "ambiguous"
        : "unavailable";
  return {
    key: `${transactionHash}:${tokenAddress}`,
    transactionHash,
    tokenAddress,
    chain,
    symbol: isNative ? nativeAsset?.symbol ?? "原生资产" : text(valuationAsset?.symbol) ?? sourceAssetSymbol ?? "未知资产",
    sourceAssetAddress,
    sourceAssetSymbol,
    usesWrappedNativeReference: isNative && sourceMatchesNative && sourceAssetAddress === nativeAsset?.wrapped,
    pair: text(details.pair),
    source,
    sourceLabel: source === "chainlink" ? "Chainlink" : source === "defillama" ? "DefiLlama" : "未知来源",
    status,
    statusLabel: { available: "可核实", stale: "已过期", ambiguous: "时序不确定", unavailable: "无法核实" }[status],
    reasonCode,
    reason: available ? null : reasonText(reasonCode),
    price: available ? price : null,
    // Preserve the provider's exact value for audit/export. Usability is
    // represented by status and price, never by the presence of this string.
    priceExact,
    requestedTimestamp,
    updatedAt,
    ageSeconds,
    feedAddress: lower(details.feed_address) ?? lower(details.proxy_address),
    roundId,
    answer,
    answeredInRound,
    feedDecimals: integer(details.feed_decimals, 0, 255),
    tokenDecimals: isNative && nativeAsset ? 18 : integer(valuationAsset?.decimals ?? details.token_decimals ?? details.decimals, 0, 255),
    sourceUrl: safePriceEvidenceUrl(details.source_url),
    configurationOrigin: text(details.configuration_origin),
    transactionStateVerified: details.transaction_state_verified === true,
    proxyActivationVerified: details.proxy_activation_verified === true,
  };
}

function scaledAnswer(answer: string, decimals: number): string {
  const digits = answer.replace(/^0+(?=\d)/, "");
  if (decimals === 0) return digits;
  const padded = digits.padStart(decimals + 1, "0");
  return `${padded.slice(0, -decimals)}.${padded.slice(-decimals)}`;
}

function oracleRow(transactionHash: string, value: RecordValue, index: number): OraclePriceRow {
  const roundId = identifier(value.round_id);
  const answer = identifier(value.answer, true);
  const answeredInRound = identifier(value.answered_in_round);
  const requestedRoundId = identifier(value.requested_round_id);
  const feedDecimals = integer(value.feed_decimals, 0, 36);
  const precisionEstablished = value.precision_evidence === "same_transaction_read" && feedDecimals !== null;
  const requestedTimestamp = timestamp(value.requested_timestamp);
  const updatedAt = timestamp(value.updated_at);
  const startedAt = timestamp(value.started_at);
  const ageSeconds = requestedTimestamp !== null && updatedAt !== null ? requestedTimestamp - updatedAt : null;
  const method = text(value.method) ?? "未知调用";
  const freshnessPolicy = integer(value.freshness_policy_seconds, 1);
  const exact = answer && /^\d+$/.test(answer) && precisionEstablished ? scaledAnswer(answer, feedDecimals!) : null;
  let reasonCode = lower(value.reason_code);
  let status: OraclePriceRow["status"] = "unavailable";
  const validRound = value.round_integrity_check === "valid" && roundId !== null && answeredInRound !== null
    && BigInt(roundId) > BigInt(0) && BigInt(answeredInRound) >= BigInt(roundId)
    && startedAt !== null && updatedAt !== null && startedAt <= updatedAt
    && (method !== "getRoundData" || (requestedRoundId !== null && BigInt(requestedRoundId) === BigInt(roundId)));
  const validAnswer = value.answer_check === "valid" && answer !== null && /^\d+$/.test(answer) && BigInt(answer) > BigInt(0);
  if (lower(value.status) === "observed" && reasonCode === null) {
    if (!validRound) {
      status = "invalid";
      reasonCode = "round_integrity_invalid";
    } else if (!validAnswer) {
      status = "invalid";
      reasonCode = "invalid_answer";
    } else if (value.freshness_check === "future" || (ageSeconds !== null && ageSeconds < 0)) {
      status = "future";
      reasonCode = "future_quote";
    } else if (value.freshness_check === "stale" || (ageSeconds !== null && freshnessPolicy !== null && ageSeconds > freshnessPolicy)) {
      status = "stale";
      reasonCode = "stale_quote";
    } else if (value.freshness_check !== "within_application_policy" || ageSeconds === null || freshnessPolicy === null) {
      reasonCode = "freshness_unknown";
    } else if (!precisionEstablished) {
      reasonCode = "precision_not_established";
    } else if (exact === null || positive(exact) === null) {
      status = "invalid";
      reasonCode = "invalid_answer";
    } else {
      status = "available";
    }
  }
  if (status === "unavailable" && reasonCode === null) reasonCode = "incomplete_evidence";
  return {
    key: `${transactionHash}:${index}:${lower(value.feed_address) ?? "unknown"}`,
    transactionHash,
    feedAddress: lower(value.feed_address),
    pair: text(value.pair),
    chain: chainName(value.network_id ?? value.chain_id ?? value.chain),
    method,
    tracePosition: typeof value.trace_position === "number" ? String(value.trace_position) : text(value.trace_position),
    sourceUrl: safePriceEvidenceUrl(value.source_url),
    roundId,
    answer,
    answeredInRound,
    requestedRoundId,
    feedDecimals,
    configuredFeedDecimals: integer(value.configured_feed_decimals, 0, 255),
    precisionEstablished,
    price: status === "available" ? positive(exact) : null,
    priceExact: status === "available" ? exact : null,
    requestedTimestamp,
    updatedAt,
    ageSeconds,
    status,
    statusLabel: { available: "已核实读取", unavailable: "无法核实", stale: "已过期", future: "时间异常", invalid: "数据异常" }[status],
    reasonCode,
    reason: status === "available" ? null : reasonText(reasonCode),
    identityStatus: text(value.identity_status),
    identityScope: text(value.identity_scope),
    roundIntegrityCheck: text(value.round_integrity_check),
    freshnessCheck: text(value.freshness_check),
    simulationId: text(value.simulation_id),
  };
}

/** Structured evidence only: report prose never establishes a price or source. */
export function normalizePriceEvidence(task: Task | null): PriceEvidencePresentation {
  const evidence = record(record(task?.result)?.price_evidence);
  if (!evidence || evidence.schema_version !== 1) {
    return { available: false, referenceRows: [], oracleRows: [], protocolCoverage: null,
      emptyReason: evidence ? "价格证据格式暂不支持。" : "本次任务未记录结构化价格证据。" };
  }
  const references = new Map<string, ReferencePriceRow>();
  for (const [rawTransaction, rawAssets] of Object.entries(record(evidence.reference_prices) ?? {})) {
    const transactionHash = rawTransaction.toLowerCase();
    for (const [rawToken, rawQuote] of Object.entries(record(rawAssets) ?? {})) {
      const quote = record(rawQuote);
      if (!quote) continue;
      const tokenAddress = rawToken.toLowerCase();
      const row = referenceRow(transactionHash, tokenAddress, quote);
      references.set(row.key, row);
    }
  }
  const oracleRows: OraclePriceRow[] = [];
  const protocols = new Map<string, RecordValue>();
  for (const [tx, raw] of Object.entries(record(evidence.protocol_oracle_reads) ?? {})) {
    const protocol = record(raw);
    if (protocol) protocols.set(tx.toLowerCase(), protocol);
  }
  const coverage: PriceEvidenceCoverage = {
    transactionCount: protocols.size, observedTransactionCount: 0, notObservedCount: 0,
    unavailableCount: 0, disabledCount: 0, incompleteCount: 0,
    scanComplete: protocols.size > 0, configuredProxiesOnly: true, absenceIsNotProof: true,
  };
  for (const [transactionHash, protocol] of protocols) {
    if (protocol.schema_version !== 1) {
      coverage.unavailableCount += 1;
      coverage.incompleteCount += 1;
      coverage.scanComplete = false;
      continue;
    }
    if (protocol.status === "observed") coverage.observedTransactionCount += 1;
    else if (protocol.status === "not_observed") coverage.notObservedCount += 1;
    else if (protocol.status === "disabled") coverage.disabledCount += 1;
    else coverage.unavailableCount += 1;
    if (protocol.scan_complete !== true) {
      coverage.scanComplete = false;
      coverage.incompleteCount += 1;
    }
    // These boundaries are conservative even for older evidence missing flags.
    if (protocol.scope && protocol.scope !== "configured_proxy_addresses_only") coverage.configuredProxiesOnly = false;
    if (!Array.isArray(protocol.observations)) continue;
    protocol.observations.forEach((observation, index) => {
      const value = record(observation);
      if (value) oracleRows.push(oracleRow(transactionHash, value, index));
    });
  }
  const referenceRows = Array.from(references.values());
  return {
    available: referenceRows.length > 0 || oracleRows.length > 0 || protocols.size > 0,
    referenceRows,
    oracleRows,
    protocolCoverage: protocols.size > 0 ? coverage : null,
    emptyReason: referenceRows.length || oracleRows.length ? null : "本次任务未记录价格报价或预言机读取。",
  };
}

export function formatEvidencePrice(price: number | null, exact?: string | null): string {
  if (price === null || !Number.isFinite(price) || price <= 0) return "未知";
  const raw = exactPrice(exact);
  if (raw) return `$${raw}`;
  return new Intl.NumberFormat("zh-CN", { style: "currency", currency: "USD", maximumSignificantDigits: 10 }).format(price);
}

export function formatEvidenceTime(value: number | null): string {
  if (value === null || timestamp(value) === null) return "未知";
  return `${new Date(value * 1000).toISOString().replace("T", " ").replace(/\.000Z$/, " UTC")}`;
}

export function formatEvidenceAge(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return "未知";
  const magnitude = Math.abs(seconds);
  const value = magnitude < 60 ? `${magnitude} 秒`
    : magnitude < 3600 ? `${Math.floor(magnitude / 60)} 分 ${magnitude % 60} 秒`
      : magnitude < 86400 ? `${Math.floor(magnitude / 3600)} 时 ${Math.floor(magnitude % 3600 / 60)} 分`
        : `${Math.floor(magnitude / 86400)} 天 ${Math.floor(magnitude % 86400 / 3600)} 时`;
  return seconds < 0 ? `晚于交易 ${value}` : `早于交易 ${value}`;
}

export function shortEvidenceHash(value: string): string {
  return value.length > 18 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value;
}
