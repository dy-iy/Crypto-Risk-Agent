/** Consume SSE incrementally, including CRLF, multiline data and a final unterminated event. */
export async function readEventStream(
  response: Response,
  onEvent: (name: string, data: unknown) => void,
  signal?: AbortSignal,
) {
  if (!response.body) throw new Error("当前浏览器无法读取流式响应，请升级浏览器后重试。");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let eventName = "message";
  let data: string[] = [];
  let eventChars = 0;
  let complete = false;
  function dispatch() {
    if (data.length) {
      const text = data.join("\n");
      if (text && text !== "[DONE]") {
        let parsed: unknown;
        try { parsed = JSON.parse(text); }
        catch { throw new Error("服务返回的数据格式异常，请重试。"); }
        onEvent(eventName, parsed);
      }
    }
    data = [];
    eventChars = 0;
    eventName = "message";
  }
  function line(text: string) {
    if (!text) { dispatch(); return; }
    if (text.startsWith(":")) return;
    const colon = text.indexOf(":");
    const field = colon < 0 ? text : text.slice(0, colon);
    const value = colon < 0 ? "" : text.slice(colon + 1).replace(/^ /, "");
    if (field === "event") eventName = value;
    if (field === "data") {
      eventChars += value.length + 1;
      if (eventChars > 4_000_000) throw new Error("流式响应过大，请缩小分析范围后重试。");
      data.push(value);
    }
  }
  const cancel = () => { void reader.cancel().catch((error: unknown) => console.warn("Stream cancellation failed", error)); };
  signal?.addEventListener("abort", cancel, { once: true });
  try {
    signal?.throwIfAborted();
    while (true) {
      const { done, value } = await reader.read();
      signal?.throwIfAborted();
      buffer += decoder.decode(value, { stream: !done });
      // A trailing CR may belong to a CRLF split across network chunks.
      let match: RegExpExecArray | null;
      while ((match = /\r\n|\r|\n/.exec(buffer))) {
        if (!done && match[0] === "\r" && match.index === buffer.length - 1) break;
        line(buffer.slice(0, match.index));
        buffer = buffer.slice(match.index + match[0].length);
      }
      if (buffer.length + eventChars > 4_000_000) {
        throw new Error("流式响应过大，请缩小分析范围后重试。");
      }
      if (done) { if (buffer) line(buffer); dispatch(); complete = true; break; }
    }
  } finally {
    signal?.removeEventListener("abort", cancel);
    try { if (!complete) await reader.cancel(); }
    finally { reader.releaseLock(); }
  }
}
