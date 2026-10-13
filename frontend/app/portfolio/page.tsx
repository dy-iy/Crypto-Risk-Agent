import { redirect } from "next/navigation";
import { legacyPortfolioTarget } from "@/lib/market-symbols";

export default async function PortfolioPage({ searchParams }: { searchParams: Promise<{ asset?: string | string[]; symbol?: string | string[] }> }) {
  const query = await searchParams;
  const value = query.asset ?? query.symbol;
  redirect(legacyPortfolioTarget(typeof value === "string" ? value : null));
}
