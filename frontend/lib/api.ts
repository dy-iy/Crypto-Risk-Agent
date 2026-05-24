export type EvidenceItem = {
  risk_category: string;
  evidence_text: string;
  explanation: string;
};

export type ScoreBreakdown = {
  severity: number;
  evidence_strength: number;
  impact_scope: number;
  urgency: number;
  reversibility: number;
};

export type RiskReport = {
  summary: string;
  input_type: string;
  has_risk: boolean;
  risk_score: number;
  risk_level: string;
  confidence_score?: number;
  confidence_level?: string;
  score_dimension_note?: string;
  risk_categories: string[];
  risk_signals: string[];
  evidence: EvidenceItem[];
  score_breakdown: ScoreBreakdown;
  impact: string[];
  advice: string[];
};

export type ChatResponse = {
  status: string;
  message: string;
  data: RiskReport;
};

export type RiskAssistantResponse = {
  status: string;
  message: string;
  answer: string;
};

export type NewsRankingItem = {
  rank: number;
  news_id: string;
  csv_order?: number | string;
  title: string;
  content: string;
  date?: string;
  risk_score: number;
  risk_level: string;
  risk_type: string;
  published_at: string;
  coins: string[];
  coin_details?: Array<{
    symbol: string;
    name?: string;
    matched_terms?: string[];
  }>;
  summary: string;
  evidence: string;
  source_url?: string;
};

export type CoinRankingItem = {
  rank: number;
  symbol: string;
  name: string;
  final_score: number;
  risk_level: string;
  news_count: number;
  main_risk_type: string;
  top_news_title: string;
  summary: string;
  related_news: Array<{
    news_id: string;
    title: string;
    risk_score: number;
    risk_level: string;
    risk_type: string;
    published_at: string;
  }>;
};

export type RiskOverview = {
  date: string;
  total_news: number;
  high_risk_news: number;
  top_news: NewsRankingItem | null;
  top_coin: CoinRankingItem | null;
  top_news_preview: NewsRankingItem[];
  top_coin_preview: CoinRankingItem[];
};

export type NewsRankingResponse = {
  date: string;
  ranking_type: "news";
  items: NewsRankingItem[];
};

export type CoinRankingResponse = {
  date: string;
  ranking_type: "coin";
  items: CoinRankingItem[];
};

export type NewsUpdateResponse = {
  status: string;
  message: string;
  crawler: {
    existing_count: number;
    fetched_count: number;
    added_count: number;
    total_count: number;
    seeded_count: number;
    lookback_hours: number;
    start_time: string;
    end_time: string;
    raw_news_path: string;
    mastered_news_path?: string;
    crawler_error?: string;
    proxy_enabled?: boolean;
    proxy_source?: string;
    news_url_overridden?: boolean;
    page_url_overridden?: boolean;
  };
  agent: {
    unprocessed_before: number;
    processed_count: number;
    unprocessed_after: number;
  };
  ranking: {
    date: string;
    overview?: RiskOverview;
    news?: NewsRankingResponse;
    coins?: CoinRankingResponse;
    review_notes?: string[];
  };
};

export type NewsUpdateProgress = {
  label: string;
  status: "pending" | "running" | "success" | "warning" | "error";
  current: number;
  total: number;
  percent: number;
  message: string;
  fetched_count?: number;
};

export type NewsUpdateJob = {
  job_id: string;
  status: "queued" | "running" | "success" | "error";
  stage: string;
  message: string;
  crawler: NewsUpdateProgress;
  dedupe: NewsUpdateProgress;
  agent: NewsUpdateProgress;
  ranking: NewsUpdateProgress;
  result: NewsUpdateResponse | null;
  error: string;
  started_at: string;
  updated_at: string;
  finished_at: string;
};

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "";
const apiCachePrefix = "cryptorisk.api-cache:";
const apiCacheTtlMs = 5 * 60 * 1000;
const memoryCache = new Map<string, { expiresAt: number; data: unknown }>();
const pendingRequests = new Map<string, Promise<unknown>>();

