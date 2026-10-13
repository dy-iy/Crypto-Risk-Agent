const DEFAULT_BACKEND_HTTP_URL = "";
const LEGACY_API_HOST = import.meta.env.VITE_API_HOST;

function trimTrailingSlash(value: string) {
  return value.replace(/\/+$/, "");
}

function toWebSocketUrl(httpUrl: string) {
  if (!httpUrl || httpUrl.startsWith("/")) {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${protocol}//${window.location.host}`;
  }
  if (httpUrl.startsWith("https://")) return httpUrl.replace(/^https:\/\//, "wss://");
  if (httpUrl.startsWith("http://")) return httpUrl.replace(/^http:\/\//, "ws://");
  return `ws://${httpUrl}`;
}

function firstNonEmpty(...values: Array<string | undefined>) {
  return values.find((value) => value && value.trim().length > 0) ?? "";
}

export const BACKEND_HTTP_URL = trimTrailingSlash(
  firstNonEmpty(
    import.meta.env.VITE_BACKEND_HTTP_URL,
    import.meta.env.VITE_API_BASE_URL,
    DEFAULT_BACKEND_HTTP_URL,
  ),
);

export const BACKEND_WS_URL = trimTrailingSlash(
  firstNonEmpty(
    import.meta.env.VITE_BACKEND_WS_URL,
    import.meta.env.VITE_WS_BASE_URL,
    LEGACY_API_HOST ? toWebSocketUrl(LEGACY_API_HOST) : undefined,
    toWebSocketUrl(BACKEND_HTTP_URL),
  ),
);
