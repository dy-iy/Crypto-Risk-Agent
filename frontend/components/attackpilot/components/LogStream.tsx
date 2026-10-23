import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { App as AntdApp, Button, Empty, Input, Select, Tooltip } from "antd";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  CirclePause,
  CirclePlay,
  FileWarning,
  FileText,
  Search,
  TerminalSquare,
  Wrench,
} from "lucide-react";
import { LogLevel, LogMessage, MsgType, TaskEvent } from "../types";
import { errorMessage, getTaskLogs } from "../services/api";
import { agentDisplayName, logLevelLabel, messageTypeLabel, taskStatusLabel } from "../utils/presentation";
import "../logs.css";

interface LogStreamProps {
  events: TaskEvent[];
  selectedAgent: string | "all";
  onSelectLog: (log: LogMessage) => void;
  taskId?: string;
  rawMode?: boolean;
  followLatest?: boolean;
  onAgentChange?: (agent: string | "all") => void;
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

const ROW_HEIGHT = 112;
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

function getPreview(content: string, query: string) {
  const text = content.replace(/```[^\n]*\n|```/g, " ").replace(/(^|\n)\s{0,3}#{1,6}\s+/g, "$1").replace(/\s+/g, " ").trim();
  const match = query ? text.toLowerCase().indexOf(query.toLowerCase()) : -1;
  const start = match > 80 ? match - 60 : 0;
  return `${start ? "…" : ""}${text.slice(start, start + 360)}${text.length > start + 360 ? "…" : ""}`;
}

function highlightPreview(content: string, query: string) {
  if (!query) return content;
  const index = content.toLowerCase().indexOf(query.toLowerCase());
  if (index < 0) return content;
  return <>{content.slice(0, index)}<mark>{content.slice(index, index + query.length)}</mark>{content.slice(index + query.length)}</>;
}

const LogStream: React.FC<LogStreamProps> = ({ events, selectedAgent, onSelectLog, taskId, rawMode = false, followLatest = !rawMode, onAgentChange }) => {
  const { message } = AntdApp.useApp();
  const scrollRef = useRef<HTMLDivElement>(null);
  const [following, setFollowing] = useState({ active: followLatest, agent: selectedAgent });
  const autoScroll = following.active && following.agent === selectedAgent;
  const setAutoScroll = (active: boolean) => setFollowing({ active, agent: selectedAgent });
  const [query, setQuery] = useState("");
  const [level, setLevel] = useState<"all" | LogLevel>("all");
  const [messageType, setMessageType] = useState<"all" | MsgType>("all");
  const filterKey = JSON.stringify([query, level, messageType, selectedAgent]);
  const [persistedEvents, setPersistedEvents] = useState<LogMessage[]>([]);
  const [nextBeforeId, setNextBeforeId] = useState<number | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loadingPage, setLoadingPage] = useState(false);
  const [initialPageError, setInitialPageError] = useState("");
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(640);
  const pendingAnchorRef = useRef<{ key: string; offset: number } | null>(null);
  const requestGenerationRef = useRef(0);
  const pageRequestRef = useRef(false);
  const pageControllerRef = useRef<AbortController | null>(null);
  const appliedFilterRef = useRef(filterKey);
  const visibleEventsRef = useRef<TaskEvent[]>([]);

  const resetScroll = () => {
    setAutoScroll(false);
    setScrollTop(0);
    if (scrollRef.current) scrollRef.current.scrollTop = 0;
  };

  const sourceEvents = useMemo(
    () => (rawMode ? mergeEvents(persistedEvents, events) : events),
    [events, persistedEvents, rawMode],
  );

  useEffect(() => {
    if (!rawMode || !taskId) return;
    let alive = true;
    const controller = new AbortController();
    pageControllerRef.current = controller;
    getTaskLogs(taskId, { limit: 240 }, controller.signal).then(page => {
      if (!alive) return;
      setPersistedEvents(page.events);
      setNextBeforeId(page.next_before_id ?? null);
      setHasMore(page.has_more);
      setInitialPageError("");
    }).catch(error => { if (alive) setInitialPageError(errorMessage(error)); });
    return () => { alive = false; requestGenerationRef.current += 1; pageControllerRef.current?.abort(); };
  }, [rawMode, taskId]);

  const filteredEvents = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return sourceEvents.filter((event) => {
      if (isLogEvent(event)) {
        if (selectedAgent !== "all" && event.agent !== selectedAgent) return false;
        if (level !== "all" && event.level !== level) return false;
        if (messageType !== "all" && event.message_type !== messageType) return false;
        if (normalizedQuery) {
          const haystack = `${event.agent} ${agentDisplayName(event.agent)} ${event.level} ${logLevelLabel(event.level)} ${event.message_type} ${messageTypeLabel(event.message_type)} ${event.message}`.toLowerCase();
          return haystack.includes(normalizedQuery);
        }
        return true;
      }

      if (selectedAgent !== "all" || level !== "all" || messageType !== "all") return false;
      if (!getControlText(event)) return false;
      if (normalizedQuery) return getControlText(event).toLowerCase().includes(normalizedQuery);
      return true;
    });
  }, [level, messageType, query, selectedAgent, sourceEvents]);

  const agents = useMemo(() => Array.from(new Set(sourceEvents.filter(isLogEvent).map(event => event.agent))), [sourceEvents]);

  const loadLogPage = async (cursor?: number | null) => {
    if (!taskId || pageRequestRef.current) return;
    const generation = requestGenerationRef.current;
    const controller = new AbortController();
    pageControllerRef.current?.abort();
    pageControllerRef.current = controller;
    pageRequestRef.current = true;
    try {
      setLoadingPage(true);
      const page = await getTaskLogs(taskId, { limit: 240, before_id: cursor ?? undefined }, controller.signal);
      if (generation !== requestGenerationRef.current) return;
      const top = scrollRef.current?.scrollTop || 0;
      const firstIndex = Math.floor(top / ROW_HEIGHT);
      const anchor = appliedFilterRef.current === filterKey ? visibleEventsRef.current[firstIndex] : null;
      pendingAnchorRef.current = anchor ? { key: getEventKey(anchor, firstIndex), offset: top % ROW_HEIGHT } : null;
      setAutoScroll(false);
      setPersistedEvents((prev) => [...page.events, ...prev]);
      setNextBeforeId(page.next_before_id ?? null);
      setHasMore(page.has_more);
      setInitialPageError("");
    } catch {
      if (generation === requestGenerationRef.current) message.error("日志分页加载失败，请重试。");
    } finally {
      if (generation === requestGenerationRef.current) {
        pageRequestRef.current = false;
        setLoadingPage(false);
      }
    }
  };

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

  useLayoutEffect(() => {
    const node = scrollRef.current;
    if (!node) return;
    visibleEventsRef.current = filteredEvents;
    if (appliedFilterRef.current !== filterKey) {
      appliedFilterRef.current = filterKey;
      pendingAnchorRef.current = null;
      node.scrollTop = 0;
      return;
    }
    const anchor = pendingAnchorRef.current;
    pendingAnchorRef.current = null;
    if (anchor) {
      const index = filteredEvents.findIndex((event, i) => getEventKey(event, i) === anchor.key);
      if (index >= 0) node.scrollTop = index * ROW_HEIGHT + anchor.offset;
    } else if (autoScroll) node.scrollTop = node.scrollHeight;
  }, [autoScroll, filterKey, filteredEvents]);

  const virtualRange = useMemo(() => {
    const start = Math.max(0, Math.min(filteredEvents.length - 1, Math.floor(scrollTop / ROW_HEIGHT)) - OVERSCAN);
    const visibleCount = Math.ceil(viewportHeight / ROW_HEIGHT) + OVERSCAN * 2;
    const end = Math.min(filteredEvents.length, start + visibleCount);
    return { start, end };
  }, [filteredEvents.length, scrollTop, viewportHeight]);

  const virtualEvents = filteredEvents.slice(virtualRange.start, virtualRange.end);
  const topPadding = virtualRange.start * ROW_HEIGHT;
  const bottomPadding = Math.max(0, (filteredEvents.length - virtualRange.end) * ROW_HEIGHT);

  return (
    <section className="stream-panel log-reader">
      <div className="stream-toolbar">
        <div className="log-reader-filters">
          <Input
            allowClear
            className="stream-search"
            prefix={<Search size={14} />}
            placeholder="搜索日志"
            aria-label="搜索日志"
            value={query}
            onChange={(event) => { resetScroll(); setQuery(event.target.value); }}
          />
          {rawMode && onAgentChange ? <Select
            aria-label="日志智能体"
            value={selectedAgent}
            onChange={(value) => { resetScroll(); onAgentChange(value); }}
            options={[{ label: "全部智能体", value: "all" }, ...agents.map(agent => ({ label: agentDisplayName(agent), value: agent }))]}
          /> : null}
          <Select
            size="middle"
            value={level}
            aria-label="日志级别"
            onChange={(value) => { resetScroll(); setLevel(value); }}
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
            aria-label="日志类型"
            onChange={(value) => { resetScroll(); setMessageType(value); }}
            options={[
              { label: "全部类型", value: "all" },
              { label: "文本", value: MsgType.TEXT },
              { label: "文档", value: MsgType.MARKDOWN },
              { label: "工具调用", value: MsgType.TOOL_CALL },
              { label: "结果", value: MsgType.RESULT },
            ]}
          />
        </div>
        <Tooltip title={autoScroll ? "暂停自动滚动" : "恢复自动滚动"}>
          <Button
            aria-label={autoScroll ? "暂停自动滚动" : "恢复自动滚动"}
            aria-pressed={autoScroll}
            icon={autoScroll ? <CirclePause size={15} /> : <CirclePlay size={15} />}
            onClick={() => setAutoScroll(!autoScroll)}
          >跟随最新</Button>
        </Tooltip>
      </div>

      {rawMode ? (
        <div className="raw-recovery-bar">
          <div className="log-reader-counts">
            <span><strong>{filteredEvents.length}</strong> 条可见</span>
            <span>{persistedEvents.length} 条已恢复</span>
            {initialPageError && <span role="alert">日志恢复失败：{initialPageError}</span>}
          </div>
          <div className="log-reader-page-actions">
            {query || level !== "all" || messageType !== "all" || selectedAgent !== "all" ? <Button size="small" type="text" onClick={() => {
              resetScroll(); setQuery(""); setLevel("all"); setMessageType("all"); onAgentChange?.("all");
            }}>重置筛选</Button> : null}
            <Button
              size="small"
              loading={loadingPage}
              disabled={!hasMore && !initialPageError}
              onClick={() => loadLogPage(initialPageError ? null : nextBeforeId)}
            >
              {initialPageError ? "重试日志加载" : "加载更早日志"}
            </Button>
          </div>
        </div>
      ) : null}

      <div
        ref={scrollRef}
        className="log-stream virtual-log-stream log-reader-viewport"
        aria-label="日志列表"
        onWheel={(event) => { if (event.deltaY < 0) setAutoScroll(false); }}
        onTouchStart={() => setAutoScroll(false)}
        onScroll={(event) => {
          const node = event.currentTarget;
          setScrollTop(node.scrollTop);
          if (node.scrollHeight - node.scrollTop - node.clientHeight > ROW_HEIGHT) setAutoScroll(false);
        }}
      >
        {filteredEvents.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有符合条件的事件" />
        ) : (
          <div className="log-reader-items">
            <div style={{ height: topPadding }} />
            {virtualEvents.map((event, index) => {
            const realIndex = virtualRange.start + index;
            if (!isLogEvent(event)) {
              const isWarning = event.type === "LOG_DROPPED" || event.type === "HEARTBEAT_TIMEOUT";
              return (
                <div key={getEventKey(event, realIndex)} className="log-stream-row" style={{ height: ROW_HEIGHT }}>
                <div className={isWarning ? "control-event warning" : "control-event"}>
                  {isWarning ? <AlertTriangle size={14} /> : <CheckCircle2 size={14} />}
                  <span>{getControlText(event)}</span>
                </div>
                </div>
              );
            }

            const contentPreview = getPreview(event.message, query.trim());
            return (
              <div key={getEventKey(event, realIndex)} className="log-stream-row" style={{ height: ROW_HEIGHT }}>
              <button
                className={`log-event ${getLevelClass(event.level)}`}
                onClick={() => onSelectLog(event)}
                type="button"
                title="查看完整日志"
              >
                <div className="log-event-meta">
                  <span className="log-time">{formatTime(event.timestamp)}</span>
                  <span className="log-reader-agent" title={agentDisplayName(event.agent)}>{agentDisplayName(event.agent)}</span>
                  <span className={`log-reader-level ${getLevelClass(event.level)}`}>{logLevelLabel(event.level)}</span>
                  <span className="message-type" title={messageTypeLabel(event.message_type)} aria-label={messageTypeLabel(event.message_type)}>
                    {getTypeIcon(event.message_type)}
                    <span>{messageTypeLabel(event.message_type)}</span>
                  </span>
                  {event.is_truncated ? <FileWarning size={14} className="log-reader-truncated" aria-label="内容已截断" /> : null}
                  <ChevronRight size={14} className="log-reader-open" aria-hidden="true" />
                </div>
                <div className="log-event-body">
                  {highlightPreview(contentPreview, query.trim())}
                </div>
              </button>
              </div>
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
