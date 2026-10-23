import React, { useMemo, useState } from "react";
import { App as AntdApp, Button, Empty, Space, Tag, Typography } from "antd";
import { Bug, CheckCircle2, Download, FileJson, KeyRound, Route, SearchCheck, ShieldCheck, Wrench } from "lucide-react";
import {
  EvidenceItem,
  AutomatedReviewResponse,
  LanguageMode,
  LogLevel,
  LogMessage,
  MacroAnalysisResponse,
  MsgType,
  ProductViewMode,
  ReportSectionKey,
  Task,
  TaskEvent,
} from "../types";
import { buildEvidenceForSection, extractTransactionHashes } from "../utils/evidence";
import AgentConsistencyPanel from "./AgentConsistencyPanel";
import EvidenceDrawer from "./EvidenceDrawer";
import EvidenceIntelligencePanel from "./EvidenceIntelligencePanel";
import KeyTransactionCards from "./KeyTransactionCards";
import MarkdownRenderer from "./MarkdownRenderer";
import PatchVerificationPanel from "./PatchVerificationPanel";
import PriceEvidencePanel, { buildPriceEvidenceMarkdown } from "./PriceEvidencePanel";
import { taskStatusLabel } from "../utils/presentation";
import { findNarrativeSummary } from "../utils/reportNarrative";
import { buildPatchVerificationMarkdown } from "../utils/verification";

interface StructuredReportProps {
  task: Task | null;
  originalTask?: Task | null;
  translated?: boolean;
  events: TaskEvent[];
  mode?: ProductViewMode;
  macroAnalysis?: MacroAnalysisResponse | null;
  automatedReview?: AutomatedReviewResponse | null;
  language?: LanguageMode;
}

interface ReportSection {
  key: ReportSectionKey;
  title: string;
  description: string;
  content: string;
  icon: React.ReactNode;
  evidence: EvidenceItem[];
}

interface AgentExportSummary {
  agent: string;
  total: number;
  errors: number;
  warnings: number;
  tool_calls: number;
  results: number;
  latest_message?: string;
  latest_timestamp?: string;
}

const SECTION_DEFS: Array<{
  key: ReportSectionKey;
  title: string;
  description: string;
  icon: React.ReactNode;
  patterns: string[];
  keywords: string[];
}> = [
  {
    key: "root_cause",
    title: "漏洞根因",
    description: "定位到的根因函数、状态变量或权限/逻辑缺陷。",
    icon: <Bug size={16} />,
    patterns: ["漏洞根因", "根因", "Root Cause", "Vulnerability Root Cause", "Fault Cause"],
    keywords: ["root cause", "漏洞", "根因", "vulnerab", "fault", "缺陷"],
  },
  {
    key: "attack_path",
    title: "攻击路径",
    description: "攻击者如何通过交易序列、调用链和状态变化触发漏洞。",
    icon: <Route size={16} />,
    patterns: ["攻击路径", "攻击流程", "Attack Path", "Exploit Path", "Attack Flow"],
    keywords: ["attack", "exploit", "攻击", "调用", "路径", "flow"],
  },
  {
    key: "key_transactions",
    title: "关键交易",
    description: "与漏洞触发、收益转移或验证闭环直接相关的交易证据。",
    icon: <KeyRound size={16} />,
    patterns: ["关键交易", "核心交易", "Key Transactions", "Critical Transactions", "Transactions"],
    keywords: ["transaction", "tx", "交易", "hash", "0x"],
  },
  {
    key: "patch_suggestions",
    title: "补丁建议",
    description: "可落地的 Solidity 修复方案、约束条件和防护策略。",
    icon: <Wrench size={16} />,
    patterns: ["补丁建议", "修复建议", "Patch", "Patch Suggestions", "Mitigation", "Fix"],
    keywords: ["patch", "fix", "mitigation", "修复", "补丁", "require", "check"],
  },
  {
    key: "verification_results",
    title: "验证结果",
    description: "补丁回放、攻击抵抗结果、失败原因或剩余风险。",
    icon: <ShieldCheck size={16} />,
    patterns: ["验证结果", "补丁验证", "Verification", "Validation", "Replay Result"],
    keywords: ["verify", "validation", "replay", "验证", "抵挡", "success", "failure"],
  },
];

function isLogEvent(event: TaskEvent): event is LogMessage {
  return event.type === "LOG";
}