function apiCacheKey(path: string) {
  return `${apiCachePrefix}${path}`;
}

function shouldPersistApiCache(path: string) {
  if (path.startsWith("/api/rankings/news?") && path.includes("limit=0")) return false;
  if (path.startsWith("/api/rankings/coins?") && path.includes("limit=0")) return false;
  return true;
}

function readCachedJson<T>(path: string): T | null {
  const now = Date.now();
  const memoryEntry = memoryCache.get(path);
  if (memoryEntry && memoryEntry.expiresAt > now) {
    return memoryEntry.data as T;
  }

  if (typeof window === "undefined" || !shouldPersistApiCache(path)) return null;

  try {
    const raw = window.sessionStorage.getItem(apiCacheKey(path));
    if (!raw) return null;
    const entry = JSON.parse(raw) as { expiresAt: number; data: T };
    if (!entry.expiresAt || entry.expiresAt <= now) {
      window.sessionStorage.removeItem(apiCacheKey(path));
      memoryCache.delete(path);
      return null;
    }
    memoryCache.set(path, entry);
    return entry.data;
  } catch {
    return null;
  }
}

function writeCachedJson<T>(path: string, data: T) {
  const entry = { expiresAt: Date.now() + apiCacheTtlMs, data };
  memoryCache.set(path, entry);

  if (typeof window === "undefined" || !shouldPersistApiCache(path)) return;
  try {
    window.sessionStorage.setItem(apiCacheKey(path), JSON.stringify(entry));
  } catch {
    // Ignore storage quota/private-mode failures; memory cache still works.
  }
}

export function clearApiCache() {
  memoryCache.clear();
  pendingRequests.clear();

  if (typeof window === "undefined") return;
  try {
    Object.keys(window.sessionStorage)
      .filter((key) => key.startsWith(apiCachePrefix))
      .forEach((key) => window.sessionStorage.removeItem(key));
  } catch {
    // Ignore storage failures; memory cache has already been cleared.
  }
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });

  if (!response.ok) {
    let detail = "";
    try {
      const payload = (await response.json()) as { detail?: string };
      detail = payload.detail ? `: ${payload.detail}` : "";
    } catch {
      detail = "";
    }
    throw new Error(`Request failed: ${response.status}${detail}`);
  }

  return response.json() as Promise<T>;
}

async function cachedRequestJson<T>(path: string): Promise<T> {
  const cached = readCachedJson<T>(path);
  if (cached) return cached;

  const pending = pendingRequests.get(path);
  if (pending) return pending as Promise<T>;

  const request = requestJson<T>(path)
    .then((data) => {
      writeCachedJson(path, data);
      return data;
    })
    .finally(() => {
      pendingRequests.delete(path);
    });
  pendingRequests.set(path, request);
  return request;
}

export function sendChatMessage(message: string) {
  return requestJson<ChatResponse>("/api/chat", {
    method: "POST",
    body: JSON.stringify({ message }),
  });
}

export async function updateTodayNews() {
  const response = await requestJson<NewsUpdateResponse>("/api/rankings/update-news", {
    method: "POST",
  });
  clearApiCache();
  return response;
}

export function startNewsUpdateJob() {
  clearApiCache();
  return requestJson<NewsUpdateJob>("/api/rankings/update-news/jobs", {
    method: "POST",
  });
}

export function fetchNewsUpdateJob(jobId: string) {
  return requestJson<NewsUpdateJob>(
    `/api/rankings/update-news/jobs/${encodeURIComponent(jobId)}`
  );
}

export function fetchCurrentNewsUpdateJob() {
  return requestJson<NewsUpdateJob>("/api/rankings/update-news/jobs/current");
}

