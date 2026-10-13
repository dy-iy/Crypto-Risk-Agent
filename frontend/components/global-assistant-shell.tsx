"use client";

import dynamic from "next/dynamic";
import { usePathname } from "next/navigation";
import { fetchCurrentUser } from "@/lib/api";
import { useEffect, useState, useSyncExternalStore } from "react";

import { getAccountScope, hasStorageWarning, subscribeAccountScope, storageWarningEvent } from "@/lib/browser-storage";

type OpenAssistantDetail = {
  context?: Record<string, unknown>;
  mode?: "general_qa" | "deep_analysis";
  news?: Record<string, unknown>;
  openOnly?: boolean;
  selectedText?: string;
  sourceInput?: string;
};

type OpenAssistantRequest = {
  detail: OpenAssistantDetail;
  id: number;
};

const openAssistantEventName = "cryptorisk:open-risk-assistant";

const AskAIOnSelection = dynamic(() => import("@/components/ask-ai-on-selection"), {
  loading: () => null,
  ssr: false,
});

export default function GlobalAssistantShell() {
  const pathname = usePathname();
  const hasForensicAssistant = pathname.startsWith("/attackpilot");
  const scope = useSyncExternalStore(subscribeAccountScope, getAccountScope, () => "guest");
  const [notice, setNotice] = useState(() => hasStorageWarning() ? "浏览器存储不可用，本次内容仅保留在当前标签页，请及时导出重要报告。" : "");
  useEffect(() => {
    const storageWarning = () => setNotice("浏览器存储不可用或已满，本次内容仅保留在当前标签页。请及时导出重要报告。");
    const syncWarning = () => setNotice("报告已保存在本机，云端同步失败。请检查网络后重新进入报告页重试。");
    const refreshIdentity = () => { void fetchCurrentUser().catch((error: unknown) => {
      if (!(error instanceof DOMException && error.name === "AbortError")) console.warn("登录状态暂时无法核验", error);
    }); };
    const handleStorage = (event: StorageEvent) => { if (event.key === "cryptorisk.auth.version") refreshIdentity(); };
    window.addEventListener("storage", handleStorage);
    window.addEventListener("focus", refreshIdentity);
    window.addEventListener(storageWarningEvent, storageWarning);
    window.addEventListener("cryptorisk:report-sync-error", syncWarning);
    return () => {
      window.removeEventListener("storage", handleStorage);
      window.removeEventListener("focus", refreshIdentity);
      window.removeEventListener(storageWarningEvent, storageWarning);
      window.removeEventListener("cryptorisk:report-sync-error", syncWarning);
    };
  }, []);
  const [enabled, setEnabled] = useState(false);
  const [initialOpenRequest, setInitialOpenRequest] = useState<OpenAssistantRequest | null>(null);
  const [buttonPosition, setButtonPosition] = useState<{ x: number; y: number } | null>(null);
  const [selectedText, setSelectedText] = useState("");
  const [selectionContext, setSelectionContext] = useState<Record<string, unknown>>({});

  useEffect(() => {
    function handleOpenAssistant(event: Event) {
      setInitialOpenRequest({
        detail: (event as CustomEvent<OpenAssistantDetail>).detail || { openOnly: true },
        id: Date.now(),
      });
      setEnabled(true);
    }

    window.addEventListener(openAssistantEventName, handleOpenAssistant);
    return () => window.removeEventListener(openAssistantEventName, handleOpenAssistant);
  }, []);

  useEffect(() => {
    if (enabled) return;

    let selectionTimer: number | undefined;
    function handleSelection() {
      window.clearTimeout(selectionTimer);
      selectionTimer = window.setTimeout(() => {
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

        const rect = selection.getRangeAt(0).getBoundingClientRect();
        if (!rect || rect.width === 0 || rect.height === 0) return;

        setSelectedText(text);
        setSelectionContext(readSelectionContext(anchorElement));
        setButtonPosition({
          x: Math.max(120, Math.min(window.innerWidth - 120, rect.left + rect.width / 2)),
          y: Math.max(12, rect.top - 44),
        });
      }, 0);
    }

    function clearFloatingButton() {
      setButtonPosition(null);
    }

    document.addEventListener("mouseup", handleSelection);
    document.addEventListener("touchend", handleSelection);
    window.addEventListener("scroll", clearFloatingButton, true);
    return () => {
      window.clearTimeout(selectionTimer);
      document.removeEventListener("mouseup", handleSelection);
      document.removeEventListener("touchend", handleSelection);
      window.removeEventListener("scroll", clearFloatingButton, true);
    };
  }, [enabled]);

  function openAssistant() {
    setInitialOpenRequest({
      detail: { openOnly: true },
      id: Date.now(),
    });
    setEnabled(true);
  }

  function openSelectionAssistant(mode: "general_qa" | "deep_analysis") {
    const text = selectedText.trim();
    if (!text) return;
    setInitialOpenRequest({
      detail: {
        context: selectionContext,
        mode,
        selectedText: text,
      },
      id: Date.now(),
    });
    setButtonPosition(null);
    setEnabled(true);
    window.getSelection()?.removeAllRanges();
  }

  return (
    <>
      {notice && <div role="status" className="fixed bottom-24 right-4 z-[70] max-w-[min(90vw,420px)] rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950 shadow-lg">
        {notice}<button type="button" className="ml-3 underline" onClick={() => setNotice("")}>关闭</button>
      </div>}
      {!hasForensicAssistant && !enabled && buttonPosition && selectedText && (
        <div
          data-ai-selection-ignore
          className="fixed z-50 flex overflow-hidden rounded-full bg-slate-950 shadow-2xl shadow-slate-900/20"
          style={{
            left: buttonPosition.x,
            top: buttonPosition.y,
            transform: "translateX(-50%)",
          }}
        >
          <button
            type="button"
            onClick={() => openSelectionAssistant("general_qa")}
            className="flex h-10 items-center px-4 text-sm font-bold text-white transition-colors duration-200 hover:bg-slate-800"
          >
            问小助手
          </button>
          <button
            type="button"
            onClick={() => openSelectionAssistant("deep_analysis")}
            className="flex h-10 items-center border-l border-white/10 bg-emerald-600 px-4 text-sm font-bold text-white transition-colors duration-200 hover:bg-emerald-700"
          >
            深入分析
          </button>
        </div>
      )}
      {!hasForensicAssistant && !enabled && (
        <button
          type="button"
          onClick={openAssistant}
          className="fixed bottom-6 right-6 z-40 flex h-14 w-14 items-center justify-center rounded-full bg-blue-600 text-sm font-black text-white shadow-2xl shadow-blue-200 transition-all duration-200 hover:-translate-y-0.5 hover:bg-blue-700"
          aria-label="打开 AI 风控助手"
        >
          AI
        </button>
      )}
      {!hasForensicAssistant && enabled && <AskAIOnSelection key={scope} initialOpenRequest={initialOpenRequest} />}
    </>
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
