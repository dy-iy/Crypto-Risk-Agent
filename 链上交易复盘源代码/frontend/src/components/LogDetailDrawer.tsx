import React, { useEffect, useState } from "react";
import { App as AntdApp, Button, Descriptions, Drawer, Space, Tag, Typography } from "antd";
import { Copy, ExternalLink } from "lucide-react";
import { getFullLog } from "../services/api";
import { FullLogResponse, LogMessage, MsgType } from "../types";
import MarkdownRenderer from "./MarkdownRenderer";
import { agentDisplayName, logLevelLabel, messageTypeLabel } from "../utils/presentation";

interface LogDetailDrawerProps {
  taskId: string;
  log: LogMessage | null;
  open: boolean;
  onClose: () => void;
}

const LogDetailDrawer: React.FC<LogDetailDrawerProps> = ({ taskId, log, open, onClose }) => {
  const { message } = AntdApp.useApp();
  const [fullLog, setFullLog] = useState<FullLogResponse | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setFullLog(null);

    if (!open || !log?.log_id) return;

    setLoading(true);
    getFullLog(taskId, log.log_id)
      .then((data) => {
        if (!cancelled) setFullLog(data);
      })
      .catch(() => {
        if (!cancelled) message.warning("完整日志暂不可用，当前显示实时接收的内容。");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [log?.log_id, message, open, taskId]);

  const content = fullLog?.content ?? log?.message ?? "";

  const handleCopy = async () => {
    await navigator.clipboard.writeText(content);
    message.success("已复制");
  };

  return (
    <Drawer
      title="日志详情"
      open={open}
      onClose={onClose}
      size="large"
      className="log-detail-drawer"
      extra={
        <Space>
          {fullLog?.source ? <Tag>{fullLog.source}</Tag> : null}
          <Button icon={<Copy size={14} />} onClick={handleCopy}>
            复制
          </Button>
        </Space>
      }
    >
      {!log ? null : (
        <Space orientation="vertical" size={16} style={{ width: "100%" }}>
          <Descriptions size="small" column={1} bordered>
            <Descriptions.Item label="智能体">{agentDisplayName(log.agent)}</Descriptions.Item>
            <Descriptions.Item label="级别">{logLevelLabel(log.level)}</Descriptions.Item>
            <Descriptions.Item label="类型">{messageTypeLabel(log.message_type)}</Descriptions.Item>
            <Descriptions.Item label="时间">{log.timestamp}</Descriptions.Item>
            <Descriptions.Item label="Log ID">
              {log.log_id ? (
                <Typography.Text copyable className="text-mono">
                  {log.log_id}
                </Typography.Text>
              ) : (
                "暂无"
              )}
            </Descriptions.Item>
          </Descriptions>

          {loading ? (
            <Typography.Text type="secondary">正在加载完整日志...</Typography.Text>
          ) : (
            <div className="log-detail-content">
              {log.message_type === MsgType.MARKDOWN || log.message_type === MsgType.RESULT ? (
                <MarkdownRenderer content={content} />
              ) : (
                <pre>{content}</pre>
              )}
            </div>
          )}

          {log.is_truncated ? (
            <div className="system-note">
              <ExternalLink size={14} />
              实时日志内容已截断，系统正在根据日志 ID 获取完整内容。
            </div>
          ) : null}
        </Space>
      )}
    </Drawer>
  );
};

export default LogDetailDrawer;
