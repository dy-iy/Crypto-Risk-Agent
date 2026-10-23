import React, { useEffect, useState } from "react";
import { App as AntdApp, Button, Drawer, Segmented, Spin, Tag, Typography } from "antd";
import { Copy } from "lucide-react";
import { getFullLog } from "../services/api";
import { FullLogResponse, LogMessage, MsgType } from "../types";
import MarkdownRenderer from "./MarkdownRenderer";
import { agentDisplayName, logLevelLabel, messageTypeLabel } from "../utils/presentation";
import "../log-detail.css";

interface LogDetailDrawerProps {
  taskId: string;
  log: LogMessage | null;
  open: boolean;
  onClose: () => void;
}

function previewContent(content: string) {
  const documentFence = content.match(/^\s*(`{3,}|~{3,})(?:markdown|md)[ \t]*\r?\n([\s\S]*?)\r?\n[ \t]*\1\s*$/i);
  return documentFence ? documentFence[2] : content;
}

const LogDetailDrawer: React.FC<LogDetailDrawerProps> = ({ taskId, log, open, onClose }) => {
  const { message } = AntdApp.useApp();
  const [resolvedLog, setResolvedLog] = useState<{ key: string; data?: FullLogResponse } | null>(null);
  const [view, setView] = useState<{ key: string; mode: "preview" | "source" } | null>(null);
  const selectedLogKey = JSON.stringify([taskId, log?.log_id ?? log?.timestamp, log?.agent]);
  const currentFullLog = resolvedLog?.key === selectedLogKey ? resolvedLog : null;
  const loading = Boolean(open && log?.log_id && !currentFullLog);
  const unavailable = Boolean(log?.log_id && currentFullLog && !currentFullLog.data);
  const mode = view?.key === selectedLogKey ? view.mode : "preview";

  useEffect(() => {
    let cancelled = false;

    if (!open || !log?.log_id) return;

    getFullLog(taskId, log.log_id)
      .then((data) => {
        if (!cancelled) setResolvedLog({ key: selectedLogKey, data });
      })
      .catch(() => {
        if (!cancelled) setResolvedLog({ key: selectedLogKey });
      });

    return () => {
      cancelled = true;
    };
  }, [log?.log_id, open, selectedLogKey, taskId]);

  const content = currentFullLog?.data ? currentFullLog.data.content : log?.message || "";
  const hasPreview = log?.message_type === MsgType.MARKDOWN || log?.message_type === MsgType.RESULT;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content);
      message.success("已复制");
    } catch {
      message.error("复制失败");
    }
  };

  return (
    <Drawer
      getContainer={() => document.querySelector<HTMLElement>(".attackpilot-root") || document.body}
      title="日志详情"
      open={open}
      onClose={onClose}
      size="min(1040px, 100vw)"
      className="log-detail-drawer"
      extra={
        <Button icon={<Copy size={14} />} onClick={handleCopy} disabled={!log || loading}>
          复制
        </Button>
      }
    >
      {!log ? null : (
        <div className="ap-log-detail-reader">
          <header className="ap-log-detail-meta">
            <div className="ap-log-detail-identity">
              <strong>{agentDisplayName(log.agent)}</strong>
              <span className="ap-log-detail-tags">
                <Tag>{logLevelLabel(log.level)}</Tag>
                <Tag>{messageTypeLabel(log.message_type)}</Tag>
              </span>
            </div>
            <time className="ap-log-detail-time">{log.timestamp}</time>
            <div className="ap-log-detail-id">
              <span>Log ID</span>
              {log.log_id ? (
                <Typography.Text copyable className="text-mono">{log.log_id}</Typography.Text>
              ) : <span>暂无</span>}
            </div>
          </header>

          {hasPreview ? (
            <div className="ap-log-detail-toolbar">
              <Segmented
                aria-label="日志展示方式"
                size="small"
                value={mode}
                options={[{ label: "预览", value: "preview" }, { label: "原文", value: "source" }]}
                onChange={(value) => setView({ key: selectedLogKey, mode: value as "preview" | "source" })}
              />
            </div>
          ) : null}

          {loading ? (
            <div className="ap-log-detail-status" role="status">
              <Spin size="small" />
              <span>正在加载完整日志...</span>
            </div>
          ) : unavailable ? (
            <div className="ap-log-detail-status" role="status">
              完整日志暂不可用，当前显示实时接收的内容。
            </div>
          ) : log.is_truncated && !currentFullLog?.data ? (
            <div className="ap-log-detail-status">实时日志内容已截断。</div>
          ) : null}

          <div className="ap-log-detail-content">
            {hasPreview && mode === "preview" ? (
              <MarkdownRenderer content={previewContent(content)} />
            ) : (
              <pre className="ap-log-detail-source">{content}</pre>
            )}
          </div>
        </div>
      )}
    </Drawer>
  );
};

export default LogDetailDrawer;
