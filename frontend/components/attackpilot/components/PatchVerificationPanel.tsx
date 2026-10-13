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
  status: "verified" | "failed" | "pending" | "skipped" | "archived";
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
  const result = task?.result;
  const verification = result && typeof result === "object" && "verification" in result
    && result.verification && typeof result.verification === "object"
    ? result.verification as { status?: string } : null;

  if (task?.is_demo) {
    return { status: "archived", title: "历史补丁验证记录", score: 0, evidence,
      description: "以下证据来自原项目归档，当前环境尚未重新执行补丁回放。" };
  }
  if (verification?.status === "verified") {
    return { status: "verified", title: "补丁回放验证通过", score: 100, evidence,
      description: "后端实际回放结果确认，补丁已通过本次验证。" };
  }
  if (verification?.status === "failed") {
    return { status: "failed", title: "补丁回放验证未通过", score: 0, evidence,
      description: "后端实际回放返回失败，请查看关联证据与验证日志。" };
  }
  if (verification?.status === "skipped") {
    return { status: "skipped", title: "本次任务未执行补丁回放", score: 0, evidence,
      description: "本次分析跳过了补丁验证阶段，报告中的修复建议尚未经回放确认。" };
  }
  return { status: "pending", title: task?.status === "running" ? "等待补丁验证" : "补丁尚未验证", score: 0, evidence,
    description: "尚无实际回放结果。报告和日志中的成功描述不能代替补丁验证。" };
}

function statusColor(status: PatchVerificationSummary["status"]) {
  if (status === "verified") return "success";
  if (status === "failed") return "exception";
  return "normal";
}

function tagColor(status: PatchVerificationSummary["status"]) {
  if (status === "verified") return "success";
  if (status === "failed") return "error";
  return "default";
}

const PatchVerificationPanel: React.FC<PatchVerificationPanelProps> = ({ task, events }) => {
  const [open, setOpen] = useState(false);
  const summary = useMemo(() => buildSummary(task, events), [events, task]);
  const Icon = summary.status === "failed" ? AlertTriangle : ShieldCheck;

  return (
    <section className="product-summary-card patch-verification-card">
      <div className="product-summary-head">
        <Space size={8}>
          <Icon size={16} />
          <Typography.Text strong>补丁验证</Typography.Text>
        </Space>
        <Tag color={tagColor(summary.status)}>
          {summary.status === "verified" ? "已通过" : summary.status === "failed" ? "未通过" : summary.status === "skipped" ? "已跳过" : summary.status === "archived" ? "历史记录" : "未验证"}
        </Tag>
      </div>

      <div className="patch-verification-body">
        <div className="patch-score">
          <Progress
            type="circle"
            size={78}
            percent={summary.score}
            status={statusColor(summary.status)}
            format={() => (summary.status === "verified" ? <CheckCircle2 size={22} /> : <ShieldCheck size={22} />)}
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
