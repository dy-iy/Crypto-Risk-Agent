import type { Metadata } from "next";
import GlobalAssistantShell from "@/components/global-assistant-shell";
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
        <GlobalAssistantShell />
      </body>
    </html>
  );
}
