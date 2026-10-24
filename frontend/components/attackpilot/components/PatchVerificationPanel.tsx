import React, { useMemo, useState } from "react";
import { Button, Space, Tag, Typography } from "antd";
import { AlertTriangle, SearchCheck, ShieldCheck } from "lucide-react";
import { EvidenceItem, LogMessage, Task, TaskEvent } from "../types";
import {
  compactEvidenceText,
  isLogEvent,
  isLowValueOperationalLog,
  normalizeEvidenceMarkdown,
} from "../utils/evidence";
import { getNativeProfitComparison, getPatchCompileDiagnostics, getPatchVerificationDimensions, getPatchVerificationPresentation, NativeProfitComparison, PatchCompileDiagnostic, PatchVerificationDimension, PatchVerificationPresentation, PatchVerificationStatus } from "../utils/verification";
import EvidenceDrawer from "./EvidenceDrawer";

interface PatchVerificationPanelProps {
  task: Task | null;
  events: TaskEvent[];
}

interface PatchVerificationSummary extends PatchVerificationPresentation {
  evidence: EvidenceItem[];
  dimensions: PatchVerificationDimension[];
  compileDiagnostics: PatchCompileDiagnostic[];
  nativeProfit: NativeProfitComparison;
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
        title: `${log.agent} 补丁记录`,
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
  return { ...getPatchVerificationPresentation(task), evidence, dimensions: getPatchVerificationDimensions(task),
    compileDiagnostics: getPatchCompileDiagnostics(task), nativeProfit: getNativeProfitComparison(task) };
}

function PatchStatusIcon({ status }: { status: PatchVerificationStatus }) {
  return (
    <svg className={`patch-status-icon is-${status}`} width="64" height="64" viewBox="0 0 64 64"
      fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
      aria-hidden="true" focusable="false">
      <circle cx="32" cy="32" r="27" fill="currentColor" fillOpacity="0.06" strokeOpacity="0.3" strokeWidth="2" />
      {status === "verified" ? <path d="m20 32 8 8 16-16" strokeWidth="3.5" />
        : status === "failed" ? <path d="m24 24 16 16m0-16L24 40" strokeWidth="3" />
        : status === "not_run" || status === "unverified" ? <path d="M32 19v13l9 5" />
        : status === "blocked" || status === "error" ? <><path d="M32 21v14" /><circle cx="32" cy="42" r="1" fill="currentColor" stroke="none" /></>
        : status === "skipped" ? <path d="M23 32h18" strokeWidth="3" />
        : <><rect x="22" y="28" width="20" height="15" rx="2" /><rect x="20" y="22" width="24" height="6" rx="1.5" /><path d="M28 34h8" /></>}
    </svg>
  );
}

const PatchVerificationPanel: React.FC<PatchVerificationPanelProps> = ({ task, events }) => {
  const [open, setOpen] = useState(false);
  const summary = useMemo(() => buildSummary(task, events), [events, task]);
  const Icon = ["failed", "blocked", "error"].includes(summary.status) ? AlertTriangle : ShieldCheck;

  return (
    <section className="product-summary-card patch-verification-card">
      <div className="product-summary-head">
        <Space size={8}>
          <Icon size={16} />
          <Typography.Text strong>补丁验证</Typography.Text>
        </Space>
        <Tag color={summary.color}>
          {summary.label}
        </Tag>
      </div>

      <div className="patch-verification-body">
        <div className="patch-score">
          <PatchStatusIcon status={summary.status} />
        </div>
        <div className="patch-summary">
          <Typography.Text strong>{summary.title}</Typography.Text>
          <Typography.Paragraph>{summary.description}</Typography.Paragraph>
          {summary.compileDiagnostics.map((diagnostic, index) => <Typography.Paragraph type="secondary" key={index}>
            {`${diagnostic.target}${diagnostic.compilerVersion ? ` · Solidity ${diagnostic.compilerVersion}` : ""}：${diagnostic.description}`}
          </Typography.Paragraph>)}
          {summary.nextStep && <Typography.Paragraph type="secondary">下一步：{summary.nextStep}</Typography.Paragraph>}
          {summary.dimensions.length > 0 && <Space size={[8, 6]} wrap style={{ marginBottom: 12 }} aria-label="补丁验证范围">
            {summary.dimensions.map(dimension => <Tag key={dimension.key}>{dimension.label}：{dimension.value}</Tag>)}
          </Space>}
          {summary.nativeProfit.transactions.length > 0 && <div className="native-profit-comparison" aria-label="原生币收益对比">
            <Typography.Paragraph type="secondary">{summary.nativeProfit.scopeDescription}</Typography.Paragraph>
            <div className="native-profit-table-scroll">
              <table>
                <thead><tr><th scope="col">交易</th><th scope="col">统计地址</th><th scope="col">原版净变化</th><th scope="col">补丁净变化</th></tr></thead>
                <tbody>{summary.nativeProfit.transactions.map(row => <tr key={row.transactionHash}>
                  <td><code>{row.transactionHash}</code></td>
                  <td><code>{row.account}</code></td>
                  <td>{row.control.text}</td>
                  <td>{row.patched.text}</td>
                </tr>)}</tbody>
              </table>
            </div>
          </div>}
          <Space size={8} wrap>
            <Tag color={summary.evidence.length > 0 ? "cyan" : "default"} title="报告片段和相关日志的数量，不代表验证通过次数">{summary.evidence.length} 条相关记录</Tag>
            <Button size="small" icon={<SearchCheck size={14} />} onClick={() => setOpen(true)}>
              查看记录
            </Button>
          </Space>
        </div>
      </div>

      <EvidenceDrawer
        title="补丁相关记录"
        open={open}
        evidence={summary.evidence}
        onClose={() => setOpen(false)}
      />
    </section>
  );
};

export default PatchVerificationPanel;
