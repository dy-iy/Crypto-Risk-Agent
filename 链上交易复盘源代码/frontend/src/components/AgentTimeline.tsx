import React, { useMemo } from "react";
import { Empty, Space, Tag, Typography } from "antd";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  Clock3,
  FileText,
  MessageSquareText,
  Wrench,
} from "lucide-react";
import { LogLevel, LogMessage, MsgType, TaskEvent, TaskStatus } from "../types";
import { agentDisplayName, messageTypeLabel, taskStatusLabel } from "../utils/presentation";

interface AgentTimelineProps {
  events: TaskEvent[];
  selectedAgent: string | "all";
  onSelectLog: (log: LogMessage) => void;
}

type TimelineItem =
  | {
      kind: "log";
      id: string;
      timestamp: string;
      agent: string;
      level: LogLevel;
      messageType: MsgType;
      title: string;
      preview: string;
      log: LogMessage;
    }
  | {
      kind: "control";
      id: string;
      timestamp: string;
      title: string;
      preview: string;
      status?: TaskStatus;
      warning?: boolean;
    };

function isLogEvent(event: TaskEvent): event is LogMessage {
  return event.type === "LOG";
}

function formatTime(timestamp?: string) {
  if (!timestamp) return "--:--:--";
  return new Date(timestamp).toLocaleTimeString("en-US", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function compactText(value: string, limit = 220) {
  const cleaned = value
    .replace(/```[\s\S]*?```/g, " code block ")
    .replace(/[#*_>`{}[\]]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return cleaned.length > limit ? `${cleaned.slice(0, limit)}...` : cleaned;
}

function getLogTitle(log: LogMessage) {
  if (log.level === LogLevel.ERROR) return "错误信号";
  if (log.level === LogLevel.WARNING) return "警告信号";
  if (log.message_type === MsgType.TOOL_CALL) return "调用工具";
  if (log.message_type === MsgType.RESULT) return "获得结果";
  if (log.message_type === MsgType.MARKDOWN) return "分析记录";
  return "智能体消息";
}

function getControlTitle(event: TaskEvent) {
  if (event.type === "TASK_STATUS") return `任务${taskStatusLabel(event.status)}`;
  if (event.type === "TASK_FINAL") return `最终状态：${taskStatusLabel(event.status)}`;
  if (event.type === "LOG_DROPPED") return "日志积压";
  if (event.type === "HEARTBEAT_TIMEOUT") return "连接心跳超时";
  if (event.type === "CONNECTED") return "实时连接已建立";
  return "系统事件";
}

function getControlPreview(event: TaskEvent) {
  if (event.type === "TASK_STATUS") return `任务状态已更新为${taskStatusLabel(event.status)}。`;
  if (event.type === "TASK_FINAL") return event.final_report ? "最终报告已生成。" : event.error ?? "";
  if (event.type === "LOG_DROPPED") return `${event.count} 条消息因积压被丢弃。`;
  if (event.type === "CONNECTED") return event.message;
  if (event.type === "HEARTBEAT_TIMEOUT") return event.message;
  return "";
}

function getTypeIcon(item: TimelineItem) {
  if (item.kind === "control") return item.warning ? <AlertTriangle size={15} /> : <Clock3 size={15} />;
  if (item.level === LogLevel.ERROR || item.level === LogLevel.WARNING) return <AlertTriangle size={15} />;
  if (item.messageType === MsgType.TOOL_CALL) return <Wrench size={15} />;
  if (item.messageType === MsgType.RESULT) return <CheckCircle2 size={15} />;
  if (item.messageType === MsgType.MARKDOWN) return <FileText size={15} />;
  return <MessageSquareText size={15} />;
}

function getLevelClass(level?: LogLevel, warning?: boolean) {
  if (level === LogLevel.ERROR || warning) return "level-error";
  if (level === LogLevel.WARNING) return "level-warning";
  if (level === LogLevel.DEBUG) return "level-debug";
  return "level-info";
}

const AgentTimeline: React.FC<AgentTimelineProps> = ({ events, selectedAgent, onSelectLog }) => {
  const items = useMemo<TimelineItem[]>(() => {
    return events
      .filter((event) => {
        if (!isLogEvent(event)) return selectedAgent === "all";
        if (selectedAgent !== "all" && event.agent !== selectedAgent) return false;
        return (
          event.level !== LogLevel.DEBUG ||
          event.message_type === MsgType.TOOL_CALL ||
          event.message_type === MsgType.RESULT
        );
      })
      .map((event, index): TimelineItem => {
        if (isLogEvent(event)) {
          return {
            kind: "log",
            id: `${event.timestamp}-${event.agent}-${index}`,
            timestamp: event.timestamp,
            agent: event.agent,
            level: event.level,
            messageType: event.message_type,
            title: getLogTitle(event),
            preview: compactText(event.message),
            log: event,
          };
        }

        return {
          kind: "control",
          id: `${event.type}-${index}`,
          timestamp: "timestamp" in event ? event.timestamp : "",
          title: getControlTitle(event),
          preview: getControlPreview(event),
          status: "status" in event ? event.status : undefined,
          warning: event.type === "LOG_DROPPED" || event.type === "HEARTBEAT_TIMEOUT",
        };
      })
      .slice(-240);
  }, [events, selectedAgent]);

  return (
    <section className="timeline-panel">
      <div className="panel-header">
        <Space size={8}>
          <Clock3 size={16} />
          <Typography.Text strong>智能体时间线</Typography.Text>
        </Space>
        <Tag>{items.length} 个事件</Tag>
      </div>

      <div className="timeline-list">
        {items.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无时间线事件" />
        ) : (
          items.map((item) => {
            const levelClass = getLevelClass(item.kind === "log" ? item.level : undefined, item.kind === "control" && item.warning);
            const content = (
              <>
                <div className="timeline-node">
                  <span className={`timeline-icon ${levelClass}`}>{getTypeIcon(item)}</span>
                  <span className="timeline-line" />
                </div>
                <div className="timeline-content">
                  <div className="timeline-meta">
                    <span className="log-time">{formatTime(item.timestamp)}</span>
                    {item.kind === "log" ? <Tag className="agent-tag">{agentDisplayName(item.agent)}</Tag> : <Tag>系统</Tag>}
                    {item.kind === "log" ? (
                      <Tag className={`level-tag ${levelClass}`}>{messageTypeLabel(item.messageType)}</Tag>
                    ) : item.status ? (
                      <Tag>{taskStatusLabel(item.status)}</Tag>
                    ) : null}
                  </div>
                  <Typography.Text strong>{item.title}</Typography.Text>
                  <Typography.Paragraph ellipsis={{ rows: 2 }} className="timeline-preview">
                    {item.preview || "暂无预览内容。"}
                  </Typography.Paragraph>
                </div>
                {item.kind === "log" ? <ChevronRight size={15} className="timeline-open" /> : null}
              </>
            );

            return item.kind === "log" ? (
              <button key={item.id} className="timeline-item clickable" type="button" onClick={() => onSelectLog(item.log)}>
                {content}
              </button>
            ) : (
              <div key={item.id} className="timeline-item">
                {content}
              </div>
            );
          })
        )}
      </div>
    </section>
  );
};

export default AgentTimeline;