function compactText(value: string, limit = 260) {
  const cleaned = value.replace(/\s+/g, " ").trim();
  return cleaned.length > limit ? `${cleaned.slice(0, limit)}...` : cleaned;
}

function normalizeHeading(value: string) {
  return value
    .replace(/^#+\s*/, "")
    .replace(/^\*{1,2}|\*{1,2}$/g, "")
    .replace(/^\d+(?:\.\d+)*[.)、]?\s+/, "")
    .replace(/[:：]\s*$/, "")
    .trim()
    .toLowerCase();
}

function extractHeadingSections(report: string) {
  const lines = report.split(/\r?\n/);
  const headings: Array<{ heading: string; level: number; line: number }> = [];
  let fence: { marker: string; length: number } | null = null;
  lines.forEach((line, index) => {
    const fenceMatch = line.match(/^\s{0,3}(`{3,}|~{3,})/);
    if (fenceMatch) {
      if (!fence) fence = { marker: fenceMatch[1][0], length: fenceMatch[1].length };
      else if (fence.marker === fenceMatch[1][0] && fenceMatch[1].length >= fence.length) fence = null;
      return;
    }
    if (fence) return;
    const markdown = line.match(/^\s{0,3}(#{1,6})\s+(.+)$/);
    if (markdown) {
      headings.push({ heading: normalizeHeading(markdown[2]), level: markdown[1].length, line: index });
      return;
    }
    // Recognize plain report headings without mistaking numbered evidence lists for sections.
    const numbered = line.match(/^(?:\*{1,2})?(\d+(?:\.\d+)*[.)、]?)\s+(.+?)(?:\*{1,2})?$/);
    if (numbered && SECTION_DEFS.some(definition => definition.patterns.some(pattern =>
      normalizeHeading(numbered[2]).includes(pattern.toLowerCase())))) {
      headings.push({ heading: normalizeHeading(numbered[2]), level: 2 + (numbered[1].match(/\.\d/g)?.length || 0), line: index });
    }
  });
  return headings.map((heading, index) => {
    const end = headings.slice(index + 1).find(next => next.level <= heading.level)?.line ?? lines.length;
    return { heading: heading.heading, content: lines.slice(heading.line + 1, end).join("\n").trim() };
  });
}

function findSectionByHeading(report: string, patterns: string[], sectionKey: ReportSectionKey) {
  const headingSections = extractHeadingSections(report);
  const normalizedPatterns = patterns.map((pattern) => pattern.toLowerCase());
  const match = headingSections.find((section) =>
    !(sectionKey === "patch_suggestions" && /verification|validation|验证/.test(section.heading))
      && normalizedPatterns.some((pattern) => section.heading.includes(pattern)),
  );
  return match?.content ?? "";
}

function findParagraphByKeyword(report: string, keywords: string[]) {
  const paragraphs = report
    .split(/\n\s*\n/)
    .map((item) => item.trim())
    .filter(Boolean);
  const normalizedKeywords = keywords.map((keyword) => keyword.toLowerCase());
  const match = paragraphs.find((paragraph) => {
    const normalized = paragraph.toLowerCase();
    return normalizedKeywords.some((keyword) => normalized.includes(keyword));
  });
  return match ? compactText(match, 900) : "";
}

function extractTransactions(report: string, events: TaskEvent[]) {
  const joinedLogs = events
    .filter(isLogEvent)
    .slice(-300)
    .map((event) => event.message)
    .join("\n");
  return extractTransactionHashes(`${report}\n${joinedLogs}`).slice(0, 12);
}

function parseReportSections(report: string, events: TaskEvent[], task: Task | null): ReportSection[] {
  const transactions = extractTransactions(report, events);
  return SECTION_DEFS.map((definition) => {
    const byHeading = findSectionByHeading(report, definition.patterns, definition.key);
    const fallback =
      definition.key === "key_transactions" && transactions.length > 0
        ? transactions.map((hash) => `- \`${hash}\``).join("\n")
        : ["root_cause", "attack_path"].includes(definition.key)
          ? findNarrativeSummary(report, definition.keywords, "", 900)
          : definition.key === "patch_suggestions" ? "" : findParagraphByKeyword(report, definition.keywords);

    const content = definition.key === "verification_results" ? buildPatchVerificationMarkdown(task)
      : byHeading || fallback || "暂未从最终报告中提取到该部分，可查看原始报告获取完整上下文。";
    return {
      key: definition.key,
      title: definition.title,
      description: definition.description,
      icon: definition.icon,
      content,
      evidence: buildEvidenceForSection(definition.key, content, events),
    };
  });
}

function buildAgentSummaries(events: TaskEvent[]): AgentExportSummary[] {
  const map = new Map<string, AgentExportSummary>();

  events.forEach((event) => {
    if (!isLogEvent(event)) return;
    const current =
      map.get(event.agent) ??
      ({
        agent: event.agent,
        total: 0,
        errors: 0,
        warnings: 0,
        tool_calls: 0,
        results: 0,
      } satisfies AgentExportSummary);

    current.total += 1;
    if (event.level === LogLevel.ERROR) current.errors += 1;
    if (event.level === LogLevel.WARNING) current.warnings += 1;
    if (event.message_type === MsgType.TOOL_CALL) current.tool_calls += 1;
    if (event.message_type === MsgType.RESULT) current.results += 1;
    current.latest_message = compactText(event.message);
    current.latest_timestamp = event.timestamp;
    map.set(event.agent, current);
  });

  return Array.from(map.values()).sort((a, b) => b.total - a.total || a.agent.localeCompare(b.agent));
}

function downloadText(filename: string, content: string, mimeType: string) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function safeName(value?: string) {
  return (value || "attackpilot").replace(/[\\/:*?"<>|\s]+/g, "_");
}

function buildMarkdownExport(task: Task, sections: ReportSection[], agentSummaries: AgentExportSummary[], originalTask: Task, translated: boolean) {
  const lines = [
    `# AttackPilot 攻击复盘报告 - ${task.dapp_name}`,
    "",
    "## 任务信息",
    "",
    `- 任务 ID：\`${task.task_id}\``,
    `- 状态：${taskStatusLabel(task.status)}`,
    `- 数据来源：${task.is_demo ? "历史归档，本次未执行回放" : "当前任务分析记录"}`,
    `- 创建时间：${task.created_at}`,
    `- 完成时间：${task.completed_at ?? "暂无"}`,
    `- 耗时：${task.duration ?? "暂无"} 秒`,
    "",
    ...sections.flatMap((section) => [`## ${section.title}`, "", section.content, ""]),
    buildPriceEvidenceMarkdown(originalTask),
    "",
    "## 智能体证据摘要",
    "",
    "| 智能体 | 事件 | 工具调用 | 结果 | 错误 | 警告 |",
    "| --- | ---: | ---: | ---: | ---: | ---: |",
    ...agentSummaries.map(
      (agent) =>
        `| ${agent.agent} | ${agent.total} | ${agent.tool_calls} | ${agent.results} | ${agent.errors} | ${agent.warnings} |`,
    ),
    "",
    translated ? "## 完整中文译文" : "## 模型原始报告",
    "模型叙述保留供核对；补丁效果以本报告的结构化验证结果为准。",
    "",
    task.final_report || "暂无",
    ...(translated ? ["", "## 模型原始报告", "", originalTask.final_report || "暂无"] : []),
  ];
  return lines.join("\n");
}

const StructuredReport: React.FC<StructuredReportProps> = ({
  task,
  originalTask,
  translated = false,
  events,
  mode = "report",
  macroAnalysis,
  automatedReview,
  language = "zh",
}) => {
  const { message } = AntdApp.useApp();
  const [selectedSection, setSelectedSection] = useState<ReportSection | null>(null);
  const finalReport = task?.final_report ?? "";
  const canonicalTask = originalTask ?? task;
  const sections = useMemo(() => parseReportSections(finalReport, events, canonicalTask), [events, finalReport, canonicalTask]);
  const agentSummaries = useMemo(() => buildAgentSummaries(events), [events]);
  const logEvents = useMemo(() => events.filter(isLogEvent), [events]);

  const exportMarkdown = () => {
    if (!task) return;
    downloadText(
      `${safeName(task.dapp_name)}_${task.task_id.slice(0, 8)}_audit_report.md`,
      buildMarkdownExport(task, sections, agentSummaries, originalTask ?? task, translated),
      "text/markdown;charset=utf-8",
    );
    message.success("Markdown 报告已导出");
  };

  const exportJson = () => {
    if (!task) return;
    const payload = {
      exported_at: new Date().toISOString(),
      task: originalTask ?? task,
      ...(translated ? { translated_report: finalReport, report_language: "zh-CN" } : {}),
      report_sections: sections.map((section) => ({
        key: section.key,
        title: section.title,
        description: section.description,
        content: section.content,
      })),
      agent_summaries: agentSummaries,
      log_event_count: logEvents.length,
      events,
    };
    downloadText(
      `${safeName(task.dapp_name)}_${task.task_id.slice(0, 8)}_evidence_package.json`,
      JSON.stringify(payload, null, 2),
      "application/json;charset=utf-8",
    );
    message.success("JSON 证据包已导出");
  };

  if (!task?.final_report) {
    return (
      <div className="empty-report">
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="任务完成后将在此显示最终报告。" />
      </div>
    );
  }

  return (
    <div className="structured-report-panel">
      <div className="report-actions">
        <div>
          <Typography.Text strong>结构化复盘报告</Typography.Text>
          <Typography.Text type="secondary">
            {mode === "learn"
              ? "学习视图按报告叙述组织攻击过程，并列出相关记录供核对。"
              : `按 ${sections.length} 个部分整理报告；验证结果以执行记录为准。`}
          </Typography.Text>
        </div>
        <Space size={8} wrap>
          <Button size="small" icon={<Download size={14} />} onClick={exportMarkdown}>
            导出 Markdown
          </Button>
          <Button size="small" icon={<FileJson size={14} />} onClick={exportJson}>
            导出 JSON
          </Button>
        </Space>
      </div>

      <div className="ap-report-verification">
        <PatchVerificationPanel task={originalTask ?? task} events={events} />
      </div>

      <PriceEvidencePanel task={originalTask ?? task} />

      <div className="ap-report-document">
        <nav className="ap-report-index" aria-label="结构化复盘报告">
          {sections.map((section) => <a key={section.key} href={`#ap-report-section-${section.key}`}>{section.icon}<span>{section.title}</span></a>)}
        </nav>
        <div className="report-section-list">

        {sections.map((section) => (
          <section className="report-section-card" id={`ap-report-section-${section.key}`} key={section.key}>
            <div className="report-section-head">
              <span className="report-section-icon">{section.icon}</span>
              <div>
                <Typography.Text strong>{section.title}</Typography.Text>
                <Typography.Text type="secondary">{section.description}</Typography.Text>
              </div>
              <Space size={6}>
                <Tag color={section.evidence.length > 0 ? "cyan" : "default"}>{section.evidence.length} 条相关记录</Tag>
                {section.content.startsWith("暂未") ? <Tag>待补充</Tag> : <Tag>{section.key === "verification_results" ? "执行状态" : "报告提取"}</Tag>}
              </Space>
            </div>
            <MarkdownRenderer content={section.content} compact />
            <div className="report-section-footer">
              <Button
                size="small"
                icon={<SearchCheck size={14} />}
                onClick={() => setSelectedSection(section)}
              >
                查看证据
              </Button>
            </div>
          </section>
        ))}

        <section className="report-section-card raw-report-card">
          <div className="report-section-head">
            <span className="report-section-icon">
              <CheckCircle2 size={16} />
            </span>
            <div>
              <Typography.Text strong>{translated ? "完整中文报告" : "完整原始报告"}</Typography.Text>
              <Typography.Text type="secondary">{translated ? "保留完整译文供核对；补丁效果以结构化验证结果为准。" : "保留模型输出上下文供核对；补丁效果以结构化验证结果为准。"}</Typography.Text>
            </div>
          </div>
          <MarkdownRenderer content={finalReport} compact />
        </section>
        </div>
      </div>

      <div className="ap-report-appendix">
        <details>
          <summary>关键交易</summary>
          <KeyTransactionCards task={task} events={events} macroAnalysis={macroAnalysis} language={language} />
        </details>
        <details>
          <summary>证据智能筛选</summary>
          <EvidenceIntelligencePanel sections={sections} language={language} />
        </details>
        <details>
          <summary>多智能体一致性检查</summary>
          <AgentConsistencyPanel task={originalTask ?? task} events={events} macro={macroAnalysis ?? null} review={automatedReview} language={language} />
        </details>
      </div>

      <EvidenceDrawer
        title={selectedSection ? `${selectedSection.title}证据` : "证据"}
        open={Boolean(selectedSection)}
        evidence={selectedSection?.evidence ?? []}
        onClose={() => setSelectedSection(null)}
      />
    </div>
  );
};

export default StructuredReport;
