import { EvidenceItem, LogLevel, MsgType } from "../types";

export interface EvidenceScoreResult {
  score: number;
  label: "strong" | "supporting" | "weak";
  reasons: string[];
  tier: NonNullable<EvidenceItem["evidence_tier"]>;
}

export interface EvidenceHealthSummary {
  score: number;
  label: "strong" | "supporting" | "weak";
  total: number;
  strong: number;
  supporting: number;
  weak: number;
  transactions: number;
  tools: number;
  agents: number;
  risks: string[];
}

const SECURITY_KEYWORDS = [
  "attack",
  "attacker",
  "exploit",
  "root cause",
  "vulnerab",
  "trace",
  "storage",
  "event",
  "transaction",
  "patch",
  "verify",
  "validation",
  "replay",
  "漏洞",
  "根因",
  "攻击",
  "交易",
  "调用",
  "状态",
  "补丁",
  "验证",
];

function clamp(value: number) {
  return Math.max(0, Math.min(100, Math.round(value)));
}

function labelFromScore(score: number): EvidenceScoreResult["label"] {
  if (score >= 72) return "strong";
  if (score >= 45) return "supporting";
  return "weak";
}

function textOf(item: EvidenceItem) {
  return `${item.title} ${item.content} ${item.full_content || ""}`.toLowerCase();
}

export function isToolBackedEvidence(item: EvidenceItem) {
  return item.source === "tool" || item.message_type === MsgType.TOOL_CALL || item.evidence_tier === "tool_backed";
}

export function inferEvidenceTier(item: EvidenceItem): NonNullable<EvidenceItem["evidence_tier"]> {
  const haystack = textOf(item);
  const hasOnChainRef = /0x[a-f0-9]{40,64}/i.test(haystack);

  if (item.source === "transaction" || (isToolBackedEvidence(item) && hasOnChainRef)) {
    return "verified";
  }
  if (isToolBackedEvidence(item) || item.source === "system") {
    return "tool_backed";
  }
  if (item.source === "agent_log") {
    return "agent_derived";
  }
  return "report_derived";
}

export function scoreEvidenceItem(item: EvidenceItem): EvidenceScoreResult {
  const reasons: string[] = [];
  const haystack = textOf(item);
  const tier = inferEvidenceTier(item);
  let score = 0;

  if (item.source === "transaction") {
    score += 32;
    reasons.push("直接交易证据");
  } else if (item.source === "tool") {
    score += 30;
    reasons.push("工具调用支撑");
  } else if (item.source === "system") {
    score += 26;
    reasons.push("结构化系统输出");
  } else if (item.source === "agent_log") {
    score += 20;
    reasons.push("智能体推理记录");
  } else {
    score += 16;
    reasons.push("报告提取结论");
  }

  if (item.confidence === "high") {
    score += 22;
    reasons.push("与结论强关联");
  } else if (item.confidence === "medium") {
    score += 14;
    reasons.push("与结论有关联");
  } else {
    score += 5;
  }

  if (tier === "verified") {
    score += 8;
    reasons.push("已验证证据层级");
  } else if (tier === "report_derived") {
    score -= 6;
    reasons.push("仅由报告支撑");
  }

  if (item.message_type === MsgType.TOOL_CALL) {
    score += 14;
    reasons.push("包含工具调用");
  }
  if (item.message_type === MsgType.RESULT) {
    score += 12;
    reasons.push("包含智能体结果");
  }
  if (item.level === LogLevel.ERROR || item.level === LogLevel.WARNING) {
    score += 4;
    reasons.push("包含高信号运行事件");
  }
  if (/0x[a-f0-9]{40,64}/i.test(haystack)) {
    score += 10;
    reasons.push("包含链上地址或交易哈希");
  }
  if (SECURITY_KEYWORDS.some((keyword) => haystack.includes(keyword.toLowerCase()))) {
    score += 8;
    reasons.push("命中漏洞分析关键词");
  }
  if ((item.full_content || item.content).length > 240) {
    score += 5;
    reasons.push("上下文较完整");
  }

  const operationalOnly = /task output|interaction:\s*(query|response)|snapshot snippet|耗时|token|统计/i.test(haystack);
  if (operationalOnly && item.source !== "transaction") {
    score -= 18;
    reasons.push("包含运行噪声");
  }
  if ((item.full_content || item.content).trim().length < 40) {
    score -= 8;
    reasons.push("上下文过短");
  }

  const finalScore = clamp(score);
  return {
    score: finalScore,
    label: labelFromScore(finalScore),
    reasons: Array.from(new Set(reasons)).slice(0, 5),
    tier,
  };
}

export function enrichEvidenceItem(item: EvidenceItem): EvidenceItem {
  const result = scoreEvidenceItem(item);
  return {
    ...item,
    evidence_tier: result.tier,
    score: result.score,
    score_label: result.label,
    score_reasons: result.reasons,
  };
}

export function enrichEvidenceItems(items: EvidenceItem[]) {
  return items.map(enrichEvidenceItem).sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
}

export function summarizeEvidenceHealth(items: EvidenceItem[]): EvidenceHealthSummary {
  const enriched = enrichEvidenceItems(items);
  const total = enriched.length;
  const strong = enriched.filter((item) => item.score_label === "strong").length;
  const supporting = enriched.filter((item) => item.score_label === "supporting").length;
  const weak = enriched.filter((item) => item.score_label === "weak").length;
  const transactions = enriched.filter((item) => item.source === "transaction").length;
  const tools = enriched.filter(isToolBackedEvidence).length;
  const agents = new Set(enriched.map((item) => item.agent).filter(Boolean)).size;
  const score = total ? clamp(enriched.reduce((sum, item) => sum + (item.score ?? 0), 0) / total) : 0;
  const risks: string[] = [];

  if (total === 0) risks.push("no linked evidence");
  if (transactions === 0) risks.push("no direct transaction hash");
  if (tools === 0) risks.push("no tool-backed evidence");
  if (agents < 2 && total > 0) risks.push("single-agent evidence");
  if (weak > strong + supporting && total > 0) risks.push("mostly weak evidence");

  return {
    score,
    label: labelFromScore(score),
    total,
    strong,
    supporting,
    weak,
    transactions,
    tools,
    agents,
    risks,
  };
}
