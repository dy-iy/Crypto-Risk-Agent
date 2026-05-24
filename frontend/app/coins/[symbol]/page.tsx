import CoinDetailPage from "@/components/coin-detail-page";

export default async function CoinDetailRoute({
  params,
  searchParams,
}: {
  params: Promise<{ symbol: string }>;
  searchParams: Promise<{ returnTo?: string }>;
}) {
  const { symbol } = await params;
  const { returnTo = "" } = await searchParams;
  return <CoinDetailPage returnTo={returnTo} symbol={symbol} />;
}
