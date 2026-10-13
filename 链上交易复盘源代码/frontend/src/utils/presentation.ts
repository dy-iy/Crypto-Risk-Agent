import { LogLevel, MsgType, TaskStatus } from "../types";

const TASK_STATUS_LABELS: Record<TaskStatus, string> = {
  [TaskStatus.PENDING]: "等待中",
  [TaskStatus.RUNNING]: "运行中",
  [TaskStatus.COMPLETED]: "已完成",
  [TaskStatus.FAILED]: "已失败",
};

const AGENT_LABELS: Record<string, string> = {
  TxDetailAgent: "交易详情智能体",
  TxRoleAgent: "交易角色智能体",
  "Transaction Filter": "交易筛选智能体",
  TxFaultAgent: "交易故障智能体",
  "Task Organizer": "任务规划智能体",
  "Transaction Debugger": "交易调试智能体",
  "GlobalMemory Administrator": "全局记忆智能体",
  "Code Patcher": "补丁生成智能体",
  "Transaction Judge": "交易验证智能体",
  "Final Report": "最终报告",
};

const LOG_LEVEL_LABELS: Record<LogLevel, string> = {
  [LogLevel.DEBUG]: "调试",
  [LogLevel.INFO]: "信息",
  [LogLevel.WARNING]: "警告",
  [LogLevel.ERROR]: "错误",
};

const MESSAGE_TYPE_LABELS: Record<MsgType, string> = {
  [MsgType.TEXT]: "文本",
  [MsgType.MARKDOWN]: "文档",
  [MsgType.TOOL_CALL]: "工具调用",
  [MsgType.RESULT]: "结果",
};

export function taskStatusLabel(status?: TaskStatus | null) {
  return status ? TASK_STATUS_LABELS[status] ?? status : "未知";
}

export function agentDisplayName(agent?: string | null) {
  if (!agent) return "智能体";
  return AGENT_LABELS[agent] ?? agent;
}

export function logLevelLabel(level: LogLevel) {
  return LOG_LEVEL_LABELS[level] ?? level;
}

export function messageTypeLabel(type: MsgType) {
  return MESSAGE_TYPE_LABELS[type] ?? type;
}

export function formatDurationZh(duration?: number | null) {
  if (duration == null) return "暂无";
  if (duration < 60) return `${duration.toFixed(1)} 秒`;
  const minutes = Math.floor(duration / 60);
  const seconds = Math.floor(duration % 60);
  return `${minutes} 分 ${seconds} 秒`;
}
