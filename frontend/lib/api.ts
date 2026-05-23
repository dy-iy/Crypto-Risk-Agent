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

export type NewsRankingItem = {
  rank: number;
  news_id: string;
  title: string;
  content: string;
  risk_score: number;
  risk_level: string;
  risk_type: string;
  published_at: string;
  coins: string[];
  summary: string;
  evidence: string;
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

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });

  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export function sendChatMessage(message: string) {
  return requestJson<ChatResponse>("/api/chat", {
    method: "POST",
    body: JSON.stringify({ message }),
  });
}

export function fetchRiskOverview(date?: string) {
  const search = date ? `?date=${encodeURIComponent(date)}` : "";
  return requestJson<RiskOverview>(`/api/rankings/overview${search}`);
}

export function fetchNewsRanking(limit = 10, date?: string) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (date) params.set("date", date);
  return requestJson<NewsRankingResponse>(
    `/api/rankings/news?${params.toString()}`
  );
}

export function fetchCoinRanking(limit = 10, date?: string) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (date) params.set("date", date);
  return requestJson<CoinRankingResponse>(
    `/api/rankings/coins?${params.toString()}`
  );
}
