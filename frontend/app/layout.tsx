import type { Metadata } from "next";
import AskAIOnSelection from "@/components/ask-ai-on-selection";
import "./globals.css";

export const metadata: Metadata = {
  title: "CryptoRisk Agent",
  description: "Multi-agent crypto financial risk control dashboard",
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
        <AskAIOnSelection />
      </body>
    </html>
  );
}
