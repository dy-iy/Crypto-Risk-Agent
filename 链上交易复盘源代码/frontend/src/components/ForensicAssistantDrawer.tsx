import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Alert, Button, Empty, Input, Space, Tag, Typography } from "antd";
import { Bot, FileSearch, Lightbulb, MessageCircle, Minus, RotateCcw, Send, ShieldCheck } from "lucide-react";
import { chatWithAssistant } from "../services/api";
import { AssistantChatRequest, AssistantMessage, AssistantSource } from "../types";
import MarkdownRenderer from "./MarkdownRenderer";

const { TextArea } = Input;
const DEFAULT_PANEL_WIDTH = 520;
const MIN_PANEL_WIDTH = 380;
const MAX_PANEL_WIDTH = 820;

interface ForensicAssistantDrawerProps {
  open: boolean;
  onOpen?: () => void;
  onClose: () => void;
  scope: AssistantChatRequest["scope"];
  taskId?: string;
  txHash?: string;
  title?: string;
}

interface LocalMessage extends AssistantMessage {
  id: string;
  sources?: AssistantSource[];
  usedFallback?: boolean;
}

const promptSets: Record<AssistantChatRequest["scope"], string[]> = {
  tx_review: [
    "为什么这笔交易值得进一步审查？",
    "这些风险信号分别说明什么？",
    "下一步应该启动深度复盘吗？",
  ],
  task: [
    "这份报告最关键的漏洞证据是什么？",
    "用新手能懂的话解释这次攻击路径。",
    "补丁建议应该优先看哪一类问题？",
  ],
  knowledge: [
    "PoC 是什么，和真实攻击有什么关系？",
    "常见漏洞通常怎么打补丁？",
    "重入攻击一般怎么看 trace？",
  ],
  general: [
    "AttackPilot 是怎么做交易审查的？",
    "我应该先看报告、日志还是漏洞教程？",
    "如何判断模型结论有没有证据支撑？",
  ],
};

function sourceLabel(source: AssistantSource) {
  if (source.type === "tx_review") return "交易审查";
  if (source.type === "report") return "报告";
  if (source.type === "logs") return "日志";
  if (source.type === "macro_analysis") return "宏观分析";
  if (source.type === "knowledge") return "知识库";
  if (source.type === "task") return "任务";
  return source.type;
}

function clampWidth(value: number) {
  return Math.max(MIN_PANEL_WIDTH, Math.min(MAX_PANEL_WIDTH, value));
}

function makeStorageKey(scope: AssistantChatRequest["scope"], taskId?: string, txHash?: string) {
  const target = taskId || txHash || "general";
  return `attackpilot-assistant:${scope}:${target.toLowerCase()}`;
}

