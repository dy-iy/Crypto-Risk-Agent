import { EvidenceItem, LanguageMode, LogLevel, MsgType } from "../types";

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

export function evidenceScoreLabel(label: EvidenceScoreResult["label"], language: LanguageMode = "zh") {
  if (language === "en") return { strong: "high relevance", supporting: "related", weak: "low relevance" }[label];
  return { strong: "高相关", supporting: "相关", weak: "低相关" }[label];
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
  // A hash mention, tool invocation or model result cannot prove an outcome.
  // These records are indexed for review; verification uses its own bound replay envelope.
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
    reasons.push("包含交易引用（未核验）");
  } else if (item.source === "tool") {
    score += 30;
    reasons.push("工具调用记录");
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

  if (tier === "report_derived") {
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
    reasons.push("包含告警或失败记录");
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
  const seen = new Set<string>();
  return items.filter(item => {
    const identity = item.log_id ? `log:${item.log_id}`
      : `${item.source}:${item.agent ?? ""}:${(item.full_content || item.content).trim().toLowerCase()}`;
    if (seen.has(identity)) return false;
    seen.add(identity);
    return true;
  }).map(enrichEvidenceItem).sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
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

  if (total === 0) risks.push("暂无相关记录");
  if (transactions === 0) risks.push("缺少交易引用");
  if (tools === 0) risks.push("缺少工具调用记录");
  if (agents < 2 && total > 0) risks.push("缺少多个智能体的交叉记录");
  if (weak > strong + supporting && total > 0) risks.push("多数记录相关性较低");

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
