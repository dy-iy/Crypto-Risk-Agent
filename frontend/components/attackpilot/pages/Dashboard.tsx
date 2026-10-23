import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "../services/navigation";
import { Alert, App as AntdApp, Button, Drawer, Layout, Segmented, Space, Spin, Tabs, Tag, Typography } from "antd";
import { Activity, ArrowLeft, Bot, FileText, FolderOpen, ListTree, RefreshCcw, ShieldCheck, Wifi, WifiOff, X } from "lucide-react";
import AgentNavigator, { AgentStats } from "../components/AgentNavigator";
import AgentFileLogs from "../components/AgentFileLogs";
import AgentConsistencyPanel from "../components/AgentConsistencyPanel";
import AgentInsights from "../components/AgentInsights";
import AgentTimeline from "../components/AgentTimeline";
import AnalysisLivePanel from "../components/AnalysisLivePanel";
import AttackReplayTimeline from "../components/AttackReplayTimeline";
import DappContextButton from "../components/DappContextButton";
import ForensicAssistantDrawer from "../components/ForensicAssistantDrawer";
import LogDetailDrawer from "../components/LogDetailDrawer";
import LogStream from "../components/LogStream";
import LearningGuidePanel from "../components/LearningGuidePanel";
import MacroAnalysisPanel from "../components/MacroAnalysisPanel";
import StructuredReport from "../components/StructuredReport";
import { createReportTranslation, errorMessage, getAutomatedReview, getMacroAnalysis, getReportTranslation, getTask, getTaskLogs } from "../services/api";
import TaskEventService from "../services/TaskEventService";
import {
  LanguageMode,
  LogLevel,
  LogMessage,
  AutomatedReviewResponse,
  MacroAnalysisResponse,
  ProductViewMode,
  Task,
  TaskEvent,
  TaskStatus,
} from "../types";
import { modeLabel, t } from "../utils/i18n";
import { agentDisplayName, formatDurationZh, taskStatusLabel } from "../utils/presentation";
import { getPatchVerificationPresentation } from "../utils/verification";
import { useAttackPilotIdentity } from "../context";
import "../detail.css";


const { Content } = Layout;

type MainTabItem = NonNullable<React.ComponentProps<typeof Tabs>["items"]>[number];

function isLogEvent(event: TaskEvent): event is LogMessage {
  return event.type === "LOG";
}

function formatDuration(duration?: number | null) {
  return formatDurationZh(duration);
}

function getStatusColor(status?: TaskStatus) {
  if (status === TaskStatus.COMPLETED) return "success";
  if (status === TaskStatus.FAILED) return "error";
  if (status === TaskStatus.RUNNING) return "processing";
  return "default";
}

function isTerminalTask(status?: TaskStatus) {
  return status === TaskStatus.COMPLETED || status === TaskStatus.FAILED || status === TaskStatus.CANCELLED;
}

function getDefaultMainTab(mode: ProductViewMode, running = false) {
  if (running) return "live";
  if (mode === "learn") return "learning";
  if (mode === "auditor") return "macro";
  if (mode === "raw") return "stream";
  return "report";
}

const PERSISTED_LOG_PAGE_SIZE = 1000;
const MAX_PERSISTED_LOG_PAGES = 5;

async function fetchPersistedTaskEvents(taskId: string, signal?: AbortSignal) {
  let cursor: number | null = null;
  let events: LogMessage[] = [];

  for (let pageIndex = 0; pageIndex < MAX_PERSISTED_LOG_PAGES; pageIndex += 1) {
    const page = await getTaskLogs(taskId, { limit: PERSISTED_LOG_PAGE_SIZE, before_id: cursor }, signal);
    events = [...page.events, ...events];
    if (!page.has_more || !page.next_before_id) break;
    cursor = page.next_before_id;
  }

  return events;
}

