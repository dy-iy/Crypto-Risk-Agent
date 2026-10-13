import React, { useMemo } from "react";
import { Button, Empty, Space, Tag, Typography } from "antd";
import { Activity, Bot, FileText, ListTree, SearchCheck } from "lucide-react";
import LogStream from "./LogStream";
import { AgentStats } from "./AgentNavigator";
import { LogLevel, LogMessage, MsgType, Task, TaskEvent, TaskStatus } from "../types";
import { agentDisplayName, messageTypeLabel } from "../utils/presentation";

interface AnalysisLivePanelProps {
  task: Task | null;
  events: TaskEvent[];
  agentStats: AgentStats[];
  selectedAgent: string | "all";
  taskId?: string;
  onSelectLog: (log: LogMessage) => void;
  onOpenReport: () => void;
  onOpenTimeline: () => void;
}

function isLogEvent(event: TaskEvent): event is LogMessage {
  return event.type === "LOG";
}

function inferStage(events: TaskEvent[], task: Task | null) {
  if (task?.status === TaskStatus.COMPLETED) return "报告已生成";
  if (task?.status === TaskStatus.FAILED) return "任务异常";

  const joined = events
    .filter(isLogEvent)
    .slice(-80)
    .map((event) => `${event.agent} ${event.message_type} ${event.message}`)
    .join("\n")
    .toLowerCase();

  if (joined.includes("patch") || joined.includes("replay") || joined.includes("tenderly")) return "补丁验证";
  if (joined.includes("trace") || joined.includes("debug")) return "Trace 调试";
  if (joined.includes("filter") || joined.includes("role") || joined.includes("fund")) return "交易筛选";
  if (joined.includes("receipt") || joined.includes("source") || joined.includes("fetch")) return "链上取证";
  return "等待分析日志";
}

function compactMessage(message: string) {
  const text = message.replace(/\s+/g, " ").trim();
  return text.length > 150 ? `${text.slice(0, 150)}...` : text;
}

const AnalysisLivePanel: React.FC<AnalysisLivePanelProps> = ({
  task,
  events,
  agentStats,
  selectedAgent,
  taskId,
  onSelectLog,
  onOpenReport,
  onOpenTimeline,
}) => {
  const logEvents = useMemo(() => events.filter(isLogEvent), [events]);
  const latestLogs = useMemo(
    () =>
      logEvents
        .filter((event) => event.message_type === MsgType.TOOL_CALL || event.message_type === MsgType.RESULT || event.level !== LogLevel.DEBUG)
        .slice(-4)
        .reverse(),
    [logEvents],
  );
  const currentAgent = agentDisplayName(agentStats.find((item) => item.lastSeen)?.name ?? agentStats[0]?.name) || "等待智能体";
  const stage = inferStage(events, task);
  const isDone = task?.status === TaskStatus.COMPLETED;
  const hasFinalReport = typeof task?.final_report === "string" && task.final_report.trim().length > 0;

  return (
    <section className="analysis-live-panel">
      <div className="analysis-live-head">
        <div>
          <Tag icon={<Activity size={13} />} color={isDone ? "success" : "processing"}>
            {isDone ? "已完成" : "分析现场"}
          </Tag>
          <Typography.Title level={4}>{stage}</Typography.Title>
          <Typography.Text type="secondary">
            系统会持续写入取证、工具调用、阶段结论和验证反馈。你可以先观察现场，等报告完成后再查看最终结论。
          </Typography.Text>
        </div>
        <Space wrap>
          <Button icon={<ListTree size={15} />} onClick={onOpenTimeline}>
            查看时间线
          </Button>
          {hasFinalReport ? (
            <Button type="primary" icon={<FileText size={15} />} onClick={onOpenReport}>
              查看最终报告
            </Button>
          ) : null}
        </Space>
      </div>

      <div className="analysis-live-cards">
        <div>
          <SearchCheck size={16} />
          <span>当前阶段</span>
          <strong>{stage}</strong>
        </div>
        <div>
          <Bot size={16} />
          <span>最近活跃</span>
          <strong>{currentAgent}</strong>
        </div>
        <div>
          <Activity size={16} />
          <span>已产生事件</span>
          <strong>{logEvents.length}</strong>
        </div>
      </div>

      <div className="analysis-live-grid">
        <div className="analysis-live-log-shell">
          <div className="analysis-live-section-title">
            <strong>持续日志</strong>
            <span>只看有用现场；完整日志可切到原始日志视图。</span>
          </div>
          <LogStream
            taskId={taskId}
            events={events}
            selectedAgent={selectedAgent}
            onSelectLog={onSelectLog}
          />
        </div>
        <aside className="analysis-live-latest">
          <div className="analysis-live-section-title">
            <strong>最近发现</strong>
            <span>用于快速判断系统有没有在推进。</span>
          </div>
          {latestLogs.length ? (
            latestLogs.map((log) => (
              <button key={log.log_id || `${log.timestamp}-${log.agent}`} type="button" onClick={() => onSelectLog(log)}>
                <Tag>{agentDisplayName(log.agent)}</Tag>
                <strong>{messageTypeLabel(log.message_type)}</strong>
                <p>{compactMessage(log.message)}</p>
              </button>
            ))
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="等待第一批分析日志" />
          )}
        </aside>
      </div>
    </section>
  );
};

export default AnalysisLivePanel;
