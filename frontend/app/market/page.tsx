import type { Metadata } from "next";
import RiskDashboardLoader from "@/components/risk-dashboard-loader";

export const metadata: Metadata = { title: "行情看盘 | CryptoRisk", description: "多周期现货行情、技术指标、盘口深度与市场成交。" };

export default function MarketPage() { return <RiskDashboardLoader initialView="sim" />; }
