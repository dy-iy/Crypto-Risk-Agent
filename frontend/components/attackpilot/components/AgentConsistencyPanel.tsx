import React, { useMemo } from "react";
import { Alert, Progress, Space, Tag, Typography } from "antd";
import { GitCompareArrows, Network, ShieldCheck, TriangleAlert } from "lucide-react";
import { AutomatedReviewResponse, ConsistencyStatus, LanguageMode, MacroAnalysisResponse, Task, TaskEvent } from "../types";
import { analyzeAgentConsistency, localizeConsistencyText } from "../utils/agentConsistency";

interface AgentConsistencyPanelProps {
  task: Task | null;
  events: TaskEvent[];
  macro: MacroAnalysisResponse | null;
  review?: AutomatedReviewResponse | null;
  language?: LanguageMode;
}

function statusColor(status: ConsistencyStatus) {
  if (status === "pass") return "success";
  if (status === "warning") return "warning";
  return "error";
}

function progressStatus(status: ConsistencyStatus) {
  return status === "risk" ? "exception" : "normal";
}

const CHECK_COPY: Record<string, { title: string; description: string }> = {
  "macro-to-debug": {
    title: "宏观筛选与调试目标",
    description: "检查宏观阶段选择的关键交易是否进入后续 Trace 调试和最终报告。",
  },
  "attack-classification-overlap": {
    title: "攻击交易一致性",
    description: "检查多个智能体是否引用同一批攻击交易，避免分析偏离案件范围。",
  },
  "root-to-patch": {
    title: "根因与补丁连续性",
    description: "检查定位阶段识别的根因函数是否被补丁和验证阶段继续使用。",
  },
  "verification-loop": {
    title: "补丁验证闭环",
    description: "检查补丁生成后是否出现重放、成功、失败或验证智能体反馈。",
  },
  "root-cause-quorum": {
    title: "根因共识",
    description: "检查根因结论是否由多个智能体共同支持，而非只出现在最终报告中。",
  },
};

function statusLabel(status: ConsistencyStatus) {
  if (status === "pass") return "通过";
  if (status === "warning") return "需注意";
  return "存在风险";
}

const AgentConsistencyPanel: React.FC<AgentConsistencyPanelProps> = ({
  task,
  events,
  macro,
  review,
  language = "zh",
}) => {
  const isZh = language === "zh";
  const localSummary = useMemo(() => analyzeAgentConsistency(task, events, macro), [events, macro, task]);
  const summary = review
    ? {
        score: review.score,
        status: review.status,
        checks: review.checks,
        agentSignals: review.agent_signals,
        sharedTransactions: review.shared_transactions,
        sharedFunctions: review.shared_functions,
      }
    : localSummary;

  // Also gate older backends which returned fallback scores for failed tasks.
  if (localSummary.status === "unavailable" || summary.status === "unavailable") {
    const ended = task?.status === "failed" || task?.status === "cancelled";
    return (
      <section className="agent-consistency-card">
        <Typography.Title level={4}>{isZh ? "多智能体一致性检查" : "Cross-Agent Consistency"}</Typography.Title>
        <Alert
          showIcon
          type={ended ? "warning" : "info"}
          title={isZh ? (ended ? "分析已终止，无法评估" : "尚未生成有效报告，暂不评分") : "Consistency assessment unavailable"}
          description={task?.error || (isZh ? "缺少完整分析证据，不能据此判断安全或风险。请查看原始日志与文件日志。" : "A completed report is required. Check the task logs for details.")}
        />
      </section>
    );
  }

  return (
    <section className="agent-consistency-card">
      <div className="agent-consistency-head">
        <Space size={8}>
          <GitCompareArrows size={16} />
          <div>
            <Typography.Text strong>{isZh ? "多智能体一致性检查" : "Cross-Agent Consistency"}</Typography.Text>
            <Typography.Text type="secondary">
              {isZh
                ? "检查宏观交易筛选、Trace 调试、根因定位、补丁生成和补丁验证之间是否连续。"
                : "Checks continuity across macro transaction selection, trace debugging, localization, patching, and verification."}
            </Typography.Text>
          </div>
        </Space>
        <Space size={6}>
          <Tag color={review ? "cyan" : "default"}>{review ? "后端审查" : "本地审查"}</Tag>
          <Tag color={statusColor(summary.status)}>{statusLabel(summary.status)}</Tag>
        </Space>
      </div>

      <div className="agent-consistency-overview">
        <div className="agent-consistency-score">
          <Progress
            type="circle"
            percent={summary.score ?? 0}
            size={76}
            status={progressStatus(summary.status)}
          />
          <Typography.Text type="secondary">
            {isZh ? "结论连续性" : "Conclusion continuity"}
          </Typography.Text>
        </div>
        <div className="agent-consistency-shared">
          <div>
            <Space size={6}>
              <Network size={14} />
              <Typography.Text strong>{isZh ? "共享交易" : "Shared transactions"}</Typography.Text>
            </Space>
            <div className="consistency-chip-row">
              {summary.sharedTransactions.length ? (
                summary.sharedTransactions.slice(0, 5).map((item) => (
                  <Tag key={item.value} color="cyan">
                    {item.value.slice(0, 10)}... · {item.agents.length} 个智能体
                  </Tag>
                ))
              ) : (
                <Tag>{isZh ? "暂无共享交易" : "none"}</Tag>
              )}
            </div>
          </div>
          <div>
            <Space size={6}>
              <ShieldCheck size={14} />
              <Typography.Text strong>{isZh ? "共享函数" : "Shared functions"}</Typography.Text>
            </Space>
            <div className="consistency-chip-row">
              {summary.sharedFunctions.length ? (
                summary.sharedFunctions.slice(0, 6).map((item) => (
                  <Tag key={item.value} color="purple">
                    {item.value} · {item.agents.length} 个智能体
                  </Tag>
                ))
              ) : (
                <Tag>{isZh ? "暂无共享函数" : "none"}</Tag>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="consistency-check-grid">
        {summary.checks.map((check) => (
          <article className={`consistency-check-card check-${check.status}`} key={check.id}>
            <div className="consistency-check-title">
              <div>
                <Typography.Text strong>{CHECK_COPY[check.id]?.title ?? localizeConsistencyText(check.title, language)}</Typography.Text>
                <Typography.Paragraph>{CHECK_COPY[check.id]?.description ?? localizeConsistencyText(check.description, language)}</Typography.Paragraph>
              </div>
              <Tag color={statusColor(check.status)}>{check.score}</Tag>
            </div>
            <Progress
              percent={check.score}
              size="small"
              status={progressStatus(check.status)}
              showInfo={false}
            />
            <ul>
              {check.evidence.slice(0, 3).map((item) => (
                <li key={item}>{localizeConsistencyText(item, language)}</li>
              ))}
            </ul>
            {check.recommendation ? (
              <div className="consistency-recommendation">
                <TriangleAlert size={13} />
                <span>{localizeConsistencyText(check.recommendation, language)}</span>
              </div>
            ) : null}
          </article>
        ))}
      </div>
    </section>
  );
};

export default AgentConsistencyPanel;
