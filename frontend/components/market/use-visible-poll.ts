"use client";
import { useEffect } from "react";

/** At most one request batch; hidden tabs stop polling and resume immediately. */
export function useVisiblePoll(task: (signal: AbortSignal) => Promise<void>, delay: number, revision = 0) {
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let busy = false;
    const run = async () => {
      if (controller.signal.aborted || document.hidden || busy) return;
      busy = true;
      try { await task(controller.signal); }
      finally {
        busy = false;
        if (!controller.signal.aborted && !document.hidden) timer = setTimeout(run, delay);
      }
    };
    const visibility = () => { clearTimeout(timer); if (!document.hidden) void run(); };
    document.addEventListener("visibilitychange", visibility);
    void run();
    return () => { controller.abort(); clearTimeout(timer); document.removeEventListener("visibilitychange", visibility); };
  }, [task, delay, revision]);
}
