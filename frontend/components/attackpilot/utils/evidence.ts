import {
  EvidenceItem,
  LogLevel,
  LogMessage,
  MsgType,
  ReportSectionKey,
  TaskEvent,
} from "../types";
import { enrichEvidenceItems } from "./evidenceScoring";

export function isLogEvent(event: TaskEvent): event is LogMessage {
  return event.type === "LOG";
}

export function compactEvidenceText(value: string, limit = 520) {
  const cleaned = value
    .replace(/```(?:json|python|solidity|text|markdown)?/gi, "")
    .replace(/```/g, "")
    .replace(/📊\s*统计\s*:?.*?(?:Token\s+\d+)?/gi, " ")
    .replace(/耗时\s*\d+(?:\.\d+)?s\s*\|\s*Token\s*\d+/gi, " ")
    .replace(/[#*_>`{}[\]]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return cleaned.length > limit ? `${cleaned.slice(0, limit)}...` : cleaned;
}

export function normalizeEvidenceMarkdown(value: string) {
  return value
    .replace(/\\r\\n/g, "\n")
    .replace(/\\n/g, "\n")
    .replace(/\\t/g, "  ")
    .replace(/^✅\s*任务输出\s*/i, "")
    .replace(/^Task output\s*/i, "")
    .replace(/📊\s*统计\s*:?.*?(?:Token\s+\d+)?/gi, "")
    .replace(/耗时\s*\d+(?:\.\d+)?s\s*\|\s*Token\s*\d+/gi, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

export function isLowValueOperationalLog(log: LogMessage) {
  const cleaned = compactEvidenceText(log.message, 1200).toLowerCase();
  if (!cleaned) return true;

  const operationalOnlyPatterns = [
    /^任务输出\s*$/i,
    /^task output\s*$/i,
    /^interaction:\s*(query|response)\s*$/i,
    /^snapshot snippet:/i,
    /^model determines invocation of tools\s*\(\d+\):?\s*$/i,
  ];
  if (operationalOnlyPatterns.some((pattern) => pattern.test(cleaned))) return true;

  const hasSubstantiveSignal = [
    "root cause",
    "attack",
    "exploit",
    "transaction",
    "trace",
    "storage",
    "event",
    "patch",
    "verify",
    "validation",
    "根因",
    "攻击",
    "交易",
    "调用",
    "状态",
    "补丁",
    "验证",
    "0x",
  ].some((keyword) => cleaned.includes(keyword));

  return !hasSubstantiveSignal && cleaned.length < 80;
}

export function extractTransactionHashes(content: string) {
  return Array.from(new Set(Array.from(content.matchAll(/0x[a-fA-F0-9]{64}/g)).map((item) => item[0])));
}

function getSectionKeywords(sectionKey: ReportSectionKey) {
  const keywordMap: Record<ReportSectionKey, string[]> = {
    root_cause: ["root cause", "根因", "vulnerab", "fault", "缺陷", "函数", "function"],
    attack_path: ["attack", "exploit", "攻击", "路径", "flow", "调用", "trace"],
    key_transactions: ["transaction", "tx", "交易", "hash", "0x", "attacker"],
    patch_suggestions: ["patch", "fix", "mitigation", "修复", "补丁", "require", "check"],
    verification_results: ["verify", "validation", "replay", "验证", "抵挡", "success", "failure"],
  };
  return keywordMap[sectionKey];
}

function scoreLogForSection(log: LogMessage, sectionKey: ReportSectionKey) {
  if (isLowValueOperationalLog(log)) return 0;

  const haystack = `${log.agent} ${log.level} ${log.message_type} ${log.message}`.toLowerCase();
  const keywords = getSectionKeywords(sectionKey);
  let score = 0;

  keywords.forEach((keyword) => {
    if (haystack.includes(keyword.toLowerCase())) score += 2;
  });
  if (log.message_type === MsgType.TOOL_CALL && ["attack_path", "key_transactions"].includes(sectionKey)) score += 2;
  if (log.message_type === MsgType.RESULT && !isLowValueOperationalLog(log)) score += 1;
  if (log.level === LogLevel.ERROR || log.level === LogLevel.WARNING) score += 1;

  return score;
}

function confidenceFromScore(score: number): EvidenceItem["confidence"] {
  if (score >= 5) return "high";
  if (score >= 3) return "medium";
  return "low";
}

export function buildEvidenceForSection(
  sectionKey: ReportSectionKey,
  sectionContent: string,
  events: TaskEvent[],
): EvidenceItem[] {
  const evidence: EvidenceItem[] = [];
  const transactions = extractTransactionHashes(sectionContent);

  transactions.slice(0, 6).forEach((hash, index) => {
    evidence.push({
      id: `${sectionKey}-tx-${index}`,
      title: `Transaction ${hash.slice(0, 10)}...${hash.slice(-8)}`,
      source: "transaction",
      content: hash,
      confidence: "high",
    });
  });

  const rankedLogs = events
    .filter(isLogEvent)
    .filter((log) => !isLowValueOperationalLog(log))
    .map((log, index) => ({ log, index, score: scoreLogForSection(log, sectionKey) }))
    .filter((item) => item.score > 0)
    .sort((a, b) => b.score - a.score || b.index - a.index)
    .slice(0, 8);

  rankedLogs.forEach(({ log, index, score }) => {
    evidence.push({
      id: `${sectionKey}-log-${log.log_id ?? index}`,
      title:
        log.message_type === MsgType.TOOL_CALL
          ? `Tool evidence from ${log.agent}`
          : `${log.agent} 智能体证据`,
      source: log.message_type === MsgType.TOOL_CALL ? "tool" : "agent_log",
      agent: log.agent,
      level: log.level,
      message_type: log.message_type,
      timestamp: log.timestamp,
      log_id: log.log_id,
      content: compactEvidenceText(log.message),
      full_content: normalizeEvidenceMarkdown(log.message),
      confidence: confidenceFromScore(score),
    });
  });

  if (sectionContent && !sectionContent.startsWith("暂未")) {
    evidence.unshift({
      id: `${sectionKey}-report-summary`,
      title: "报告章节摘要",
      source: "report",
      content: compactEvidenceText(sectionContent, 700),
      full_content: normalizeEvidenceMarkdown(sectionContent),
      confidence: "medium",
    });
  }

  return enrichEvidenceItems(evidence).slice(0, 10);
}

export function buildAttackPhaseEvidence(events: TaskEvent[], keywords: string[]) {
  const normalized = keywords.map((keyword) => keyword.toLowerCase());
  return enrichEvidenceItems(events
    .filter(isLogEvent)
    .filter((log) => !isLowValueOperationalLog(log))
    .filter((log) => {
      const haystack = `${log.agent} ${log.message}`.toLowerCase();
      return normalized.some((keyword) => haystack.includes(keyword));
    })
    .slice(-5)
    .map((log, index): EvidenceItem => ({
      id: `phase-${log.log_id ?? index}`,
      title: `${log.agent} evidence`,
      source: log.message_type === MsgType.TOOL_CALL ? "tool" : "agent_log",
      agent: log.agent,
      level: log.level,
      message_type: log.message_type,
      timestamp: log.timestamp,
      log_id: log.log_id,
      content: compactEvidenceText(log.message),
      full_content: normalizeEvidenceMarkdown(log.message),
      confidence: log.message_type === MsgType.RESULT ? "high" : "medium",
    })));
}
