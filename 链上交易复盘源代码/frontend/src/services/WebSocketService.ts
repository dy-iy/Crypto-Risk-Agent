import { BACKEND_WS_URL } from "../config/appConfig";
import { LogLevel, MsgType, TaskEvent } from "../types";

type Listener = (event: TaskEvent) => void;
type StatusListener = (status: WebSocket["readyState"] | null) => void;

class WebSocketService {
  private static instance: WebSocketService;
  private ws: WebSocket | null = null;
  private url: string | null = null;
  private listeners: Listener[] = [];
  private statusListeners: StatusListener[] = [];
  private reconnectAttempts = 0;
  private readonly maxReconnectAttempts = 10;
  private reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
  private isReconnecting = false;
  private shouldReconnect = true;
  private terminalEventReceived = false;
  private eventHistory: TaskEvent[] = [];
  private readonly maxHistorySize = 5000;

  public static getInstance(): WebSocketService {
    if (!WebSocketService.instance) {
      WebSocketService.instance = new WebSocketService();
    }
    return WebSocketService.instance;
  }

  public connect(taskId: string, onConnect?: () => void, onError?: (error: string) => void): void {
    const targetUrl = `${BACKEND_WS_URL}/ws/${taskId}`;

    if (this.ws && this.url === targetUrl) {
      if (this.ws.readyState === WebSocket.OPEN) {
        onConnect?.();
      }
      if (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING) {
        return;
      }
    }

    if (this.ws && this.url !== targetUrl) {
      this.disconnect();
    }

    if (this.url !== targetUrl) {
      this.clearHistory();
    }

    this.url = targetUrl;
    this.shouldReconnect = true;
    this.terminalEventReceived = false;
    this.connectWebSocket(onConnect, onError);
  }

  private connectWebSocket(onConnect?: () => void, onError?: (error: string) => void): void {
    if (this.isReconnecting || (this.ws && this.ws.readyState === WebSocket.OPEN)) {
      return;
    }

    if (!this.url) {
      onError?.("WebSocket URL not initialized");
      return;
    }

    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      onError?.("Max reconnection attempts reached. Please refresh the page.");
      return;
    }

    this.isReconnecting = true;

    try {
      this.ws = new WebSocket(this.url);
      this.emitStatus();

      this.ws.onopen = () => {
        this.reconnectAttempts = 0;
        this.isReconnecting = false;
        this.emitStatus();
        onConnect?.();
      };

      this.ws.onmessage = (event) => {
        try {
          const parsed = JSON.parse(event.data);
          const normalized = this.normalizeEvent(parsed);
          if (!normalized) return;

          if (this.isTerminalEvent(normalized)) {
            this.terminalEventReceived = true;
            this.shouldReconnect = false;
          }

          if (normalized.type === "PING") {
            this.send({ type: "PONG", timestamp: new Date().toISOString() });
          }

          this.pushHistory(normalized);
          this.listeners.forEach((callback) => callback(normalized));
        } catch (error) {
          console.error("WebSocket parse error:", error);
        }
      };

      this.ws.onerror = () => {
        this.isReconnecting = false;
        this.emitStatus();
        onError?.("WebSocket connection error");
      };

      this.ws.onclose = () => {
        this.isReconnecting = false;
        this.ws = null;
        this.emitStatus();

        if (this.shouldReconnect && !this.terminalEventReceived && this.reconnectAttempts < this.maxReconnectAttempts) {
          this.reconnectAttempts += 1;
          const delay = Math.min(2000 * Math.pow(1.5, this.reconnectAttempts - 1), 30000);
          this.reconnectTimeout = setTimeout(() => {
            this.connectWebSocket(onConnect, onError);
          }, delay);
        }
      };
    } catch (error) {
      this.isReconnecting = false;
      this.emitStatus();
      onError?.(`Connection failed: ${String(error)}`);
    }
  }

  private isTerminalEvent(event: TaskEvent): boolean {
    if (event.type === "TASK_FINAL") return true;
    if (event.type !== "TASK_STATUS") return false;
    return event.status === "completed" || event.status === "failed";
  }

  private normalizeEvent(data: unknown): TaskEvent | null {
    if (typeof data !== "object" || data === null) return null;
    const payload = data as Record<string, unknown>;
    const type = payload.type ?? (payload.agent ? "LOG" : undefined);
    if (!type) return null;

    if (type === "LOG") {
      return {
        type: "LOG",
        task_id: typeof payload.task_id === "string" ? payload.task_id : undefined,
        agent: typeof payload.agent === "string" ? payload.agent : "Unknown",
        level: this.normalizeLevel(payload.level),
        message: typeof payload.message === "string" ? payload.message : "",
        message_type: this.normalizeMessageType(payload.message_type),
        is_truncated: Boolean(payload.is_truncated),
        timestamp: typeof payload.timestamp === "string" ? payload.timestamp : new Date().toISOString(),
        log_id: typeof payload.log_id === "string" ? payload.log_id : undefined,
      };
    }

    return payload as unknown as TaskEvent;
  }

  private normalizeLevel(level: unknown): LogLevel {
    const value = String(level || "").toLowerCase();
    if (value === LogLevel.ERROR) return LogLevel.ERROR;
    if (value === LogLevel.WARNING) return LogLevel.WARNING;
    if (value === LogLevel.DEBUG) return LogLevel.DEBUG;
    return LogLevel.INFO;
  }

  private normalizeMessageType(messageType: unknown): MsgType {
    const value = String(messageType || "").toLowerCase();
    if (value === MsgType.MARKDOWN) return MsgType.MARKDOWN;
    if (value === MsgType.TOOL_CALL || value === "tool_call") return MsgType.TOOL_CALL;
    if (value === MsgType.RESULT) return MsgType.RESULT;
    return MsgType.TEXT;
  }

  private pushHistory(event: TaskEvent): void {
    this.eventHistory.push(event);
    if (this.eventHistory.length > this.maxHistorySize) {
      this.eventHistory = this.eventHistory.slice(this.eventHistory.length - this.maxHistorySize);
    }
  }

  private send(payload: unknown): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(payload));
    }
  }

  private emitStatus(): void {
    const state = this.getConnectionState();
    this.statusListeners.forEach((callback) => callback(state));
  }

  public disconnect(): void {
    this.shouldReconnect = false;
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }

    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }

    this.url = null;
    this.isReconnecting = false;
    this.emitStatus();
  }

  public subscribe(callback: Listener): void {
    if (!this.listeners.includes(callback)) {
      this.listeners.push(callback);
    }
  }

  public unsubscribe(callback: Listener): void {
    this.listeners = this.listeners.filter((listener) => listener !== callback);
  }

  public subscribeStatus(callback: StatusListener): void {
    if (!this.statusListeners.includes(callback)) {
      this.statusListeners.push(callback);
    }
  }

  public unsubscribeStatus(callback: StatusListener): void {
    this.statusListeners = this.statusListeners.filter((listener) => listener !== callback);
  }

  public isConnected(): boolean {
    return this.ws !== null && this.ws.readyState === WebSocket.OPEN;
  }

  public getHistory(): TaskEvent[] {
    return [...this.eventHistory];
  }

  public clearHistory(): void {
    this.eventHistory = [];
  }

  public getConnectionState(): WebSocket["readyState"] | null {
    return this.ws ? this.ws.readyState : null;
  }
}

export default WebSocketService.getInstance();
