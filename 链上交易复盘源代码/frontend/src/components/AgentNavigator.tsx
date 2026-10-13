import React from "react";
import { Badge, Button, Space, Tooltip, Typography } from "antd";
import { Bot, CircleAlert, CircleCheck, Clock3, Filter } from "lucide-react";
import { LogLevel } from "../types";
import { agentDisplayName } from "../utils/presentation";

export interface AgentStats {
  name: string;
  total: number;
  errors: number;
  warnings: number;
  lastSeen?: string;
  lastLevel?: LogLevel;
}

interface AgentNavigatorProps {
  stats: AgentStats[];
  selectedAgent: string | "all";
  onSelectAgent: (agent: string | "all") => void;
  systemStatus?: {
    label: string;
    hint: string;
    tone: "healthy" | "warning" | "error";
  };
}

function getStatus(stats: AgentStats): "idle" | "running" | "warning" | "error" | "done" {
  if (stats.errors > 0 || stats.lastLevel === LogLevel.ERROR) return "error";
  if (stats.warnings > 0 || stats.lastLevel === LogLevel.WARNING) return "warning";
  if (!stats.lastSeen) return "idle";

  const age = Date.now() - new Date(stats.lastSeen).getTime();
  return age < 30000 ? "running" : "done";
}

function getBadge(status: ReturnType<typeof getStatus>) {
  if (status === "running") return "processing";
  if (status === "warning") return "warning";
  if (status === "error") return "error";
  if (status === "done") return "success";
  return "default";
}

const AgentNavigator: React.FC<AgentNavigatorProps> = ({ stats, selectedAgent, onSelectAgent, systemStatus }) => {
  const totalLogs = stats.reduce((sum, item) => sum + item.total, 0);
  const activeAgents = stats.filter((item) => item.total > 0).length;

  return (
    <aside className="agent-nav">
      <div className="panel-header">
        <Space size={8}>
          <Bot size={16} />
          <Typography.Text strong>智能体状态</Typography.Text>
        </Space>
        <Tooltip title="显示全部智能体">
          <Button
            size="small"
            type={selectedAgent === "all" ? "primary" : "default"}
            icon={<Filter size={14} />}
            onClick={() => onSelectAgent("all")}
          />
        </Tooltip>
      </div>

      <div className="agent-summary">
        <div>
          <span className="metric-value">{activeAgents}</span>
          <span className="metric-label">已参与</span>
        </div>
        <div>
          <span className="metric-value">{totalLogs}</span>
          <span className="metric-label">事件</span>
        </div>
      </div>

      <div className="agent-list">
        {stats.map((item) => {
          const status = getStatus(item);
          const selected = selectedAgent === item.name;
          return (
            <button
              key={item.name}
              className={selected ? "agent-row selected" : "agent-row"}
              onClick={() => onSelectAgent(item.name)}
              type="button"
            >
              <span className="agent-row-main">
                <Badge status={getBadge(status)} />
                <span className="agent-name">{agentDisplayName(item.name)}</span>
              </span>
              <span className="agent-row-meta">
                {item.errors > 0 ? <CircleAlert size={13} className="text-red" /> : null}
                {status === "done" ? <CircleCheck size={13} className="text-green" /> : null}
                {status === "idle" ? <Clock3 size={13} className="text-muted" /> : null}
                <span>{item.total}</span>
              </span>
            </button>
          );
        })}
      </div>

      {systemStatus ? (
        <div className={`agent-system-status agent-system-status-${systemStatus.tone}`}>
          <span className="agent-system-dot" />
          <div>
            <small>系统状态</small>
            <strong>{systemStatus.label}</strong>
            <em>{systemStatus.hint}</em>
          </div>
        </div>
      ) : null}
    </aside>
  );
};

export default AgentNavigator;
