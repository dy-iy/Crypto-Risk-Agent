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
import { buildEvidenceForSection } from "../utils/evidence";
import AgentConsistencyPanel from "./AgentConsistencyPanel";
import EvidenceDrawer from "./EvidenceDrawer";
import EvidenceIntelligencePanel from "./EvidenceIntelligencePanel";
import KeyTransactionCards from "./KeyTransactionCards";
import MarkdownRenderer from "./MarkdownRenderer";
import PatchVerificationPanel from "./PatchVerificationPanel";
import { taskStatusLabel } from "../utils/presentation";

interface StructuredReportProps {
  task: Task | null;
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
    .replace(/^\d+[.)、]\s*/, "")
    .replace(/[:：]\s*$/, "")
    .trim()
    .toLowerCase();
}

function extractHeadingSections(report: string) {
  const lines = report.split(/\r?\n/);
  const sections: Array<{ heading: string; content: string }> = [];
  let currentHeading = "";
  let currentLines: string[] = [];

  for (const line of lines) {
    const headingMatch = line.match(/^\s{0,3}(#{1,4}\s+.+|\d+[.)、]\s+.+)$/);
    if (headingMatch) {
      if (currentHeading) sections.push({ heading: currentHeading, content: currentLines.join("\n").trim() });
      currentHeading = normalizeHeading(headingMatch[1]);
      currentLines = [];
      continue;
    }

    if (currentHeading) currentLines.push(line);
  }

  if (currentHeading) sections.push({ heading: currentHeading, content: currentLines.join("\n").trim() });
  return sections;
}

function findSectionByHeading(report: string, patterns: string[]) {
  const headingSections = extractHeadingSections(report);
  const normalizedPatterns = patterns.map((pattern) => pattern.toLowerCase());
  const match = headingSections.find((section) =>
    normalizedPatterns.some((pattern) => section.heading.includes(pattern)),
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
  const matches = Array.from(`${report}\n${joinedLogs}`.matchAll(/0x[a-fA-F0-9]{64}/g)).map((item) => item[0]);
  return Array.from(new Set(matches)).slice(0, 12);
}

function parseReportSections(report: string, events: TaskEvent[]): ReportSection[] {
  const transactions = extractTransactions(report, events);
  return SECTION_DEFS.map((definition) => {
    const byHeading = findSectionByHeading(report, definition.patterns);
    const fallback =
      definition.key === "key_transactions" && transactions.length > 0
        ? transactions.map((hash) => `- \`${hash}\``).join("\n")
        : findParagraphByKeyword(report, definition.keywords);

    const content = byHeading || fallback || "暂未从最终报告中提取到该部分，可查看原始报告获取完整上下文。";
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

function buildMarkdownExport(task: Task, sections: ReportSection[], agentSummaries: AgentExportSummary[]) {
  const lines = [
    `# AttackPilot 攻击复盘报告 - ${task.dapp_name}`,
    "",
    "## 任务信息",
    "",
    `- 任务 ID：\`${task.task_id}\``,
    `- 状态：${taskStatusLabel(task.status)}`,
    `- 创建时间：${task.created_at}`,
    `- 完成时间：${task.completed_at ?? "暂无"}`,
    `- 耗时：${task.duration ?? "暂无"} 秒`,
    "",
    ...sections.flatMap((section) => [`## ${section.title}`, "", section.content, ""]),
    "## 智能体证据摘要",
    "",
    "| 智能体 | 事件 | 工具调用 | 结果 | 错误 | 警告 |",
    "| --- | ---: | ---: | ---: | ---: | ---: |",
    ...agentSummaries.map(
      (agent) =>
        `| ${agent.agent} | ${agent.total} | ${agent.tool_calls} | ${agent.results} | ${agent.errors} | ${agent.warnings} |`,
    ),
    "",
    "## 原始最终报告",
    "",
    task.final_report || "暂无",
  ];
  return lines.join("\n");
}

const StructuredReport: React.FC<StructuredReportProps> = ({
  task,
  events,
  mode = "report",
  macroAnalysis,
  automatedReview,
  language = "zh",
}) => {
  const { message } = AntdApp.useApp();
  const [selectedSection, setSelectedSection] = useState<ReportSection | null>(null);
  const finalReport = task?.final_report ?? "";
  const sections = useMemo(() => parseReportSections(finalReport, events), [events, finalReport]);
  const agentSummaries = useMemo(() => buildAgentSummaries(events), [events]);
  const logEvents = useMemo(() => events.filter(isLogEvent), [events]);

  const exportMarkdown = () => {
    if (!task) return;
    downloadText(
      `${safeName(task.dapp_name)}_${task.task_id.slice(0, 8)}_audit_report.md`,
      buildMarkdownExport(task, sections, agentSummaries),
      "text/markdown;charset=utf-8",
    );
    message.success("Markdown 报告已导出");
  };

  const exportJson = () => {
    if (!task) return;
    const payload = {
      exported_at: new Date().toISOString(),
      task,
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
              ? "学习视图按攻击过程解释结论，并关联对应证据。"
              : `已从最终报告提取 ${sections.length} 个部分，并关联证据。`}
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

      <div className="report-section-list">
        <div className="product-summary-grid">
          <KeyTransactionCards task={task} events={events} macroAnalysis={macroAnalysis} language={language} />
          <PatchVerificationPanel task={task} events={events} />
        </div>

        <EvidenceIntelligencePanel sections={sections} language={language} />
        <AgentConsistencyPanel
          task={task}
          events={events}
          macro={macroAnalysis ?? null}
          review={automatedReview}
          language={language}
        />

        {sections.map((section) => (
          <section className="report-section-card" key={section.key}>
            <div className="report-section-head">
              <span className="report-section-icon">{section.icon}</span>
              <div>
                <Typography.Text strong>{section.title}</Typography.Text>
                <Typography.Text type="secondary">{section.description}</Typography.Text>
              </div>
              <Space size={6}>
                <Tag color={section.evidence.length > 0 ? "cyan" : "default"}>{section.evidence.length} 条证据</Tag>
                {section.content.startsWith("暂未") ? <Tag>待补充</Tag> : <Tag color="success">已提取</Tag>}
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
              <Typography.Text strong>原始报告</Typography.Text>
              <Typography.Text type="secondary">完整原始报告，保留模型输出上下文。</Typography.Text>
            </div>
          </div>
          <MarkdownRenderer content={finalReport} compact />
        </section>
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
