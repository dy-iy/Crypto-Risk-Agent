"use client";

import { FormEvent, ReactNode, useEffect, useRef, useState } from "react";
import { LoadingDots } from "@/components/ui/loading-states";
import { streamRiskAssistant } from "@/lib/api";

type ChatRole = "user" | "assistant";

type ChatMessage = {
  id: string;
  role: ChatRole;
  content: string;
};

type SelectionQuote = {
  selectedText: string;
  context: Record<string, unknown>;
};

const quickQuestions = [
  "解释这段话是什么意思",
  "这段内容反映了什么风险？",
  "这可能影响哪些币种？",
  "普通用户需要注意什么？",
];

const welcomeMessage: ChatMessage = {
  id: "global-assistant-welcome",
  role: "assistant",
  content: "可以选中页面内容后引用提问，也可以直接问我加密资产、金融市场和风控方法。",
};

export default function AskAIOnSelection() {
  const [selectedText, setSelectedText] = useState("");
  const [selectionContext, setSelectionContext] = useState<Record<string, unknown>>({});
  const [buttonPosition, setButtonPosition] = useState<{ x: number; y: number } | null>(null);
  const [quote, setQuote] = useState<SelectionQuote | null>(null);
  const [panelOpen, setPanelOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([welcomeMessage]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, loading, panelOpen]);

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

  function handleAskSelection() {
    const text = selectedText.trim();
    if (!text) return;
    setQuote({
      selectedText: text,
      context: selectionContext,
    });
    setPanelOpen(true);
    setButtonPosition(null);
    window.getSelection()?.removeAllRanges();
  }

  async function askAssistant(rawQuestion: string) {
    const trimmedQuestion = rawQuestion.trim();
    const effectiveQuestion = trimmedQuestion || (quote ? "请解释这段内容" : "");
    if (!effectiveQuestion || loading) return;

    const selected = quote?.selectedText;
    const context = buildAssistantContext(quote);
    const userMessage = selected
      ? `引用内容：${compactText(selected, 180)}\n\n${effectiveQuestion}`
      : effectiveQuestion;
    const replyId = `global-assistant-reply-${Date.now()}`;

    setMessages((items) => [
      ...items,
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
          setMessages((items) =>
            items.map((item) =>
              item.id === replyId ? { ...item, content: item.content + chunk } : item
            )
          );
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
      setMessages((items) => items.filter((item) => item.id !== replyId));
      setError("助手暂时无法回答，请稍后重试。");
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
        <button
          type="button"
          onMouseDown={(event) => event.preventDefault()}
          onClick={handleAskSelection}
          style={{
            position: "fixed",
            left: buttonPosition.x,
            top: buttonPosition.y,
            transform: "translateX(-50%)",
            zIndex: 9999,
          }}
          className="rounded-full bg-slate-950 px-4 py-2 text-sm font-bold text-white shadow-lg shadow-slate-900/20 transition-colors duration-200 hover:bg-slate-800"
        >
          询问 AI
        </button>
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
                <p className="text-xs text-slate-500">引用页面内容继续追问</p>
              </div>
              <span className="h-2 w-2 rounded-full bg-emerald-500" />
            </div>
            <button
              className="flex h-9 w-9 items-center justify-center rounded-lg text-slate-400 transition-colors duration-200 hover:bg-blue-50 hover:text-slate-900"
              type="button"
              onClick={() => setPanelOpen(false)}
              aria-label="关闭 AI 风控助手"
            >
              ×
            </button>
          </div>

          <div className="flex min-h-0 flex-1 flex-col gap-5 p-5">
            <div className="risk-scroll min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
              {messages.map((message) => (
                <div key={message.id} className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}>
                  <div
                    className={`max-w-[88%] whitespace-pre-wrap rounded-lg px-4 py-3 text-sm leading-7 ${
                      message.role === "user"
                        ? "bg-blue-600 font-semibold text-white"
                        : "border border-blue-100 bg-slate-50 text-slate-700"
                    }`}
                  >
                    {message.role === "assistant" ? (
                      message.content ? <MarkdownMessage content={message.content} /> : <LoadingDots label="正在整理回答" />
                    ) : (
                      message.content
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
                    <p className="text-xs font-bold text-blue-700">已引用选中内容</p>
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
                  <div className="mt-3 flex flex-wrap gap-2">
                    {quickQuestions.map((item) => (
                      <button
                        key={item}
                        type="button"
                        onClick={() => setQuestion(item)}
                        className="rounded-md border border-blue-100 bg-white px-2.5 py-1 text-xs font-bold text-blue-700 transition-colors duration-200 hover:bg-blue-600 hover:text-white"
                      >
                        {item}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              <div className="flex min-h-12 items-center gap-3 rounded-lg border border-blue-100 bg-slate-50 px-3 text-sm">
                <input
                  value={question}
                  onChange={(event) => setQuestion(event.target.value)}
                  className="min-w-0 flex-1 bg-transparent text-slate-700 outline-none placeholder:text-slate-400"
                  placeholder={quote ? "继续输入你的问题，也可直接发送..." : "问金融、币种、风险或当前页面..."}
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

function buildAssistantContext(quote: SelectionQuote | null): Record<string, unknown> {
  const baseContext = {
    active_view: "global_page_assistant",
    page_title: typeof document === "undefined" ? "" : document.title,
    page_path: typeof window === "undefined" ? "" : window.location.pathname,
    page_search: typeof window === "undefined" ? "" : window.location.search,
  };

  if (!quote) return baseContext;

  return {
    ...baseContext,
    quoted_selection_available: true,
    selected_text_preview: compactText(quote.selectedText, 500),
    selection_context: quote.context,
  };
}

function compactText(value: string, limit: number) {
  const compact = value.replace(/\s+/g, " ").trim();
  if (compact.length <= limit) return compact;
  return `${compact.slice(0, limit).trim()}...`;
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

function SendIcon() {
  return <IconSvg><path d="M22 2 11 13" /><path d="m22 2-7 20-4-9-9-4z" /></IconSvg>;
}
