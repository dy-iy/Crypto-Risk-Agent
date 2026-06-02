"use client";

import { FormEvent, ReactNode, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { LoadingDots } from "@/components/ui/loading-states";
import {
  fetchCurrentUser,
  NewsRankingItem,
  RiskReport,
  saveAnalysisReport,
  streamChatMessage,
  streamRiskAssistant,
} from "@/lib/api";

type ChatRole = "user" | "assistant";

type ChatMessage = {
  id: string;
  role: ChatRole;
  content: string;
  reportRecordId?: string;
  reportTitle?: string;
};

type SelectionQuote = {
  selectedText: string;
  context: Record<string, unknown>;
  mode: SelectionAskMode;
  sourceInput?: string;
  news?: Partial<NewsRankingItem>;
};

type SelectionAskMode = "general_qa" | "deep_analysis";

type AssistantMemory = {
  news?: Partial<NewsRankingItem>;
  quotedText?: string;
  eventAnalysis?: {
    recordId: string;
    title: string;
    createdAt: string;
    input: string;
    answer: string;
    report: RiskReport;
  };
};

type AssistantSession = {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messages: ChatMessage[];
  memory: AssistantMemory;
};

const welcomeMessage: ChatMessage = {
  id: "global-assistant-welcome",
  role: "assistant",
  content: "可以选中页面内容后引用提问，也可以直接问我加密资产、金融市场和风控方法。",
};

const assistantSessionsStoragePrefix = "cryptorisk.globalAssistant.sessions";
const assistantActiveSessionStoragePrefix = "cryptorisk.globalAssistant.activeSession";
const analysisRecordsStorageKey = "cryptorisk.analysisRecords";
const selectedRecordStorageKey = "cryptorisk.selectedRecordId";
const reportCreatedEventName = "cryptorisk:analysis-record-created";
const openAssistantEventName = "cryptorisk:open-risk-assistant";
const authUsernameStorageKey = "cryptorisk.auth.username";

export default function AskAIOnSelection() {
  const router = useRouter();
  const [storageScope, setStorageScope] = useState(() => readAssistantStorageScope());
  const [sessions, setSessions] = useState<AssistantSession[]>(() => readAssistantSessions(readAssistantStorageScope()));
  const [activeSessionId, setActiveSessionId] = useState(() => readActiveAssistantSessionId(readAssistantStorageScope()));
  const [selectedText, setSelectedText] = useState("");
  const [selectionContext, setSelectionContext] = useState<Record<string, unknown>>({});
  const [buttonPosition, setButtonPosition] = useState<{ x: number; y: number } | null>(null);
  const [quote, setQuote] = useState<SelectionQuote | null>(null);
  const [panelOpen, setPanelOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const endRef = useRef<HTMLDivElement | null>(null);
  const activeSession = sessions.find((item) => item.id === activeSessionId) || sessions[0] || createAssistantSession();
  const messages = activeSession.messages;

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, loading, panelOpen]);

  useEffect(() => {
    let ignore = false;

    async function loadScope() {
      try {
        const user = await fetchCurrentUser();
        const nextScope = user?.username?.trim().toLowerCase() || readAssistantStorageScope();
        if (ignore || nextScope === storageScope) return;
        setStorageScope(nextScope);
        const nextSessions = readAssistantSessions(nextScope);
        setSessions(nextSessions);
        setActiveSessionId(readActiveAssistantSessionId(nextScope) || nextSessions[0]?.id || "");
      } catch {
        // Keep the local guest/user scope if auth state cannot be loaded.
      }
    }

    void loadScope();
    return () => {
      ignore = true;
    };
  }, [storageScope]);

  useEffect(() => {
    if (!sessions.length) {
      const session = createAssistantSession();
      setSessions([session]);
      setActiveSessionId(session.id);
      return;
    }
    if (!activeSessionId || !sessions.some((item) => item.id === activeSessionId)) {
      setActiveSessionId(sessions[0].id);
    }
  }, [activeSessionId, sessions]);

  useEffect(() => {
    writeAssistantSessions(storageScope, sessions);
  }, [sessions, storageScope]);

  useEffect(() => {
    writeActiveAssistantSessionId(storageScope, activeSessionId);
  }, [activeSessionId, storageScope]);

  useEffect(() => {
    const handleSelection = () => {
      window.setTimeout(() => {
        const selection = window.getSelection();
        const text = selection?.toString().trim() || "";
        const anchorElement = getSelectionElement(selection);

        if (anchorElement?.closest("[data-ai-selection-ignore]")) {
          setButtonPosition(null);
          return;
        }

        if (!selection || !text || text.length < 2 || selection.rangeCount === 0) {
          setSelectedText("");
          setButtonPosition(null);
          return;
        }

        const range = selection.getRangeAt(0);
        const rect = range.getBoundingClientRect();
        if (!rect || rect.width === 0 || rect.height === 0) return;

        setSelectedText(text);
        setSelectionContext(readSelectionContext(anchorElement));
        setButtonPosition({
          x: rect.left + rect.width / 2,
          y: Math.max(12, rect.top - 44),
        });
      }, 0);
    };

    const clearFloatingButton = () => setButtonPosition(null);

    document.addEventListener("mouseup", handleSelection);
    document.addEventListener("touchend", handleSelection);
    window.addEventListener("scroll", clearFloatingButton, true);
    return () => {
      document.removeEventListener("mouseup", handleSelection);
      document.removeEventListener("touchend", handleSelection);
      window.removeEventListener("scroll", clearFloatingButton, true);
    };
  }, []);

  useEffect(() => {
    const handleOpenAssistant = (event: Event) => {
      const detail = (event as CustomEvent<{
        selectedText?: string;
        context?: Record<string, unknown>;
        sourceInput?: string;
        news?: Partial<NewsRankingItem>;
        mode?: SelectionAskMode;
      }>).detail || {};
      const text = String(detail.selectedText || detail.news?.content || detail.news?.summary || detail.news?.title || "").trim();
      if (!text) return;
      setQuote({
        selectedText: text,
        context: detail.context || buildNewsContext(detail.news),
        mode: detail.mode || "deep_analysis",
        sourceInput: detail.sourceInput,
        news: detail.news,
      });
      setQuestion("");
      setPanelOpen(true);
    };

    window.addEventListener(openAssistantEventName, handleOpenAssistant);
    return () => window.removeEventListener(openAssistantEventName, handleOpenAssistant);
  }, []);

  function updateActiveSession(updater: (session: AssistantSession) => AssistantSession) {
    setSessions((items) => {
      const existing = items.length ? items : [createAssistantSession()];
      const targetId = activeSessionId || existing[0].id;
      return existing.map((session) => session.id === targetId ? updater(session) : session);
    });
  }

  function appendMessages(nextMessages: ChatMessage[]) {
    updateActiveSession((session) => ({
      ...session,
      title: deriveSessionTitle(session, nextMessages),
      updatedAt: new Date().toISOString(),
      messages: [...session.messages, ...nextMessages],
    }));
  }

  function updateMessage(messageId: string, updater: (message: ChatMessage) => ChatMessage) {
    updateActiveSession((session) => ({
      ...session,
      updatedAt: new Date().toISOString(),
      messages: session.messages.map((message) => message.id === messageId ? updater(message) : message),
    }));
  }

  function removeMessage(messageId: string) {
    updateActiveSession((session) => ({
      ...session,
      updatedAt: new Date().toISOString(),
      messages: session.messages.filter((message) => message.id !== messageId),
    }));
  }

  function updateMemory(updater: (memory: AssistantMemory) => AssistantMemory) {
    updateActiveSession((session) => ({
      ...session,
      updatedAt: new Date().toISOString(),
      memory: updater(session.memory),
    }));
  }

  function handleNewSession() {
    const session = createAssistantSession();
    setSessions((items) => [session, ...items]);
    setActiveSessionId(session.id);
    setQuote(null);
    setQuestion("");
    setError("");
  }

  function handleDeleteSession() {
    setSessions((items) => {
      if (items.length <= 1) {
        const session = createAssistantSession();
        setActiveSessionId(session.id);
        return [session];
      }
      const next = items.filter((item) => item.id !== activeSession.id);
      setActiveSessionId(next[0]?.id || "");
      return next;
    });
    setQuote(null);
    setQuestion("");
  }

  function handleSelectionAction(mode: SelectionAskMode) {
    const text = selectedText.trim();
    if (!text) return;

    setQuote({
      selectedText: text,
      context: selectionContext,
      mode,
      sourceInput: buildEventAnalysisInput(text, selectionContext, ""),
      news: getNewsFromContext(selectionContext),
    });
    setPanelOpen(true);
    setButtonPosition(null);
    window.getSelection()?.removeAllRanges();
  }

  async function askAssistant(rawQuestion: string) {
    const trimmedQuestion = rawQuestion.trim();
    if (quote?.mode === "deep_analysis") {
      await runQuotedEventAnalysis(trimmedQuestion);
      return;
    }

    const effectiveQuestion = trimmedQuestion || (quote ? "请解释这段内容" : "");
    if (!effectiveQuestion || loading) return;

    const selected = quote?.selectedText;
    const context = buildAssistantContext(quote, activeSession);
    const userMessage = selected
      ? `引用内容：${compactText(selected, 180)}\n\n${effectiveQuestion}`
      : effectiveQuestion;
    const replyId = `global-assistant-reply-${Date.now()}`;

    appendMessages([
      { id: `global-assistant-user-${Date.now()}`, role: "user", content: userMessage },
      { id: replyId, role: "assistant", content: "" },
    ]);
    setQuestion("");
    setQuote(null);
    setError("");
    setLoading(true);

    try {
      await streamRiskAssistant(
        effectiveQuestion,
        context,
        (chunk) => {
          updateMessage(replyId, (message) => ({ ...message, content: message.content + chunk }));
        },
        selected
          ? {
              selectedText: selected,
              userQuestion: effectiveQuestion,
            }
          : undefined
      );
    } catch (assistantError) {
      console.error(assistantError);
      removeMessage(replyId);
      setError("助手暂时无法回答，请稍后重试。");
    } finally {
      setLoading(false);
    }
  }

  async function runQuotedEventAnalysis(supplement: string) {
    if (!quote || loading) return;
    const analysisInput = buildEventAnalysisInput(
      quote.sourceInput || quote.selectedText,
      quote.context,
      supplement,
      quote.news,
    );
    if (!analysisInput.trim()) return;

    const displayQuestion = supplement || "请基于引用新闻进行事件风险分析";
    const replyId = `event-analysis-reply-${Date.now()}`;
    appendMessages([
      {
        id: `event-analysis-user-${Date.now()}`,
        role: "user",
        content: `事件分析引用：${compactText(quote.selectedText, 220)}\n\n补充要求：${displayQuestion}`,
      },
      { id: replyId, role: "assistant", content: "" },
    ]);
    setQuestion("");
    setQuote(null);
    setError("");
    setLoading(true);

    try {
      const response = await streamChatMessage(analysisInput, () => undefined);
      const record = createAnalysisRecord(getReportOriginalInput(quote, analysisInput), response.data);
      storeAnalysisRecord(record);
      const answer = buildBriefAnalysis(record);
      const assistantContext = buildReportAssistantContext(quote, activeSession, analysisInput, answer, record);
      updateMessage(replyId, (message) => ({
        ...message,
        content: supplement
          ? `${answer}\n\n**风控助手追问回答**\n`
          : `${answer}\n\n完整事件分析链路已完成，报告已生成并保存。`,
        reportRecordId: record.id,
        reportTitle: record.title,
      }));
      updateMemory((memory) => ({
        ...memory,
        news: quote.news || getNewsFromContext(quote.context) || memory.news,
        quotedText: quote.selectedText,
        eventAnalysis: {
          recordId: record.id,
          title: record.title,
          createdAt: record.createdAt,
          input: analysisInput,
          answer,
          report: response.data,
        },
      }));
      if (supplement) {
        try {
          await waitForNextPaint();
          await streamRiskAssistant(
            supplement,
            assistantContext,
            (chunk) => {
              updateMessage(replyId, (message) => ({ ...message, content: message.content + chunk }));
            },
            {
              selectedText: quote.selectedText,
              userQuestion: supplement,
            }
          );
        } catch (assistantError) {
          console.error(assistantError);
          updateMessage(replyId, (message) => ({
            ...message,
            content: `${answer}\n\n完整事件分析链路已完成，报告已生成并保存。助手追问回答暂时失败，请稍后再试。`,
          }));
        }
      }
    } catch (analysisError) {
      console.error(analysisError);
      removeMessage(replyId);
      setError("事件分析暂时失败，请稍后重试。");
    } finally {
      setLoading(false);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void askAssistant(question);
  }

  return (
    <div data-ai-selection-ignore>
      {buttonPosition && selectedText && (
        <div
          onMouseDown={(event) => event.preventDefault()}
          style={{
            position: "fixed",
            left: buttonPosition.x,
            top: buttonPosition.y,
            transform: "translateX(-50%)",
            zIndex: 9999,
          }}
          className="flex overflow-hidden rounded-full border border-slate-800 bg-slate-950 shadow-lg shadow-slate-900/20"
        >
          <button
            type="button"
            onClick={() => handleSelectionAction("general_qa")}
            className="flex h-10 items-center gap-2 px-4 text-sm font-bold text-white transition-colors duration-200 hover:bg-slate-800"
          >
            <BotIcon />
            问小助手
          </button>
          <button
            type="button"
            onClick={() => handleSelectionAction("deep_analysis")}
            className="flex h-10 items-center gap-2 border-l border-white/10 bg-emerald-600 px-4 text-sm font-bold text-white transition-colors duration-200 hover:bg-emerald-700"
          >
            <RadarIcon />
            深入分析
          </button>
        </div>
      )}

      <button
        type="button"
        onClick={() => setPanelOpen(true)}
        className={`fixed bottom-6 right-6 z-40 flex h-14 w-14 items-center justify-center rounded-full bg-blue-600 text-white shadow-2xl shadow-blue-200 transition-all duration-200 hover:-translate-y-0.5 hover:bg-blue-700 ${
          panelOpen ? "pointer-events-none scale-95 opacity-0" : "opacity-100"
        }`}
        aria-label="打开 AI 风控助手"
        aria-expanded={panelOpen}
      >
        <BotIcon />
      </button>

      {panelOpen && (
        <button
          type="button"
          className="fixed inset-0 z-40 bg-slate-950/20 backdrop-blur-[1px] xl:hidden"
          onClick={() => setPanelOpen(false)}
          aria-label="关闭 AI 风控助手遮罩"
        />
      )}

      <aside
        className={`fixed inset-y-0 right-0 z-50 w-full max-w-[420px] transform border-l border-blue-100 bg-white shadow-2xl shadow-slate-900/20 transition-transform duration-300 sm:right-4 sm:top-[108px] sm:bottom-6 sm:h-[calc(100vh-132px)] sm:rounded-lg sm:border ${
          panelOpen ? "translate-x-0" : "translate-x-full sm:translate-x-[calc(100%+2rem)]"
        }`}
        aria-hidden={!panelOpen}
      >
        <section className="flex h-full flex-col">
          <div className="flex items-center justify-between border-b border-blue-100 px-5 py-4">
            <div className="flex items-center gap-3">
              <div className="flex h-11 w-11 items-center justify-center rounded-full bg-blue-50 text-blue-600">
                <BotIcon />
              </div>
              <div>
                <p className="font-bold text-slate-950">AI风控助手</p>
                <p className="text-xs text-slate-500">基于事件报告回答追问</p>
              </div>
              <span className="h-2 w-2 rounded-full bg-emerald-500" />
            </div>
            <div className="flex items-center gap-1">
              <button
                className="flex h-9 w-9 items-center justify-center rounded-lg text-slate-400 transition-colors duration-200 hover:bg-blue-50 hover:text-blue-600"
                type="button"
                onClick={handleNewSession}
                aria-label="新聊天"
                title="新聊天"
              >
                <PlusIcon />
              </button>
              <button
                className="flex h-9 w-9 items-center justify-center rounded-lg text-slate-400 transition-colors duration-200 hover:bg-rose-50 hover:text-rose-600"
                type="button"
                onClick={handleDeleteSession}
                aria-label="删除当前聊天"
                title="删除当前聊天"
              >
                <TrashIcon />
              </button>
              <button
                className="flex h-9 w-9 items-center justify-center rounded-lg text-slate-400 transition-colors duration-200 hover:bg-blue-50 hover:text-slate-900"
                type="button"
                onClick={() => setPanelOpen(false)}
                aria-label="关闭 AI 风控助手"
              >
                ×
              </button>
            </div>
          </div>

          <div className="border-b border-blue-100 bg-slate-50 px-4 py-2.5">
            <div className="flex items-center">
              <select
                value={activeSession.id}
                onChange={(event) => {
                  setActiveSessionId(event.target.value);
                  setQuote(null);
                  setQuestion("");
                  setError("");
                }}
                className="min-w-0 flex-1 rounded-lg border border-blue-100 bg-white px-3 py-2 text-xs font-semibold text-slate-700 outline-none"
                aria-label="选择聊天历史"
              >
                {sessions.map((session) => (
                  <option key={session.id} value={session.id}>
                    {session.title}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="flex min-h-0 flex-1 flex-col gap-5 p-5">
            <div className="risk-scroll min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
              {messages.map((message) => (
                <div key={message.id} className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}>
                  <div
                    className={`max-w-[88%] rounded-lg px-4 py-3 text-sm leading-7 ${
                      message.role === "user"
                        ? "bg-blue-600 font-semibold text-white"
                        : "border border-blue-100 bg-slate-50 text-slate-700"
                    }`}
                  >
                    {message.role === "assistant" ? (
                      message.content ? (
                        <>
                          <MarkdownMessage content={message.content} />
                          {message.reportRecordId && (
                            <button
                              type="button"
                              onClick={() => {
                                window.localStorage.setItem(selectedRecordStorageKey, message.reportRecordId || "");
                                router.push(`/reports?record=${encodeURIComponent(message.reportRecordId || "")}`);
                              }}
                              className="mt-3 inline-flex h-9 items-center gap-2 rounded-lg bg-blue-600 px-3 text-xs font-bold text-white transition-colors duration-200 hover:bg-blue-700"
                            >
                              <FileIcon />
                              查看完整报告
                            </button>
                          )}
                        </>
                      ) : <LoadingDots label="正在整理回答" />
                    ) : (
                      <span className="whitespace-pre-wrap">{message.content}</span>
                    )}
                  </div>
                </div>
              ))}
              <div ref={endRef} />
            </div>

            {error && (
              <div className="rounded-lg border border-rose-100 bg-rose-50 px-3 py-2 text-sm font-semibold text-rose-700">
                {error}
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-3">
              {quote && (
                <div className="rounded-lg border border-blue-100 bg-blue-50 p-3">
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-xs font-bold text-blue-700">
                      {quote.mode === "deep_analysis" ? "已引用待分析新闻" : "已引用选中内容"}
                    </p>
                    <button
                      type="button"
                      onClick={() => setQuote(null)}
                      className="flex h-7 w-7 items-center justify-center rounded-md text-slate-400 transition-colors duration-200 hover:bg-white hover:text-slate-900"
                      aria-label="移除引用内容"
                    >
                      ×
                    </button>
                  </div>
                  <p className="mt-2 max-h-20 overflow-hidden text-sm leading-6 text-slate-700">
                    {compactText(quote.selectedText, 220)}
                  </p>
                </div>
              )}

              <div className="flex min-h-12 items-center gap-3 rounded-lg border border-blue-100 bg-slate-50 px-3 text-sm">
                <input
                  value={question}
                  onChange={(event) => setQuestion(event.target.value)}
                  className="min-w-0 flex-1 bg-transparent text-slate-700 outline-none placeholder:text-slate-400"
                  placeholder={quote?.mode === "deep_analysis" ? "输入问题，发送后先完成事件分析再回答..." : quote ? "继续输入你的问题，也可直接发送..." : "问金融、币种、风险或当前页面..."}
                />
                <button
                  type="submit"
                  disabled={loading || (!question.trim() && !quote)}
                  className="ml-auto flex h-8 w-8 items-center justify-center rounded-full bg-blue-600 text-white transition-colors duration-200 hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
                  aria-label="发送问题"
                >
                  <SendIcon />
                </button>
              </div>
            </form>
            <p className="text-xs text-slate-400">内容由 AI 生成，仅供参考</p>
          </div>
        </section>
      </aside>
    </div>
  );
}

function getSelectionElement(selection: Selection | null) {
  const node = selection?.anchorNode;
  if (!node) return null;
  return node.nodeType === Node.ELEMENT_NODE ? (node as Element) : node.parentElement;
}

function readSelectionContext(anchorElement: Element | null): Record<string, unknown> {
  const container = anchorElement?.closest("[data-ai-context]");
  const rawContext = container?.getAttribute("data-ai-context");
  let nearestContext: unknown = null;
  if (rawContext) {
    try {
      nearestContext = JSON.parse(rawContext);
    } catch {
      nearestContext = rawContext;
    }
  }

  return {
    page_title: document.title,
    page_path: window.location.pathname,
    page_search: window.location.search,
    nearest_context: nearestContext,
  };
}

function buildAssistantContext(quote: SelectionQuote | null, session: AssistantSession): Record<string, unknown> {
  const baseContext = {
    active_view: "global_page_assistant",
    page_title: typeof document === "undefined" ? "" : document.title,
    page_path: typeof window === "undefined" ? "" : window.location.pathname,
    page_search: typeof window === "undefined" ? "" : window.location.search,
    assistant_memory: {
      news: session.memory.news,
      quoted_text: session.memory.quotedText ? compactText(session.memory.quotedText, 800) : "",
      event_analysis: session.memory.eventAnalysis ? {
        record_id: session.memory.eventAnalysis.recordId,
        title: session.memory.eventAnalysis.title,
        input: compactText(session.memory.eventAnalysis.input, 1200),
        answer: session.memory.eventAnalysis.answer,
        report: session.memory.eventAnalysis.report,
      } : null,
      recent_messages: session.messages.slice(-8).map((message) => ({
        role: message.role,
        content: compactText(message.content, 500),
      })),
    },
  };

  if (!quote) return baseContext;

  return {
    ...baseContext,
    quoted_selection_available: true,
    selected_text_preview: compactText(quote.selectedText, 500),
    selection_context: quote.context,
  };
}

function buildReportAssistantContext(
  quote: SelectionQuote,
  session: AssistantSession,
  analysisInput: string,
  answer: string,
  record: AnalysisRecord,
): Record<string, unknown> {
  const news = quote.news || getNewsFromContext(quote.context) || session.memory.news;
  return {
    active_view: "global_page_assistant",
    page_title: typeof document === "undefined" ? "" : document.title,
    page_path: typeof window === "undefined" ? "" : window.location.pathname,
    page_search: typeof window === "undefined" ? "" : window.location.search,
    quoted_selection_available: true,
    selected_text_preview: compactText(quote.selectedText, 500),
    selection_context: quote.context,
    assistant_memory: {
      news,
      quoted_text: compactText(quote.selectedText, 800),
      event_analysis: {
        record_id: record.id,
        title: record.title,
        created_at: record.createdAt,
        input: compactText(analysisInput, 1200),
        answer,
        report: record.report,
      },
      recent_messages: session.messages.slice(-8).map((message) => ({
        role: message.role,
        content: compactText(message.content, 500),
      })),
    },
  };
}

function readAssistantStorageScope() {
  if (typeof window === "undefined") return "guest";
  return window.localStorage.getItem(authUsernameStorageKey)?.trim().toLowerCase() || "guest";
}

function assistantSessionsStorageKey(scope: string) {
  return `${assistantSessionsStoragePrefix}:${scope || "guest"}`;
}

function assistantActiveSessionStorageKey(scope: string) {
  return `${assistantActiveSessionStoragePrefix}:${scope || "guest"}`;
}

function createAssistantSession(): AssistantSession {
  const now = new Date().toISOString();
  return {
    id: `assistant-session-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    title: "新聊天",
    createdAt: now,
    updatedAt: now,
    messages: [welcomeMessage],
    memory: {},
  };
}

function readAssistantSessions(scope: string): AssistantSession[] {
  if (typeof window === "undefined") return [createAssistantSession()];
  try {
    const raw = window.localStorage.getItem(assistantSessionsStorageKey(scope));
    const parsed = raw ? (JSON.parse(raw) as AssistantSession[]) : [];
    return parsed.length ? parsed : [createAssistantSession()];
  } catch {
    return [createAssistantSession()];
  }
}

function writeAssistantSessions(scope: string, sessions: AssistantSession[]) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(assistantSessionsStorageKey(scope), JSON.stringify(sessions.slice(0, 20)));
}

function readActiveAssistantSessionId(scope: string) {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(assistantActiveSessionStorageKey(scope)) || "";
}

function writeActiveAssistantSessionId(scope: string, sessionId: string) {
  if (typeof window === "undefined" || !sessionId) return;
  window.localStorage.setItem(assistantActiveSessionStorageKey(scope), sessionId);
}

function deriveSessionTitle(session: AssistantSession, nextMessages: ChatMessage[]) {
  if (session.title !== "新聊天") return session.title;
  const firstUserMessage = nextMessages.find((message) => message.role === "user" && message.content.trim());
  return firstUserMessage ? compactText(firstUserMessage.content, 28) : session.title;
}

function getNewsFromContext(context: Record<string, unknown>): Partial<NewsRankingItem> | undefined {
  const nearest = context.nearest_context;
  if (!nearest || typeof nearest !== "object") return undefined;
  const data = nearest as Partial<NewsRankingItem> & { type?: string };
  if (data.type !== "news_detail") return undefined;
  return data;
}

function buildNewsContext(news?: Partial<NewsRankingItem>): Record<string, unknown> {
  return {
    page_title: typeof document === "undefined" ? "" : document.title,
    page_path: typeof window === "undefined" ? "" : window.location.pathname,
    page_search: typeof window === "undefined" ? "" : window.location.search,
    nearest_context: news ? { type: "news_detail", ...news } : null,
  };
}

function buildEventAnalysisInput(
  selectedText: string,
  context: Record<string, unknown>,
  supplement: string,
  explicitNews?: Partial<NewsRankingItem>,
) {
  const news = explicitNews || getNewsFromContext(context);
  const sections = [
    news?.title ? `新闻标题：${news.title}` : "",
    news?.published_at || news?.date ? `发布时间：${news.published_at || news.date}` : "",
    news?.risk_type ? `原始风险类别：${news.risk_type}` : "",
    typeof news?.risk_score === "number" ? `原始风险分：${news.risk_score}` : "",
    news?.coins?.length ? `关联币种：${news.coins.join(", ")}` : "",
    news?.content ? `新闻正文：${news.content}` : `引用内容：${selectedText}`,
    selectedText && selectedText !== news?.content ? `用户选中片段：${selectedText}` : "",
    news?.summary ? `已有摘要：${news.summary}` : "",
    news?.evidence ? `已有证据：${news.evidence}` : "",
    supplement ? `用户补充要求：${supplement}` : "",
  ];
  return sections.filter(Boolean).join("\n");
}

function getReportOriginalInput(quote: SelectionQuote, analysisInput: string) {
  const newsBody = quote.news?.content?.trim() || quote.news?.summary?.trim() || "";
  if (newsBody) return newsBody;
  return extractNewsBodyFromAnalysisInput(analysisInput) || quote.selectedText.trim() || analysisInput;
}

function extractNewsBodyFromAnalysisInput(input: string) {
  const lines = input.split(/\r?\n/);
  const newsLineIndex = lines.findIndex((line) => line.trim().startsWith("新闻正文："));
  if (newsLineIndex >= 0) {
    const firstLine = lines[newsLineIndex].replace(/^新闻正文：/, "").trim();
    const bodyLines = [firstLine];
    for (let index = newsLineIndex + 1; index < lines.length; index += 1) {
      const line = lines[index];
      if (/^(用户选中片段|已有摘要|已有证据|用户补充要求|新闻标题|发布时间|原始风险类别|原始风险分|关联币种|引用内容)：/.test(line.trim())) {
        break;
      }
      bodyLines.push(line);
    }
    return bodyLines.join("\n").trim();
  }
  return "";
}

type AnalysisRecord = {
  id: string;
  title: string;
  createdAt: string;
  input: string;
  report: RiskReport;
  disposition?: "pending" | "verified" | "ignored" | "monitoring" | "reviewed";
  dispositionNote?: string;
};

function createAnalysisRecord(input: string, report: RiskReport): AnalysisRecord {
  return {
    id: `report-${Date.now()}`,
    title: buildReportTitle(input, report),
    createdAt: formatTimestamp(new Date()),
    input,
    report,
    disposition: "pending",
    dispositionNote: "",
  };
}

function storeAnalysisRecord(record: AnalysisRecord) {
  if (typeof window === "undefined") return;
  let records: AnalysisRecord[] = [];
  try {
    const raw = window.localStorage.getItem(analysisRecordsStorageKey);
    records = raw ? (JSON.parse(raw) as AnalysisRecord[]) : [];
  } catch {
    records = [];
  }
  window.localStorage.setItem(analysisRecordsStorageKey, JSON.stringify([record, ...records]));
  window.localStorage.setItem(selectedRecordStorageKey, record.id);
  void saveAnalysisReport({
    id: record.id,
    title: record.title,
    created_at: record.createdAt,
    input: record.input,
    report: record.report,
    disposition: record.disposition || "pending",
    disposition_note: record.dispositionNote || "",
  }).catch(() => undefined);
  window.dispatchEvent(new CustomEvent(reportCreatedEventName, { detail: { recordId: record.id } }));
}

function buildReportTitle(input: string, report: RiskReport) {
  const category = report.primary_category || report.risk_categories?.[0] || "综合风险";
  const compact = compactText(input, 28);
  return `${category} · ${compact}`;
}

function buildBriefAnalysis(record: AnalysisRecord) {
  const report = record.report;
  const evidence = report.evidence?.[0]?.evidence_text || "暂无明确证据摘录。";
  const advice = report.advice?.[0] || "建议继续核验官方公告、链上数据和后续报道。";
  return [
    `**事件分析完成**`,
    `风险等级：${report.risk_level}，风险分：${report.risk_score}/100。`,
    `核心判断：${report.summary}`,
    `主要证据：${evidence}`,
    `处置建议：${advice}`,
  ].join("\n");
}

function formatTimestamp(date: Date) {
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function compactText(value: string, limit: number) {
  const compact = value.replace(/\s+/g, " ").trim();
  if (compact.length <= limit) return compact;
  return `${compact.slice(0, limit).trim()}...`;
}

function waitForNextPaint() {
  return new Promise<void>((resolve) => {
    if (typeof window === "undefined") {
      resolve();
      return;
    }
    window.setTimeout(resolve, 0);
  });
}

function MarkdownMessage({ content }: { content: string }) {
  const lines = content.split(/\r?\n/);
  const elements: ReactNode[] = [];
  let listItems: string[] = [];
  let paragraph: string[] = [];

  const flushParagraph = () => {
    if (!paragraph.length) return;
    const text = paragraph.join(" ");
    elements.push(
      <p key={`p-${elements.length}`} className="my-2 first:mt-0 last:mb-0">
        {renderInlineMarkdown(text)}
      </p>
    );
    paragraph = [];
  };

  const flushList = () => {
    if (!listItems.length) return;
    elements.push(
      <ul key={`ul-${elements.length}`} className="my-2 list-disc space-y-1 pl-5">
        {listItems.map((item, index) => (
          <li key={`${index}-${item}`}>{renderInlineMarkdown(item)}</li>
        ))}
      </ul>
    );
    listItems = [];
  };

  lines.forEach((rawLine) => {
    const line = rawLine.trim();

    if (!line) {
      flushParagraph();
      flushList();
      return;
    }

    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      flushParagraph();
      flushList();
      elements.push(
        <p key={`h-${elements.length}`} className="mt-2 text-sm font-bold">
          {renderInlineMarkdown(heading[2])}
        </p>
      );
      return;
    }

    const bullet = line.match(/^[-*]\s+(.+)$/);
    if (bullet) {
      flushParagraph();
      listItems.push(bullet[1]);
      return;
    }

    paragraph.push(line);
  });

  flushParagraph();
  flushList();

  return <>{elements}</>;
}

function renderInlineMarkdown(text: string) {
  const parts: ReactNode[] = [];
  let remaining = text;
  let index = 0;

  while (remaining.length) {
    const boldMatch = remaining.match(/\*\*([^*]+)\*\*/);
    if (!boldMatch || boldMatch.index === undefined) {
      parts.push(remaining);
      break;
    }

    if (boldMatch.index > 0) parts.push(remaining.slice(0, boldMatch.index));
    parts.push(
      <strong key={`bold-${index}`} className="font-bold text-slate-950">
        {boldMatch[1]}
      </strong>
    );
    remaining = remaining.slice(boldMatch.index + boldMatch[0].length);
    index += 1;
  }

  return parts;
}

function IconSvg({ children }: { children: ReactNode }) {
  return (
    <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {children}
    </svg>
  );
}

function BotIcon() {
  return <IconSvg><rect x="5" y="8" width="14" height="11" rx="4" /><path d="M12 4v4" /><path d="M9 13h.01" /><path d="M15 13h.01" /><path d="M10 17h4" /></IconSvg>;
}

function RadarIcon() {
  return <IconSvg><path d="M12 3a9 9 0 1 0 9 9" /><path d="M12 12 20 4" /><path d="M12 7v5h5" /><circle cx="12" cy="12" r="2" /></IconSvg>;
}

function SendIcon() {
  return <IconSvg><path d="M22 2 11 13" /><path d="m22 2-7 20-4-9-9-4z" /></IconSvg>;
}

function FileIcon() {
  return <IconSvg><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6" /><path d="M8 13h8" /><path d="M8 17h5" /></IconSvg>;
}

function PlusIcon() {
  return <IconSvg><path d="M12 5v14" /><path d="M5 12h14" /></IconSvg>;
}

function TrashIcon() {
  return <IconSvg><path d="M3 6h18" /><path d="M8 6V4h8v2" /><path d="M19 6l-1 14H6L5 6" /><path d="M10 11v5" /><path d="M14 11v5" /></IconSvg>;
}
