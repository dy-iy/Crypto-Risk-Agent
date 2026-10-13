import React, { useMemo, useState } from "react";
import { Button, Progress, Space, Tag, Typography } from "antd";
import { AlertTriangle, CheckCircle2, SearchCheck, ShieldCheck } from "lucide-react";
import { EvidenceItem, LogMessage, Task, TaskEvent } from "../types";
import {
  compactEvidenceText,
  isLogEvent,
  isLowValueOperationalLog,
  normalizeEvidenceMarkdown,
} from "../utils/evidence";
import EvidenceDrawer from "./EvidenceDrawer";

interface PatchVerificationPanelProps {
  task: Task | null;
  events: TaskEvent[];
}

interface PatchVerificationSummary {
  status: "verified" | "partial" | "failed" | "pending";
  title: string;
  description: string;
  score: number;
  evidence: EvidenceItem[];
}

function pickParagraph(report: string, keywords: string[]) {
  const normalized = keywords.map((keyword) => keyword.toLowerCase());
  return (
    report
      .split(/\n\s*\n/)
      .map((item) => item.trim())
      .find((paragraph) => {
        const haystack = paragraph.toLowerCase();
        return normalized.some((keyword) => haystack.includes(keyword));
      }) ?? ""
  );
}

function isPatchLog(log: LogMessage) {
  const text = `${log.agent} ${log.message}`.toLowerCase();
  return /patch|verify|verification|validation|replay|success|failure|fix|补丁|验证|重放|修复|抵挡|失败|成功/.test(text);
}

function buildPatchEvidence(report: string, logs: LogMessage[]): EvidenceItem[] {
  const evidence: EvidenceItem[] = [];
  const reportContext = pickParagraph(report, [
    "verification",
    "validation",
    "replay",
    "patch",
    "verify",
    "验证",
    "补丁",
    "重放",
    "抵挡",
  ]);

  if (reportContext) {
    evidence.push({
      id: "patch-report-context",
      title: "报告验证片段",
      source: "report",
      content: compactEvidenceText(reportContext, 900),
      full_content: normalizeEvidenceMarkdown(reportContext),
      confidence: "medium",
    });
  }

  logs
    .filter(isPatchLog)
    .slice(-8)
    .forEach((log, index) => {
      evidence.push({
        id: `patch-log-${log.log_id ?? index}`,
        title: `${log.agent} 补丁证据`,
        source: log.message_type === "tool" ? "tool" : "agent_log",
        agent: log.agent,
        level: log.level,
        message_type: log.message_type,
        timestamp: log.timestamp,
        log_id: log.log_id,
        content: compactEvidenceText(log.message, 900),
        full_content: normalizeEvidenceMarkdown(log.message),
        confidence: /success|verified|抵挡|成功|passed/i.test(log.message) ? "high" : "medium",
      });
    });

  return evidence;
}

function buildSummary(task: Task | null, events: TaskEvent[]): PatchVerificationSummary {
  const report = task?.final_report ?? "";
  const logs = events.filter(isLogEvent).filter((log) => !isLowValueOperationalLog(log));
  const evidence = buildPatchEvidence(report, logs);
  const haystack = `${report}\n${logs.map((log) => log.message).join("\n")}`.toLowerCase();

  const hasSuccess = /success|verified|passed|blocked|resist|抵挡|阻断|成功|通过/.test(haystack);
  const hasFailure = /fail|failed|failure|error|not verified|失败|未通过|无法验证/.test(haystack);
  const hasPatchSignal = /patch|fix|mitigation|verify|validation|replay|补丁|修复|验证|重放/.test(haystack);

  if (hasSuccess && !hasFailure) {
    return {
      status: "verified",
      title: "补丁验证通过",
      description: "现有报告和日志证据表明，该补丁已阻断重放的攻击路径。",
      score: 92,
      evidence,
    };
  }

  if (hasSuccess && hasFailure) {
    return {
      status: "partial",
      title: "补丁验证部分通过",
      description: "分析中同时出现成功与失败信号，需要结合关联证据判断修复效果。",
      score: 62,
      evidence,
    };
  }

  if (hasFailure) {
    return {
      status: "failed",
      title: "补丁验证存在异常",
      description: "现有证据包含失败或尚未解决的验证信号。",
      score: 34,
      evidence,
    };
  }

  if (hasPatchSignal) {
    return {
      status: "pending",
      title: "补丁验证证据不完整",
      description: "已发现补丁相关内容，但尚未提取到明确的通过或失败信号。",
      score: 48,
      evidence,
    };
  }

  return {
    status: "pending",
    title: "等待补丁验证",
    description: "暂未提取到明确的补丁重放或验证信号。",
    score: 18,
    evidence,
  };
}

function statusColor(status: PatchVerificationSummary["status"]) {
  if (status === "verified") return "success";
  if (status === "partial") return "active";
  if (status === "failed") return "exception";
  return "normal";
}

function tagColor(status: PatchVerificationSummary["status"]) {
  if (status === "verified") return "success";
  if (status === "partial") return "warning";
  if (status === "failed") return "error";
  return "default";
}

const PatchVerificationPanel: React.FC<PatchVerificationPanelProps> = ({ task, events }) => {
  const [open, setOpen] = useState(false);
  const summary = useMemo(() => buildSummary(task, events), [events, task]);
  const Icon = summary.status === "failed" || summary.status === "partial" ? AlertTriangle : ShieldCheck;

  return (
    <section className="product-summary-card patch-verification-card">
      <div className="product-summary-head">
        <Space size={8}>
          <Icon size={16} />
          <Typography.Text strong>补丁验证</Typography.Text>
        </Space>
        <Tag color={tagColor(summary.status)}>
          {summary.status === "verified" ? "已通过" : summary.status === "partial" ? "部分通过" : summary.status === "failed" ? "异常" : "等待中"}
        </Tag>
      </div>

      <div className="patch-verification-body">
        <div className="patch-score">
          <Progress
            type="circle"
            size={78}
            percent={summary.score}
            status={statusColor(summary.status)}
            format={() => (summary.status === "verified" ? <CheckCircle2 size={22} /> : `${summary.score}%`)}
          />
        </div>
        <div className="patch-summary">
          <Typography.Text strong>{summary.title}</Typography.Text>
          <Typography.Paragraph>{summary.description}</Typography.Paragraph>
          <Space size={8} wrap>
            <Tag color={summary.evidence.length > 0 ? "cyan" : "default"}>{summary.evidence.length} 条证据</Tag>
            <Button size="small" icon={<SearchCheck size={14} />} onClick={() => setOpen(true)}>
              查看证据
            </Button>
          </Space>
        </div>
      </div>

      <EvidenceDrawer
        title="补丁验证证据"
        open={open}
        evidence={summary.evidence}
        onClose={() => setOpen(false)}
      />
    </section>
  );
};

export default PatchVerificationPanel;
