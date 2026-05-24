import NewsDetailPage from "@/components/news-detail-page";

export default async function NewsDetailRoute({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ returnTo?: string; fromCoin?: string }>;
}) {
  const { id } = await params;
  const { returnTo = "", fromCoin = "" } = await searchParams;
  return <NewsDetailPage fromCoin={fromCoin} newsId={id} returnTo={returnTo} />;
}
