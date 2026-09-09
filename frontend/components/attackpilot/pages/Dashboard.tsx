import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "../services/navigation";
import { Alert, App as AntdApp, Button, Layout, Segmented, Space, Spin, Tabs, Tag, Typography } from "antd";
import { Activity, ArrowLeft, Bot, FileText, FolderOpen, Home, ListTree, RefreshCcw, ShieldCheck, Wifi, WifiOff } from "lucide-react";
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
import { getAutomatedReview, getMacroAnalysis, getTask, getTaskLogs } from "../services/api";
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
import { formatDurationZh, taskStatusLabel } from "../utils/presentation";


const { Header, Content } = Layout;

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

async function fetchPersistedTaskEvents(taskId: string) {
  let cursor: number | null = null;
  let events: LogMessage[] = [];

  for (let pageIndex = 0; pageIndex < MAX_PERSISTED_LOG_PAGES; pageIndex += 1) {
    const page = await getTaskLogs(taskId, { limit: PERSISTED_LOG_PAGE_SIZE, before_id: cursor });
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
  const mountedRef = useRef(true);
  const generatedNoticeRef = useRef({ report: false, macro: false, review: false });
  const [task, setTask] = useState<Task | null>(null);
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [selectedAgentChoice, setSelectedAgent] = useState<string | "all">("all");
  const [selectedLog, setSelectedLog] = useState<LogMessage | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [wsStatus, setWsStatus] = useState<WebSocket["readyState"] | null>(null);
  const [errorMsg, setErrorMsg] = useState("");
  const [loadingTask, setLoadingTask] = useState(true);
  const [viewMode, setViewMode] = useState<ProductViewMode>("report");
  const language: LanguageMode = "zh";
  const [activeMainTab, setActiveMainTab] = useState("");
  const [macroAnalysis, setMacroAnalysis] = useState<MacroAnalysisResponse | null>(null);
  const [automatedReview, setAutomatedReview] = useState<AutomatedReviewResponse | null>(null);
  const verification = task?.result && typeof task.result === "object" && "verification" in task.result
    ? task.result.verification as { status?: string } | null : null;
  const verificationLabel = ({ verified: "回放验证通过", failed: "验证未通过", skipped: "验证已跳过", not_run: "验证未执行" } as Record<string, string>)[verification?.status || "not_run"] || "验证未完成";

  const refreshTask = useCallback(async () => {
    if (!taskId) return null;
    try {
      const nextTask = await getTask(taskId);
      setTask(nextTask);
      setErrorMsg("");
      return nextTask;
    } catch {
      setErrorMsg("任务状态获取失败。");
      return null;
    } finally {
      setLoadingTask(false);
    }
  }, [taskId]);

  useEffect(() => {
    mountedRef.current = true;
    if (!taskId) return;

    let cancelled = false;
    TaskEventService.disconnect();
    TaskEventService.clearHistory();

    const handleConnect = () => {
      setErrorMsg("");
      setWsStatus(WebSocket.OPEN);
    };

    const handleError = (error: string) => {
      setErrorMsg(error);
      setWsStatus(WebSocket.CLOSED);
    };

    const handleStatus = (status: WebSocket["readyState"] | null) => {
      if (mountedRef.current) setWsStatus(status);
    };

    const handleEvent = (event: TaskEvent) => {
      if (!mountedRef.current) return;
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
      const nextTask = await refreshTask();
      if (cancelled || !mountedRef.current || !nextTask) return;

      if (isTerminalTask(nextTask.status)) {
        try {
          const persistedEvents = await fetchPersistedTaskEvents(taskId);
          if (!cancelled && mountedRef.current) {
            setEvents(persistedEvents);
            setWsStatus(null);
          }
        } catch {
          if (!cancelled && mountedRef.current) setErrorMsg("历史任务日志获取失败，请检查日志接口。");
        }
        return;
      }

      setEvents(TaskEventService.getHistory());
      TaskEventService.subscribe(handleEvent);
      TaskEventService.subscribeStatus(handleStatus);
      TaskEventService.connect(taskId, handleConnect, handleError);
      setWsStatus(TaskEventService.getConnectionState());
    };

    initializeTaskView();

    return () => {
      cancelled = true;
      mountedRef.current = false;
      TaskEventService.disconnect();
      TaskEventService.unsubscribe(handleEvent);
      TaskEventService.unsubscribeStatus(handleStatus);
    };
  }, [refreshTask, taskId]);

  const terminalTask = isTerminalTask(task?.status);
  const isTaskRunning = task?.status === TaskStatus.RUNNING || (!terminalTask && wsStatus === WebSocket.OPEN);
  const finalReportText = typeof task?.final_report === "string" ? task.final_report.trim() : "";
  const hasFinalReport = finalReportText.length > 0;
  const hasMacroAnalysis = Boolean(macroAnalysis);
  const hasAutomatedReview = Boolean(automatedReview);
  const hasReplay = hasFinalReport;
  const hasLearningGuide = hasFinalReport || hasMacroAnalysis;
  const hasConsistencyReview = hasFinalReport || hasAutomatedReview;

  useEffect(() => {
    generatedNoticeRef.current = { report: false, macro: false, review: false };
  }, [taskId]);



  useEffect(() => {
    let cancelled = false;
    if (!taskId) return;

    getMacroAnalysis(taskId)
      .then((payload) => {
        if (!cancelled) setMacroAnalysis(payload);
      })
      .catch(() => {
        if (!cancelled) setMacroAnalysis(null);
      });

    return () => {
      cancelled = true;
    };
  }, [taskId, task?.status, task?.completed_at]);

  useEffect(() => {
    let cancelled = false;
    if (!taskId) return;

    getAutomatedReview(taskId)
      .then((payload) => {
        if (!cancelled) setAutomatedReview(payload);
      })
      .catch(() => {
        if (!cancelled) setAutomatedReview(null);
      });

    return () => {
      cancelled = true;
    };
  }, [taskId, task?.status, task?.completed_at]);

  useEffect(() => {
    if (!taskId) return;

    const notices = generatedNoticeRef.current;
    if (hasFinalReport && !notices.report) {
      notices.report = true;
      message.success("结构化报告已生成，报告和攻击复盘入口已开放。");
    }
    if (hasMacroAnalysis && !notices.macro) {
      notices.macro = true;
      message.info("宏观分析已生成，可以查看交易角色和资金路径。");
    }
    if (hasAutomatedReview && !notices.review) {
      notices.review = true;
      message.info("一致性审查已生成，可以核对证据链。");
    }
  }, [hasAutomatedReview, hasFinalReport, hasMacroAnalysis, message, taskId]);

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
  const systemStatusHint = agentIssueCount > 0
    ? `${agentIssueCount} 个智能体有告警或错误`
    : activeAgentCount > 0
      ? "所有智能体正常运行"
      : "等待智能体输出日志";

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
          task={task}
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
      children: <AttackReplayTimeline task={task} events={events} mode={viewMode} />,
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
          taskId={taskId}
          events={events}
          selectedAgent={selectedAgent}
          onSelectLog={openLog}
          rawMode
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
    viewMode,
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
    <Layout className="app-shell">
      <Header className="topbar">
        <Space size={12} className="review-topbar-main">
          <Button icon={<ArrowLeft size={16} />} onClick={() => navigate("/tasks")} title="返回任务控制台" />
          <Button icon={<Home size={16} />} onClick={() => navigate("/")} title="返回首页" />
          
          <div className="review-title-block">
            <Typography.Title level={5} className="review-title">
              {task?.dapp_name ? `${task.dapp_name} 攻击复盘` : "攻击复盘工作台"}
            </Typography.Title>
            <Typography.Text type="secondary" className="text-mono">
              {taskId?.slice(0, 8)}...
            </Typography.Text>
          </div>
        </Space>
        <Space size={10}>
          <div className="view-mode-switcher">
            <Typography.Text className="view-mode-label">{language === "zh" ? "视图模式" : "View"}</Typography.Text>
            <Segmented
              value={viewMode}
              onChange={(value) => { setViewMode(value as ProductViewMode); setActiveMainTab(""); }}
              options={[
                { label: modeLabel(language, "report"), value: "report" },
                { label: modeLabel(language, "learn"), value: "learn" },
                { label: modeLabel(language, "auditor"), value: "auditor" },
                { label: modeLabel(language, "raw"), value: "raw" },
              ]}
            />
          </div>
          <Tag color={getStatusColor(task?.status)}>{task?.status ? taskStatusLabel(task.status) : t(language, "loading")}</Tag>
          {task && !task.is_demo && <Tag color={verification?.status === "verified" ? "success" : "default"}>{verificationLabel}</Tag>}
          {task?.archived ? <Tag>{t(language, "archived")}</Tag> : null}
          <Tag>{task?.dapp_name ?? t(language, "unknownDapp")}</Tag>
          <Tag>{formatDuration(task?.duration)}</Tag>
          <Tag icon={wsOpen ? <Wifi size={13} /> : <WifiOff size={13} />} color={connectionColor}>
            {connectionLabel}
          </Tag>
          <DappContextButton dappName={task?.dapp_name} autoOpenKey={task?.task_id} />
          <Button icon={<Bot size={15} />} onClick={() => setAssistantOpen(true)}>
            取证助手
          </Button>
          <Button icon={<RefreshCcw size={15} />} onClick={refreshTask}>
            {t(language, "refresh")}
          </Button>
        </Space>
      </Header>

      <Content className="dashboard-layout">
        {task && <Alert type={task.is_demo ? "info" : "warning"} showIcon title={task.is_demo
          ? "公共历史示例 · 报告与日志来自原项目归档，未在当前环境重新验证。"
          : "实时分析任务 · 仅本人可见。补丁验证状态以报告中的实际执行结果为准。"} />}

        {errorMsg ? <Alert type="error" showIcon message={errorMsg} closable onClose={() => setErrorMsg("")} /> : null}

        <div className="task-overview">
          <div>
            <Typography.Text type="secondary">{t(language, "dapp")}</Typography.Text>
            <Typography.Title level={4}>{task?.dapp_name ?? "加载中..."}</Typography.Title>
          </div>
          <div className="overview-metrics">
            <div>
              <span className="metric-value">{totalLogs}</span>
              <span className="metric-label">{t(language, "logs")}</span>
            </div>
            <div>
              <span className="metric-value">{agentStats.filter((item) => item.total > 0).length}</span>
              <span className="metric-label">{t(language, "agents")}</span>
            </div>
            <div>
              <span className="metric-value">{formatDuration(task?.duration)}</span>
              <span className="metric-label">{t(language, "duration")}</span>
            </div>
          </div>
        </div>

        {loadingTask && !task ? (
          <div className="center-loading">
            <Spin />
          </div>
        ) : (
          <div className="workbench-grid">
            <AgentNavigator
              stats={agentStats}
              selectedAgent={selectedAgent}
              onSelectAgent={setSelectedAgent}
              systemStatus={{
                label: systemStatusLabel,
                hint: systemStatusHint,
                tone: systemStatusTone,
              }}
            />

            <div className="analysis-center">
              <Tabs
                activeKey={displayedTab}
                onChange={setActiveMainTab}
                items={mainTabItems}
              />
            </div>

            <aside className="inspector-panel">
              <Tabs
                defaultActiveKey="agents"
                items={inspectorTabItems}
              />
            </aside>
          </div>
        )}
      </Content>

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
