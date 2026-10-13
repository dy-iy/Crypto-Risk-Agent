import type { Metadata } from "next";
import GlobalAssistantShell from "@/components/global-assistant-shell";
import "./globals.css";

export const metadata: Metadata = {
  title: "CryptoRisk Agent",
  description: "多智能体加密资产风控工作台，提供事件分析、证据报告、个人资产风险监测和链上攻击复盘。",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" className="h-full antialiased">
      <body className="min-h-full flex flex-col">
        {children}
        <GlobalAssistantShell />
      </body>
    </html>
  );
}
