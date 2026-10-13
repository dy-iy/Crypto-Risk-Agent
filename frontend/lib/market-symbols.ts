// Mirrors the server's deliberately bounded public spot-market coverage.
export const marketSymbols: readonly string[] = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "TRXUSDT", "SUIUSDT", "AAVEUSDT", "DOTUSDT", "LTCUSDT", "UNIUSDT"];
export function normalizeMarketSymbol(value: string | null | undefined): string | null {
  const raw = (value || "").trim().toUpperCase();
  const symbol = raw.endsWith("USDT") ? raw : raw + "USDT";
  return marketSymbols.includes(symbol) ? symbol : null;
}
export function legacyPortfolioTarget(value: string | null | undefined) {
  const symbol = normalizeMarketSymbol(value);
  return symbol ? `/market?symbol=${symbol}` : "/my?tab=assets";
}
