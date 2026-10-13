import React, { useCallback, useEffect, useMemo, useState } from "react";
import { App as AntdApp, Button, Empty, Space, Spin, Tag, Typography } from "antd";
import { Copy, FileText, RefreshCcw } from "lucide-react";
import { getAgentLogFile, listAgentLogFiles } from "../services/api";
import { AgentLogFileMeta, AgentLogFileResponse } from "../types";

interface AgentFileLogsProps {
  taskId: string;
}

function formatBytes(size: number) {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function getFileLabel(file: AgentLogFileMeta) {
  return file.name.replace(/\.log$/i, "");
}

const AgentFileLogs: React.FC<AgentFileLogsProps> = ({ taskId }) => {
  const { message } = AntdApp.useApp();
  const [files, setFiles] = useState<AgentLogFileMeta[]>([]);
  const [logDir, setLogDir] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [selectedLog, setSelectedLog] = useState<AgentLogFileResponse | null>(null);
  const [loadingList, setLoadingList] = useState(false);
  const [loadingFile, setLoadingFile] = useState(false);

  const selectedFile = useMemo(
    () => files.find((file) => file.id === selectedId) ?? null,
    [files, selectedId],
  );

  const loadFile = useCallback(
    async (fileId: string) => {
      if (!taskId || !fileId) return;
      try {
        setLoadingFile(true);
        setSelectedLog(await getAgentLogFile(taskId, fileId));
      } catch {
        message.error("智能体日志文件加载失败");
      } finally {
        setLoadingFile(false);
      }
    },
    [message, taskId],
  );

  const loadList = useCallback(async () => {
    if (!taskId) return;
    try {
      setLoadingList(true);
      const response = await listAgentLogFiles(taskId);
      setFiles(response.files);
      setLogDir(response.log_dir);
      const nextSelected = response.files.find((file) => file.size > 0)?.id ?? response.files[0]?.id ?? "";
      setSelectedId(nextSelected);
      setSelectedLog(null);
      if (nextSelected) await loadFile(nextSelected);
    } catch {
      message.error("日志文件列表加载失败");
    } finally {
      setLoadingList(false);
    }
  }, [loadFile, message, taskId]);

  useEffect(() => {
    loadList();
  }, [loadList]);

  const handleSelect = async (fileId: string) => {
    setSelectedId(fileId);
    await loadFile(fileId);
  };

  const handleCopy = async () => {
    if (!selectedLog?.content) return;
    await navigator.clipboard.writeText(selectedLog.content);
    message.success("日志已复制");
  };

  if (loadingList && files.length === 0) {
    return (
      <div className="center-loading">
        <Spin />
      </div>
    );
  }

  if (files.length === 0) {
    return (
      <div className="file-log-panel">
        <div className="file-log-header">
          <div>
            <Typography.Text strong>智能体日志文件</Typography.Text>
            <Typography.Text type="secondary">未找到持久化日志文件。</Typography.Text>
          </div>
          <Button size="small" icon={<RefreshCcw size={14} />} onClick={loadList} />
        </div>
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无日志文件" />
      </div>
    );
  }

  return (
    <div className="file-log-panel">
      <div className="file-log-header">
        <div>
          <Typography.Text strong>智能体日志文件</Typography.Text>
          <Typography.Text type="secondary" className="text-mono">
            {logDir ?? "日志目录不可用"}
          </Typography.Text>
        </div>
        <Button size="small" icon={<RefreshCcw size={14} />} loading={loadingList} onClick={loadList} />
      </div>

      <div className="file-log-list">
        {files.map((file) => (
          <button
            className={`file-log-row ${file.id === selectedId ? "selected" : ""}`}
            key={file.id}
            type="button"
            onClick={() => handleSelect(file.id)}
          >
            <span>
              <FileText size={14} />
              {getFileLabel(file)}
            </span>
            <small>{formatBytes(file.size)}</small>
          </button>
        ))}
      </div>

      <div className="file-log-main">
        <div className="file-log-meta">
          <Space size={6} wrap>
            <Tag>{selectedFile?.agent ?? "智能体"}</Tag>
            <Tag>{selectedFile ? formatBytes(selectedFile.size) : "暂无"}</Tag>
            {selectedLog?.truncated ? <Tag color="warning">内容已截断</Tag> : null}
          </Space>
          <Button size="small" icon={<Copy size={13} />} disabled={!selectedLog?.content} onClick={handleCopy}>
            复制
          </Button>
        </div>

        <div className="file-log-viewer">
          {loadingFile ? (
            <div className="center-loading">
              <Spin />
            </div>
          ) : selectedLog?.content ? (
            <pre>{selectedLog.content}</pre>
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="日志文件为空" />
          )}
        </div>
      </div>
    </div>
  );
};

export default AgentFileLogs;