export async function streamRiskAssistant(
  question: string,
  context: Record<string, unknown>,
  onChunk: (chunk: string) => void
) {
  const response = await fetch(`${API_BASE_URL}/api/risk-assistant/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ question, context }),
  });

  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }

  if (!response.body) {
    throw new Error("ReadableStream is not supported in this browser");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const flushEvents = () => {
    const events = buffer.split("\n\n");
    buffer = events.pop() || "";

    events.forEach((eventText) => {
      const dataLine = eventText
        .split("\n")
        .find((line) => line.startsWith("data:"));
      if (!dataLine) return;

      const payload = dataLine.slice(5).trim();
      if (!payload || payload === "{}") return;

      const parsed = JSON.parse(payload) as { content?: string };
      if (parsed.content) onChunk(parsed.content);
    });
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    flushEvents();
  }

  buffer += decoder.decode();
  flushEvents();
}

export function fetchRiskOverview(date?: string) {
  const search = date ? `?date=${encodeURIComponent(date)}` : "";
  return cachedRequestJson<RiskOverview>(`/api/rankings/overview${search}`);
}

export function readCachedRiskOverview(date?: string) {
  const search = date ? `?date=${encodeURIComponent(date)}` : "";
  return readCachedJson<RiskOverview>(`/api/rankings/overview${search}`);
}

export function fetchNewsRanking(limit = 10, date?: string) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (date) params.set("date", date);
  return cachedRequestJson<NewsRankingResponse>(
    `/api/rankings/news?${params.toString()}`
  );
}

export function readCachedNewsRanking(limit = 10, date?: string) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (date) params.set("date", date);
  return readCachedJson<NewsRankingResponse>(
    `/api/rankings/news?${params.toString()}`
  );
}

export function fetchNewsDetail(newsId: string, date?: string) {
  const search = date ? `?date=${encodeURIComponent(date)}` : "";
  return cachedRequestJson<NewsRankingItem>(
    `/api/rankings/news/${encodeURIComponent(newsId)}${search}`
  );
}

export function readCachedNewsDetail(newsId: string, date?: string) {
  const search = date ? `?date=${encodeURIComponent(date)}` : "";
  const detail = readCachedJson<NewsRankingItem>(
    `/api/rankings/news/${encodeURIComponent(newsId)}${search}`
  );
  if (detail) return detail;

  const rankingParams = new URLSearchParams({ limit: "0" });
  if (date) rankingParams.set("date", date);
  const ranking = readCachedJson<NewsRankingResponse>(
    `/api/rankings/news?${rankingParams.toString()}`
  );
  return ranking?.items.find((item) => String(item.news_id) === newsId) || null;
}

export function fetchCoinRanking(limit = 10, date?: string) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (date) params.set("date", date);
  return cachedRequestJson<CoinRankingResponse>(
    `/api/rankings/coins?${params.toString()}`
  );
}

export function readCachedCoinRanking(limit = 10, date?: string) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (date) params.set("date", date);
  return readCachedJson<CoinRankingResponse>(
    `/api/rankings/coins?${params.toString()}`
  );
}

export function fetchCoinDetail(symbol: string, date?: string) {
  const search = date ? `?date=${encodeURIComponent(date)}` : "";
  return cachedRequestJson<CoinRankingItem>(
    `/api/rankings/coins/${encodeURIComponent(symbol)}${search}`
  );
}

export function readCachedCoinDetail(symbol: string, date?: string) {
  const search = date ? `?date=${encodeURIComponent(date)}` : "";
  const normalizedSymbol = symbol.toUpperCase();
  const detail = readCachedJson<CoinRankingItem>(
    `/api/rankings/coins/${encodeURIComponent(symbol)}${search}`
  );
  if (detail) return detail;

  const rankingParams = new URLSearchParams({ limit: "0" });
  if (date) rankingParams.set("date", date);
  const ranking = readCachedJson<CoinRankingResponse>(
    `/api/rankings/coins?${rankingParams.toString()}`
  );
  return ranking?.items.find((item) => item.symbol.toUpperCase() === normalizedSymbol) || null;
}
