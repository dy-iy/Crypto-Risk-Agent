"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";

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

    function handleSelection() {
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

        const rect = selection.getRangeAt(0).getBoundingClientRect();
        if (!rect || rect.width === 0 || rect.height === 0) return;

        setSelectedText(text);
        setSelectionContext(readSelectionContext(anchorElement));
        setButtonPosition({
          x: rect.left + rect.width / 2,
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
      {!enabled && buttonPosition && selectedText && (
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
      {!enabled && (
        <button
          type="button"
          onClick={openAssistant}
          className="fixed bottom-6 right-6 z-40 flex h-14 w-14 items-center justify-center rounded-full bg-blue-600 text-sm font-black text-white shadow-2xl shadow-blue-200 transition-all duration-200 hover:-translate-y-0.5 hover:bg-blue-700"
          aria-label="打开 AI 风控助手"
        >
          AI
        </button>
      )}
      {enabled && <AskAIOnSelection initialOpenRequest={initialOpenRequest} />}
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