const ForensicAssistantDrawer: React.FC<ForensicAssistantDrawerProps> = ({
  open,
  onOpen,
  onClose,
  scope,
  taskId,
  txHash,
  title = "取证助手",
}) => {
  const [messages, setMessages] = useState<LocalMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [panelWidth, setPanelWidth] = useState(DEFAULT_PANEL_WIDTH);
  const [resizing, setResizing] = useState(false);
  const [historyReady, setHistoryReady] = useState(false);

  const prompts = useMemo(() => promptSets[scope] ?? promptSets.general, [scope]);
  const hasContext = Boolean(taskId || txHash || scope === "knowledge" || scope === "general");
  const storageKey = useMemo(() => makeStorageKey(scope, taskId, txHash), [scope, taskId, txHash]);

  useEffect(() => {
    setHistoryReady(false);
    try {
      const stored = window.localStorage.getItem(storageKey);
      setMessages(stored ? JSON.parse(stored) : []);
    } catch {
      setMessages([]);
    } finally {
      setHistoryReady(true);
    }
  }, [storageKey]);

  useEffect(() => {
    if (!historyReady) return;
    try {
      window.localStorage.setItem(storageKey, JSON.stringify(messages.slice(-40)));
    } catch {
      // Ignore localStorage failures in private mode or quota pressure.
    }
  }, [historyReady, messages, storageKey]);

  const startResize = useCallback((event: React.MouseEvent<HTMLDivElement>) => {
    event.preventDefault();
    setResizing(true);
    const startX = event.clientX;
    const startWidth = panelWidth;

    const handleMove = (moveEvent: MouseEvent) => {
      const delta = startX - moveEvent.clientX;
      setPanelWidth(clampWidth(startWidth + delta));
    };
    const handleUp = () => {
      setResizing(false);
      window.removeEventListener("mousemove", handleMove);
      window.removeEventListener("mouseup", handleUp);
    };

    window.addEventListener("mousemove", handleMove);
    window.addEventListener("mouseup", handleUp);
  }, [panelWidth]);

  const clearHistory = useCallback(() => {
    setMessages([]);
    setError("");
    try {
      window.localStorage.removeItem(storageKey);
    } catch {
      // Ignore localStorage failures.
    }
  }, [storageKey]);

  const sendQuestion = async (question: string) => {
    const value = question.trim();
    if (!value || loading) return;

    const userMessage: LocalMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      content: value,
    };
    setMessages((current) => [...current, userMessage]);
    setDraft("");
    setError("");
    setLoading(true);

    try {
      const history = messages
        .filter((item) => item.role === "user" || item.role === "assistant")
        .slice(-6)
        .map(({ role, content }) => ({ role, content }));
      const response = await chatWithAssistant({
        scope,
        task_id: taskId,
        tx_hash: txHash,
        chain: "ethereum",
        question: value,
        history,
      });

      setMessages((current) => [
        ...current,
        {
          id: `assistant-${Date.now()}`,
          role: "assistant",
          content: response.answer,
          sources: response.sources,
          usedFallback: response.used_fallback,
        },
      ]);
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      setError(detail || "取证助手暂时无法回答，请稍后重试。");
    } finally {
      setLoading(false);
    }
  };

  if (!open) {
    return (
      <button className="assistant-floating-launcher" type="button" onClick={onOpen} aria-label="打开取证助手">
        <span className="assistant-launcher-icon"><MessageCircle size={20} /></span>
        <span>
          <strong>取证助手</strong>
          <small>{hasContext ? "已绑定上下文" : "随时提问"}</small>
        </span>
      </button>
    );
  }

  return (
    <section className="forensic-assistant-floating" style={{ width: panelWidth }} aria-label={title}>
      <div
        className={`assistant-resize-handle${resizing ? " assistant-resize-handle-active" : ""}`}
        onMouseDown={startResize}
        title="拖拽调整助手宽度"
      />

      <header className="assistant-floating-header">
        <Space size={8} wrap>
          <span className="assistant-title-icon"><Bot size={17} /></span>
          <span className="assistant-floating-title">{title}</span>
          <Tag color={hasContext ? "blue" : "default"}>{hasContext ? "已绑定上下文" : "通用问答"}</Tag>
        </Space>
        <Space size={6}>
          <Button size="small" icon={<RotateCcw size={13} />} onClick={clearHistory}>
            清空
          </Button>
          <Button size="small" icon={<Minus size={13} />} onClick={onClose} aria-label="收起取证助手" />
        </Space>
      </header>

      <div className="assistant-shell">
        <Alert
          className="assistant-context-card"
          type="info"
          showIcon
          icon={<ShieldCheck size={16} />}
          message="助手会基于当前交易、任务报告、Agent 日志和漏洞知识库回答。"
          description="回答中的判断仍应回到链上证据复核。"
        />

        <div className="assistant-scroll-area">
          {messages.length === 0 ? (
            <div className="assistant-empty">
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="可以边看报告边问，不会遮住主工作区。" />
              <div className="assistant-prompt-grid">
                {prompts.map((prompt) => (
                  <button key={prompt} type="button" onClick={() => sendQuestion(prompt)}>
                    <Lightbulb size={14} />
                    <span>{prompt}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="assistant-message-list">
              {messages.map((message) => (
                <div className={`assistant-message assistant-message-${message.role}`} key={message.id}>
                  <div className="assistant-message-role">
                    {message.role === "assistant" ? <Bot size={14} /> : <FileSearch size={14} />}
                    <span>{message.role === "assistant" ? "取证助手" : "你"}</span>
                    {message.usedFallback ? <Tag color="gold">降级回答</Tag> : null}
                  </div>
                  {message.role === "assistant" ? (
                    <MarkdownRenderer content={message.content} compact />
                  ) : (
                    <Typography.Paragraph>{message.content}</Typography.Paragraph>
                  )}
                  {message.sources?.length ? (
                    <div className="assistant-source-list">
                      <span>依据</span>
                      {message.sources.map((source) => (
                        <Tag key={`${source.type}-${source.source}-${source.title}`}>{sourceLabel(source)} · {source.title}</Tag>
                      ))}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </div>

        {error ? <Alert type="error" showIcon message={error} /> : null}

        <div className="assistant-composer">
          <TextArea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onPressEnter={(event) => {
              if (!event.shiftKey) {
                event.preventDefault();
                sendQuestion(draft);
              }
            }}
            autoSize={{ minRows: 2, maxRows: 4 }}
            maxLength={2000}
            placeholder="问它：这笔交易为什么可疑？漏洞证据在哪里？"
          />
          <Button type="primary" icon={<Send size={15} />} loading={loading} onClick={() => sendQuestion(draft)}>
            发送
          </Button>
        </div>
      </div>
    </section>
  );
};

export default ForensicAssistantDrawer;
