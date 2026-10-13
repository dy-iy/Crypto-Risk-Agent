import React, { useEffect, useMemo, useRef, useState } from "react";
import { Button, Empty, Input, Select, Space, Tag, Tooltip, Typography } from "antd";
import {
  AlertTriangle,
  Bug,
  CheckCircle2,
  ChevronDown,
  CirclePause,
  CirclePlay,
  Code2,
  FileText,
  Search,
  TerminalSquare,
  Wrench,
} from "lucide-react";
import { LogLevel, LogMessage, MsgType, TaskEvent } from "../types";
import { getTaskLogs } from "../services/api";
import MarkdownRenderer from "./MarkdownRenderer";
import { agentDisplayName, logLevelLabel, messageTypeLabel, taskStatusLabel } from "../utils/presentation";

interface LogStreamProps {
  events: TaskEvent[];
  selectedAgent: string | "all";
  onSelectLog: (log: LogMessage) => void;
  taskId?: string;
  rawMode?: boolean;
}

function isLogEvent(event: TaskEvent): event is LogMessage {
  return event.type === "LOG";
}

function getLevelClass(level: LogLevel) {
  if (level === LogLevel.ERROR) return "level-error";
  if (level === LogLevel.WARNING) return "level-warning";
  if (level === LogLevel.DEBUG) return "level-debug";
  return "level-info";
}

