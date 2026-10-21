import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "AttackPilot · 链上攻击复盘平台",
  description: "AttackPilot 多智能体链上攻击复盘平台，还原攻击链路、定位漏洞根因并生成验证报告。",
};

export default function AttackPilotLayout({ children }: { children: React.ReactNode }) {
  return children;
}