const Dashboard: React.FC = () => {
  const { taskId } = useParams<{ taskId: string }>();
  const navigate = useNavigate();
  const { message } = AntdApp.useApp();
  const { userId, onLogin } = useAttackPilotIdentity();
  const mountedRef = useRef(true);
  const completionNoticeTaskRef = useRef<string | null>(null);
  const [task, setTask] = useState<Task | null>(null);
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [selectedAgentChoice, setSelectedAgent] = useState<string | "all">("all");
  const [selectedLog, setSelectedLog] = useState<LogMessage | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [wsStatus, setWsStatus] = useState<WebSocket["readyState"] | null>(null);
  const [errorMsg, setErrorMsg] = useState("");
  const [loadingTask, setLoadingTask] = useState(true);
  const [connectionRevision, setConnectionRevision] = useState(0);
  const [viewMode, setViewMode] = useState<ProductViewMode>("report");
  const language: LanguageMode = "zh";
  const [activeMainTab, setActiveMainTab] = useState("");
  const [macroAnalysis, setMacroAnalysis] = useState<MacroAnalysisResponse | null>(null);
  const [automatedReview, setAutomatedReview] = useState<AutomatedReviewResponse | null>(null);
  const [reportLanguage, setReportLanguage] = useState<"zh" | "original">("zh");
  const [translationRevision, setTranslationRevision] = useState(0);
  const [translation, setTranslation] = useState<{
    taskId: string; source: string; report: string | null;
    status: "translating" | "ready" | "missing" | "original" | "error";
    error?: string;
  } | null>(null);
  const resolvedTranslationRef = useRef<{ taskId: string; source: string } | null>(null);
  const verification = getPatchVerificationPresentation(task);

  const refreshTask = useCallback(async (signal?: AbortSignal) => {
    if (!taskId) return null;
    try {
      const nextTask = await getTask(taskId, signal);
      if (signal?.aborted) return null;
      setTask(nextTask);
      setErrorMsg("");
      return nextTask;
    } catch (error) {
      if (!signal?.aborted) setErrorMsg(errorMessage(error));
      return null;
    } finally {
      if (!signal?.aborted) setLoadingTask(false);
    }
  }, [taskId]);

  useEffect(() => {
    mountedRef.current = true;
    if (!taskId) return;

    let cancelled = false;
    const controller = new AbortController();
    let notifyReportCompletion = false;
    TaskEventService.disconnect();
    TaskEventService.clearHistory();

    const handleConnect = () => {
      setErrorMsg("");
      setWsStatus(TaskEventService.getConnectionState());
    };

    const handleError = (error: string) => {
      setErrorMsg(error);
      setWsStatus(WebSocket.CLOSED);
    };

    const handleStatus = (status: WebSocket["readyState"] | null) => {
      if (mountedRef.current) setWsStatus(status);
    };

    const handleEvent = (event: TaskEvent) => {
      if (cancelled || !mountedRef.current || (event.task_id && event.task_id !== taskId)) return;
      setEvents((prev) => [...prev, event].slice(-5000));

      if (event.type === "TASK_STATUS") {
        setTask((prev) => ({
          ...prev,
          task_id: event.task_id,
          dapp_name: event.dapp_name,
          status: event.status,
          created_at: event.created_at ?? prev?.created_at ?? "",
          completed_at: event.completed_at,
          duration: event.duration,
          final_report: prev?.final_report,
          result: prev?.result,
          error: event.error,
          archived: event.archived ?? prev?.archived ?? false,
        }));
      }

      if (event.type === "TASK_FINAL") {
        if (notifyReportCompletion && event.status === TaskStatus.COMPLETED && event.final_report?.trim()
          && completionNoticeTaskRef.current !== taskId) {
          notifyReportCompletion = false;
          completionNoticeTaskRef.current = taskId;
          message.success({ key: `attackpilot-report-ready:${taskId}`, content: "结构化报告已生成，报告和攻击复盘入口已开放。" });
        }
        setTask((prev) => ({
          ...prev,
          task_id: event.task_id,
          dapp_name: event.dapp_name,
          status: event.status,
          created_at: prev?.created_at ?? "",
          completed_at: event.completed_at,
          duration: event.duration,
          final_report: event.final_report,
          result: event.result ?? prev?.result,
          error: event.error,
          archived: event.archived ?? prev?.archived ?? false,
        }));
      }
    };

    const initializeTaskView = async () => {
      const nextTask = await refreshTask(controller.signal);
      if (cancelled || !mountedRef.current || !nextTask) return;

      if (isTerminalTask(nextTask.status)) {
        try {
          const persistedEvents = await fetchPersistedTaskEvents(taskId, controller.signal);
          if (!cancelled && mountedRef.current) {
            setEvents(persistedEvents);
            setWsStatus(null);
          }
        } catch {
          if (!cancelled && mountedRef.current) setErrorMsg("历史任务日志获取失败，请检查日志接口。");
        }
        return;
      }

      notifyReportCompletion = !nextTask.is_demo && !nextTask.final_report?.trim();
      setEvents(TaskEventService.getHistory());
      TaskEventService.subscribe(handleEvent);
      TaskEventService.subscribeStatus(handleStatus);
      TaskEventService.connect(taskId, handleConnect, handleError);
      setWsStatus(TaskEventService.getConnectionState());
    };

    initializeTaskView();

    return () => {
      cancelled = true;
      controller.abort();
      mountedRef.current = false;
      TaskEventService.disconnect();
      TaskEventService.unsubscribe(handleEvent);
      TaskEventService.unsubscribeStatus(handleStatus);
    };
  }, [connectionRevision, message, refreshTask, taskId]);

  const terminalTask = isTerminalTask(task?.status);
  const isTaskRunning = task?.status === TaskStatus.RUNNING || (!terminalTask && wsStatus === WebSocket.OPEN);
  const finalReportText = typeof task?.final_report === "string" ? task.final_report.trim() : "";
  const hasFinalReport = finalReportText.length > 0;
  const hasMacroAnalysis = Boolean(macroAnalysis);
  const hasAutomatedReview = Boolean(automatedReview);
  const hasReplay = hasFinalReport;
  const hasLearningGuide = hasFinalReport || hasMacroAnalysis;
  const hasConsistencyReview = hasFinalReport || hasAutomatedReview;
  const currentTranslation = translation?.taskId === taskId && translation.source === finalReportText ? translation : null;
  const translating = hasFinalReport && reportLanguage === "zh" && (!currentTranslation || currentTranslation.status === "translating");
  const displayedReport = reportLanguage === "zh" && currentTranslation?.report ? currentTranslation.report : finalReportText;
  const displayedTask = useMemo(() => task ? { ...task, final_report: displayedReport } : null, [task, displayedReport]);
  const usingTranslation = reportLanguage === "zh" && currentTranslation?.status === "ready";

  useEffect(() => {
    if (!taskId || !finalReportText) return;
    if (resolvedTranslationRef.current?.taskId === taskId && resolvedTranslationRef.current.source === finalReportText) return;
    let cancelled = false;
    const source = finalReportText;
    getReportTranslation(taskId).then(async (payload) => {
      if (cancelled) return;
      if (payload.status === "missing" && userId) {
        setTranslation({ taskId, source, report: null, status: "translating" });
        payload = await createReportTranslation(taskId);
      }
      if (!cancelled) {
        if (payload.status === "ready" || payload.status === "original") {
          if (!payload.translated_report?.trim()) throw new Error("中文译文内容不完整，当前保留原始报告。请手动重试。");
          resolvedTranslationRef.current = { taskId, source };
        }
        setTranslation({ taskId, source, report: payload.translated_report, status: payload.status });
      }
    }).catch((error: unknown) => {
      if (!cancelled) setTranslation({ taskId, source, report: null, status: "error", error: errorMessage(error) });
    });
    return () => { cancelled = true; };
  }, [finalReportText, taskId, translationRevision, userId]);

  useEffect(() => {
    let cancelled = false;
    if (!taskId || task?.status === undefined) return;
    const controller = new AbortController();

    getMacroAnalysis(taskId, controller.signal)
      .then((payload) => {
        if (!cancelled) setMacroAnalysis(payload);
      })
      .catch(() => {
        if (!cancelled) setMacroAnalysis(null);
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [connectionRevision, taskId, task?.status, task?.completed_at]);

  useEffect(() => {
    let cancelled = false;
    if (!taskId || task?.status === undefined) return;
    const controller = new AbortController();

    getAutomatedReview(taskId, controller.signal)
      .then((payload) => {
        if (!cancelled) setAutomatedReview(payload);
      })
      .catch(() => {
        if (!cancelled) setAutomatedReview(null);
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [connectionRevision, taskId, task?.status, task?.completed_at]);

  const agentStats = useMemo<AgentStats[]>(() => {
    const map = new Map<string, AgentStats>();

    events.forEach((event) => {
      if (!isLogEvent(event)) return;
      const current = map.get(event.agent) ?? { name: event.agent, total: 0, errors: 0, warnings: 0 };
      current.total += 1;
      current.lastSeen = event.timestamp;
      current.lastLevel = event.level;
      if (event.level === LogLevel.ERROR) current.errors += 1;
      if (event.level === LogLevel.WARNING) current.warnings += 1;
      map.set(event.agent, current);
    });

    return Array.from(map.values()).sort((a, b) => {
      const aTime = a.lastSeen ? new Date(a.lastSeen).getTime() : 0;
      const bTime = b.lastSeen ? new Date(b.lastSeen).getTime() : 0;
      return bTime - aTime || b.total - a.total || a.name.localeCompare(b.name);
    });
  }, [events]);

  const selectedAgent = agentStats.some(item => item.name === selectedAgentChoice) ? selectedAgentChoice : "all";

  const totalLogs = events.filter(isLogEvent).length;
  const wsOpen = wsStatus === WebSocket.OPEN;
  const connectionLabel = wsOpen ? t(language, "live") : terminalTask ? t(language, "archived") : t(language, "offline");
  const connectionColor = wsOpen ? "success" : terminalTask ? "default" : "error";
  const activeAgentCount = agentStats.filter((item) => item.total > 0).length;
  const agentIssueCount = agentStats.filter((item) => item.errors > 0 || item.warnings > 0).length;
  const systemStatusLabel = task?.status === TaskStatus.RUNNING || wsOpen
    ? "运行中"
    : terminalTask
      ? taskStatusLabel(task?.status)
      : "待连接";
  const systemStatusTone = agentIssueCount > 0 ? "warning" : task?.status === TaskStatus.FAILED ? "error" : "healthy";
  const systemStatusHint = task?.status === TaskStatus.FAILED ? "分析已失败，请查看任务错误与日志"
    : task?.status === TaskStatus.CANCELLED ? "分析已取消，已产生的记录供核对"
      : agentIssueCount > 0 ? `${agentIssueCount} 个智能体有告警或错误`
        : activeAgentCount > 0 ? "当前已加载日志未发现告警"
          : "暂无可显示的智能体日志";

  const openLog = (log: LogMessage) => {
    setSelectedLog(log);
    setDrawerOpen(true);
  };

  const mainTabItems = useMemo(() => {
    const liveTab: MainTabItem = {
      key: "live",
      label: (
        <Space size={6}>
          <Activity size={14} />
          {language === "zh" ? "分析现场" : "Live Analysis"}
        </Space>
      ),
      children: (
        <AnalysisLivePanel
          task={task}
          events={events}
          agentStats={agentStats}
          selectedAgent={selectedAgent}
          taskId={taskId}
          onSelectLog={openLog}
          onOpenReport={() => setActiveMainTab("report")}
          onOpenTimeline={() => setActiveMainTab("timeline")}
        />
      ),
    };

    const reportTab: MainTabItem = {
      key: "report",
      label: (
        <Space size={6}>
          <FileText size={14} />
          {t(language, "reportTab")}
        </Space>
      ),
      children: (
        <StructuredReport
          task={displayedTask}
          originalTask={task}
          translated={usingTranslation}
          events={events}
          mode={viewMode}
          macroAnalysis={macroAnalysis}
          automatedReview={automatedReview}
          language={language}
        />
      ),
    };

    const replayTab: MainTabItem = {
      key: "attack-replay",
      label: (
        <Space size={6}>
          <ListTree size={14} />
          {t(language, "replayTab")}
        </Space>
      ),
      children: <AttackReplayTimeline task={displayedTask} events={events} mode={viewMode} />,
    };

    const learningTab: MainTabItem = {
      key: "learning",
      label: (
        <Space size={6}>
          <Bot size={14} />
          {language === "zh" ? "学习导览" : "Learning Guide"}
        </Space>
      ),
      children: <LearningGuidePanel task={task} macro={macroAnalysis} language={language} />,
    };

    const macroTab: MainTabItem = {
      key: "macro",
      label: (
        <Space size={6}>
          <ShieldCheck size={14} />
          {t(language, "macroTab")}
        </Space>
      ),
      children: <MacroAnalysisPanel macro={macroAnalysis} language={language} />,
    };

    const consistencyTab: MainTabItem = {
      key: "consistency",
      label: (
        <Space size={6}>
          <ShieldCheck size={14} />
          {language === "zh" ? "一致性检查" : "Consistency"}
        </Space>
      ),
      children: (
        <AgentConsistencyPanel
          task={task}
          events={events}
          macro={macroAnalysis}
          review={automatedReview}
          language={language}
        />
      ),
    };

    const streamTab: MainTabItem = {
      key: "stream",
      label: (
        <Space size={6}>
          <Activity size={14} />
          {t(language, "rawLogsTab")}
        </Space>
      ),
      children: (
        <LogStream
          key={taskId}
          taskId={taskId}
          events={events}
          selectedAgent={selectedAgent}
          onSelectLog={openLog}
          rawMode
          followLatest={!terminalTask}
          onAgentChange={setSelectedAgent}
        />
      ),
    };

    const timelineTab: MainTabItem = {
      key: "timeline",
      label: (
        <Space size={6}>
          <ListTree size={14} />
          {t(language, "timelineTab")}
        </Space>
      ),
      children: <AgentTimeline events={events} selectedAgent={selectedAgent} onSelectLog={openLog} />,
    };

    const tabMap: Record<string, MainTabItem> = {
      live: liveTab,
      report: reportTab,
      "attack-replay": replayTab,
      learning: learningTab,
      macro: macroTab,
      consistency: consistencyTab,
      stream: streamTab,
      timeline: timelineTab,
    };
    const modeOrder: Record<ProductViewMode, string[]> = {
      report: isTaskRunning
        ? ["live", "stream", "timeline", "report", "attack-replay", "macro", "consistency", "learning"]
        : ["report", "attack-replay", "macro", "consistency", "learning", "stream", "timeline"],
      learn: isTaskRunning
        ? ["live", "learning", "stream", "timeline", "attack-replay", "report", "macro", "consistency"]
        : ["learning", "attack-replay", "report", "macro", "consistency", "stream", "timeline"],
      auditor: isTaskRunning
        ? ["live", "macro", "consistency", "stream", "timeline", "report", "attack-replay", "learning"]
        : ["macro", "consistency", "report", "attack-replay", "timeline", "stream", "learning"],
      raw: isTaskRunning
        ? ["live", "stream", "timeline", "report", "macro", "consistency", "attack-replay", "learning"]
        : ["stream", "timeline", "report", "macro", "consistency", "attack-replay", "learning"],
    };

    const availableKeys = new Set(["live", "stream", "timeline"]);
    if (hasFinalReport) availableKeys.add("report");
    if (hasReplay) availableKeys.add("attack-replay");
    if (hasLearningGuide) availableKeys.add("learning");
    if (hasMacroAnalysis) availableKeys.add("macro");
    if (hasConsistencyReview) availableKeys.add("consistency");

    return modeOrder[viewMode]
      .filter((key) => availableKeys.has(key))
      .map((key) => tabMap[key]);
  }, [
    agentStats,
    automatedReview,
    events,
    displayedTask,
    hasConsistencyReview,
    hasFinalReport,
    hasLearningGuide,
    hasMacroAnalysis,
    hasReplay,
    isTaskRunning,
    language,
    macroAnalysis,
    selectedAgent,
    task,
    taskId,
    terminalTask,
    viewMode,
    usingTranslation,
  ]);

  const desiredTab = activeMainTab || getDefaultMainTab(viewMode, isTaskRunning);
  const displayedTab = mainTabItems.some(item => item.key === desiredTab) ? desiredTab : String(mainTabItems[0]?.key || "live");

  const inspectorTabItems = useMemo(
    () => [
      {
        key: "agents",
        label: (
          <Space size={6}>
            <Bot size={14} />
            {t(language, "agentBriefTab")}
          </Space>
        ),
        children: (
          <AgentInsights
            taskStatus={task?.status}
            events={events}
            selectedAgent={selectedAgent}
            onSelectAgent={setSelectedAgent}
            onSelectLog={openLog}
          />
        ),
      },
      {
        key: "agent-files",
        label: (
          <Space size={6}>
            <FolderOpen size={14} />
            {t(language, "fileLogsTab")}
          </Space>
        ),
        children: <AgentFileLogs taskId={taskId ?? ""} />,
      },
      {
        key: "summary",
        label: t(language, "taskTab"),
        children: (
          <div className="task-detail-list">
            <div>
              <span>{t(language, "taskId")}</span>
              <Typography.Text copyable className="text-mono">
                {taskId}
              </Typography.Text>
            </div>
            <div>
              <span>{t(language, "status")}</span>
              <Space size={6}>
                <Tag color={getStatusColor(task?.status)}>{taskStatusLabel(task?.status)}</Tag>
                {task?.archived ? <Tag>{t(language, "archived")}</Tag> : null}
              </Space>
            </div>
            <div>
              <span>{t(language, "created")}</span>
              <Typography.Text>{task?.created_at ?? "暂无"}</Typography.Text>
            </div>
            <div>
              <span>{t(language, "completed")}</span>
              <Typography.Text>{task?.completed_at ?? "暂无"}</Typography.Text>
            </div>
            <div>
              <span>{t(language, "error")}</span>
              <Typography.Text type={task?.error ? "danger" : "secondary"}>{task?.error ?? t(language, "none")}</Typography.Text>
            </div>
          </div>
        ),
      },
    ],
    [events, language, selectedAgent, task, taskId],
  );

  return (
    <Layout className="ap-page ap-detail-page">
      <Content className="ap-page-content">
        <div className="ap-detail-breadcrumb">
          <Button type="text" icon={<ArrowLeft size={15} />} onClick={() => navigate("/tasks")}>任务库</Button>
          <Typography.Text type="secondary" className="text-mono" copyable={{ text: taskId }} title={taskId}>
            {taskId?.slice(0, 8)}...
          </Typography.Text>
        </div>
        <header className="ap-page-heading ap-detail-heading">
          <div>
            <span className="ap-eyebrow">攻击复盘工作台</span>
            <Typography.Title>
              {task?.dapp_name ? `${task.dapp_name} 攻击复盘` : "攻击复盘工作台"}
            </Typography.Title>
            <div className="ap-detail-task-status">
              <Tag color={getStatusColor(task?.status)}>{task?.status ? taskStatusLabel(task.status) : t(language, "loading")}</Tag>
              {task && !task.is_demo && <Tag color={verification.color}>{verification.headerLabel}</Tag>}
              {task?.archived ? <Tag>{t(language, "archived")}</Tag> : null}
            </div>
          </div>
          <div className="ap-page-actions">
            <DappContextButton dappName={task?.dapp_name} />
            <Button icon={<Bot size={15} />} onClick={() => setInspectorOpen(true)}>{t(language, "agentBriefTab")}</Button>
            <Button icon={<Bot size={15} />} onClick={() => setAssistantOpen(true)}>取证助手</Button>
            <Button icon={<RefreshCcw size={15} />} onClick={() => {
              setLoadingTask(true);
              setConnectionRevision(value => value + 1);
            }}>{t(language, "refresh")}</Button>
          </div>
        </header>

        <div className="ap-detail-metadata">
          <div><span>{t(language, "logs")}</span><strong>{totalLogs}</strong></div>
          <div><span>{t(language, "agents")}</span><strong>{agentStats.filter((item) => item.total > 0).length}</strong></div>
          <div><span>{t(language, "duration")}</span><strong>{formatDuration(task?.duration)}</strong></div>
          <Tag icon={wsOpen ? <Wifi size={13} /> : <WifiOff size={13} />} color={connectionColor}>{connectionLabel}</Tag>
        </div>

        <div className="ap-detail-notices">
          {task && <Alert type={task.is_demo ? "info" : "warning"} showIcon title={task.is_demo
            ? "公共历史示例 · 报告与日志来自原项目归档，未在当前环境重新验证。"
            : "实时分析任务 · 仅本人可见。补丁验证状态以报告中的实际执行结果为准。"} />}
          {errorMsg ? <Alert type="error" showIcon message={errorMsg} closable onClose={() => setErrorMsg("")} /> : null}
        </div>

        <section className="ap-detail-workspace">
          <div className="ap-detail-toolbar">
            <div className="ap-detail-view-switcher">
              <Typography.Text type="secondary">视图模式</Typography.Text>
              <Segmented
                aria-label="视图模式"
                value={viewMode}
                onChange={(value) => { setViewMode(value as ProductViewMode); setActiveMainTab(""); }}
                options={[
                  { label: modeLabel(language, "report"), value: "report" },
                  { label: modeLabel(language, "learn"), value: "learn" },
                  { label: modeLabel(language, "auditor"), value: "auditor" },
                  { label: modeLabel(language, "raw"), value: "raw" },
                ]}
              />
              {selectedAgent !== "all" ? <Button className="ap-detail-agent-filter" size="small" icon={<X size={13} />} title="显示全部智能体" aria-label="显示全部智能体" onClick={() => setSelectedAgent("all")}>{agentDisplayName(selectedAgent)}</Button> : null}
            </div>
        {hasFinalReport && <div className="report-language-toolbar ap-detail-report-language">
          <Space wrap>
            <Typography.Text strong>报告语言</Typography.Text>
            <Segmented value={reportLanguage} onChange={(value) => setReportLanguage(value as "zh" | "original")}
              options={[{ label: "中文", value: "zh" }, { label: "原文", value: "original" }]} />
            {translating ? <><Spin size="small" /><Typography.Text type="secondary">正在准备中文译文，当前显示原文…</Typography.Text></> : null}
            {usingTranslation ? <Tag color="blue">中文译文 · 可切换原文核对</Tag> : null}
            {reportLanguage === "original" ? <Tag>模型原始报告</Tag> : null}
            {reportLanguage === "zh" && currentTranslation?.status === "original" ? <Tag>原报告已为中文</Tag> : null}
          </Space>
          {reportLanguage === "zh" && currentTranslation?.status === "missing" && !userId &&
            <Alert type="info" showIcon title="这份历史报告尚无中文译文，当前显示归档原文。"
              action={<Button size="small" onClick={onLogin}>登录生成中文译文</Button>} />}
          {reportLanguage === "zh" && currentTranslation?.status === "error" &&
            <Alert type="warning" showIcon title="中文译文暂时无法加载，当前显示原文。" description={currentTranslation.error}
              action={<Button size="small" onClick={() => { setTranslation(null); setTranslationRevision(value => value + 1); }}>重试</Button>} />}
        </div>}

          </div>
          {loadingTask && !task ? <div className="center-loading"><Spin /></div> : (
            <div className="ap-detail-reader">
              <Tabs activeKey={displayedTab} onChange={setActiveMainTab} items={mainTabItems} tabBarGutter={24} />
            </div>
          )}
        </section>
      </Content>

      <Drawer className="ap-detail-drawer" title={t(language, "agentBriefTab")} open={inspectorOpen} onClose={() => setInspectorOpen(false)} size={440}
        getContainer={() => document.querySelector<HTMLElement>(".attackpilot-root") || document.body}>
        <AgentNavigator
          stats={agentStats}
          selectedAgent={selectedAgent}
          onSelectAgent={(agent) => { setSelectedAgent(agent); setInspectorOpen(false); }}
          systemStatus={{ label: systemStatusLabel, hint: systemStatusHint, tone: systemStatusTone }}
        />
        <Tabs defaultActiveKey="agents" items={inspectorTabItems} />
      </Drawer>

      <LogDetailDrawer
        taskId={taskId ?? ""}
        log={selectedLog}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      />
      <ForensicAssistantDrawer
        open={assistantOpen}
        onOpen={() => setAssistantOpen(true)}
        onClose={() => setAssistantOpen(false)}
        scope="task"
        taskId={taskId}
        title="任务取证助手"
      />
    </Layout>
  );
};

export default Dashboard;