function getTypeIcon(type: MsgType) {
  if (type === MsgType.TOOL_CALL) return <Wrench size={14} />;
  if (type === MsgType.RESULT) return <CheckCircle2 size={14} />;
  if (type === MsgType.MARKDOWN) return <FileText size={14} />;
  return <TerminalSquare size={14} />;
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

function getControlText(event: TaskEvent) {
  if (event.type === "TASK_STATUS") return `任务状态已更新为${taskStatusLabel(event.status)}`;
  if (event.type === "TASK_FINAL") return `任务已结束，状态为${taskStatusLabel(event.status)}`;
  if (event.type === "LOG_DROPPED") return `${event.count} 条日志因消息积压被丢弃`;
  if (event.type === "CONNECTED") return event.message;
  if (event.type === "HEARTBEAT_TIMEOUT") return event.message;
  return "";
}

const ROW_HEIGHT = 132;
const OVERSCAN = 8;

function getEventKey(event: TaskEvent, index: number) {
  if (isLogEvent(event)) return event.log_id || `${event.timestamp}-${event.agent}-${index}`;
  return `${event.type}-${"timestamp" in event ? event.timestamp : index}-${index}`;
}

function mergeEvents(persisted: LogMessage[], liveEvents: TaskEvent[]) {
  const map = new Map<string, TaskEvent>();
  persisted.forEach((event, index) => map.set(getEventKey(event, index), event));
  liveEvents.forEach((event, index) => map.set(getEventKey(event, index), event));
  return Array.from(map.values()).sort((a, b) => {
    const aTime = "timestamp" in a && a.timestamp ? new Date(a.timestamp).getTime() : 0;
    const bTime = "timestamp" in b && b.timestamp ? new Date(b.timestamp).getTime() : 0;
    return aTime - bTime;
  });
}

const LogStream: React.FC<LogStreamProps> = ({ events, selectedAgent, onSelectLog, taskId, rawMode = false }) => {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const [query, setQuery] = useState("");
  const [level, setLevel] = useState<"all" | LogLevel>("all");
  const [messageType, setMessageType] = useState<"all" | MsgType>("all");
  const [persistedEvents, setPersistedEvents] = useState<LogMessage[]>([]);
  const [nextBeforeId, setNextBeforeId] = useState<number | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loadingPage, setLoadingPage] = useState(false);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(640);

  const sourceEvents = useMemo(
    () => (rawMode ? mergeEvents(persistedEvents, events) : events),
    [events, persistedEvents, rawMode],
  );

  const loadLogPage = async (cursor?: number | null, replace = false) => {
    if (!taskId || loadingPage) return;
    try {
      setLoadingPage(true);
      const page = await getTaskLogs(taskId, { limit: 240, before_id: cursor ?? undefined });
      setPersistedEvents((prev) => (replace ? page.events : [...page.events, ...prev]));
      setNextBeforeId(page.next_before_id ?? null);
      setHasMore(page.has_more);
    } finally {
      setLoadingPage(false);
    }
  };

  useEffect(() => {
    if (!rawMode || !taskId) return;
    setPersistedEvents([]);
    setNextBeforeId(null);
    setHasMore(false);
    loadLogPage(null, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rawMode, taskId]);

  const filteredEvents = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return sourceEvents.filter((event) => {
      if (isLogEvent(event)) {
        if (selectedAgent !== "all" && event.agent !== selectedAgent) return false;
        if (level !== "all" && event.level !== level) return false;
        if (messageType !== "all" && event.message_type !== messageType) return false;
        if (normalizedQuery) {
          const haystack = `${event.agent} ${event.level} ${event.message_type} ${event.message}`.toLowerCase();
          return haystack.includes(normalizedQuery);
        }
        return true;
      }

      if (selectedAgent !== "all") return false;
      if (normalizedQuery) return getControlText(event).toLowerCase().includes(normalizedQuery);
      return true;
    });
  }, [level, messageType, query, selectedAgent, sourceEvents]);

  useEffect(() => {
    const node = scrollRef.current;
    if (!node) return;
    const resizeObserver = new ResizeObserver(() => {
      setViewportHeight(node.clientHeight || 640);
    });
    resizeObserver.observe(node);
    setViewportHeight(node.clientHeight || 640);
    return () => resizeObserver.disconnect();
  }, []);

  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [autoScroll, filteredEvents.length]);

  const virtualRange = useMemo(() => {
    const start = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN);
    const visibleCount = Math.ceil(viewportHeight / ROW_HEIGHT) + OVERSCAN * 2;
    const end = Math.min(filteredEvents.length, start + visibleCount);
    return { start, end };
  }, [filteredEvents.length, scrollTop, viewportHeight]);

  const virtualEvents = filteredEvents.slice(virtualRange.start, virtualRange.end);
  const topPadding = virtualRange.start * ROW_HEIGHT;
  const bottomPadding = Math.max(0, (filteredEvents.length - virtualRange.end) * ROW_HEIGHT);

  return (
    <section className="stream-panel">
      <div className="stream-toolbar">
        <Space size={8} wrap>
          <Input
            allowClear
            className="stream-search"
            prefix={<Search size={14} />}
            placeholder="搜索日志"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          <Select
            size="middle"
            value={level}
            onChange={setLevel}
            options={[
              { label: "全部级别", value: "all" },
              { label: "信息", value: LogLevel.INFO },
              { label: "警告", value: LogLevel.WARNING },
              { label: "错误", value: LogLevel.ERROR },
              { label: "调试", value: LogLevel.DEBUG },
            ]}
          />
          <Select
            size="middle"
            value={messageType}
            onChange={setMessageType}
            options={[
              { label: "全部类型", value: "all" },
              { label: "文本", value: MsgType.TEXT },
              { label: "文档", value: MsgType.MARKDOWN },
              { label: "工具调用", value: MsgType.TOOL_CALL },
              { label: "结果", value: MsgType.RESULT },
            ]}
          />
        </Space>
        <Tooltip title={autoScroll ? "暂停自动滚动" : "恢复自动滚动"}>
          <Button
            icon={autoScroll ? <CirclePause size={15} /> : <CirclePlay size={15} />}
            onClick={() => setAutoScroll((value) => !value)}
          />
        </Tooltip>
      </div>

      {rawMode ? (
        <div className="raw-recovery-bar">
          <Space size={8} wrap>
            <Tag color="cyan">{filteredEvents.length} 条可见</Tag>
            <Tag>{persistedEvents.length} 条已恢复</Tag>
            <Button
              size="small"
              loading={loadingPage}
              disabled={!hasMore}
              onClick={() => loadLogPage(nextBeforeId)}
            >
              加载更早日志
            </Button>
          </Space>
          <Typography.Text type="secondary">长任务日志采用虚拟列表展示。</Typography.Text>
        </div>
      ) : null}

      <div
        ref={scrollRef}
        className="log-stream virtual-log-stream"
        onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}
      >
        {filteredEvents.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有符合条件的事件" />
        ) : (
          <div>
            <div style={{ height: topPadding }} />
            {virtualEvents.map((event, index) => {
            const realIndex = virtualRange.start + index;
            if (!isLogEvent(event)) {
              const isWarning = event.type === "LOG_DROPPED" || event.type === "HEARTBEAT_TIMEOUT";
              return (
                <div key={getEventKey(event, realIndex)} className={isWarning ? "control-event warning" : "control-event"}>
                  {isWarning ? <AlertTriangle size={14} /> : <ChevronDown size={14} />}
                  <span>{getControlText(event)}</span>
                </div>
              );
            }

            const contentPreview = event.message.length > 900 ? `${event.message.slice(0, 900)}...` : event.message;
            return (
              <button
                key={getEventKey(event, realIndex)}
                className={`log-event ${getLevelClass(event.level)}`}
                onClick={() => onSelectLog(event)}
                type="button"
              >
                <div className="log-event-meta">
                  <span className="log-time">{formatTime(event.timestamp)}</span>
                  <Tag className="agent-tag">{agentDisplayName(event.agent)}</Tag>
                  <Tag className={`level-tag ${getLevelClass(event.level)}`}>{logLevelLabel(event.level)}</Tag>
                  <span className="message-type">
                    {getTypeIcon(event.message_type)}
                    {messageTypeLabel(event.message_type)}
                  </span>
                  {event.is_truncated ? <Tag color="warning">内容已截断</Tag> : null}
                  {event.level === LogLevel.ERROR ? <Bug size={14} className="text-red" /> : null}
                </div>
                <div className="log-event-body">
                  {event.message_type === MsgType.MARKDOWN || event.message_type === MsgType.RESULT ? (
                    <MarkdownRenderer content={contentPreview} compact />
                  ) : (
                    <Typography.Text>{contentPreview}</Typography.Text>
                  )}
                </div>
                {event.message_type === MsgType.TOOL_CALL ? (
                  <div className="tool-hint">
                    <Code2 size={13} />
                    工具调用事件
                  </div>
                ) : null}
              </button>
            );
          })}
            <div style={{ height: bottomPadding }} />
          </div>
        )}
      </div>
    </section>
  );
};

export default LogStream;
