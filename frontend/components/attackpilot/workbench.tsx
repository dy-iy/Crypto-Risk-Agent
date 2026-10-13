"use client";

import { useMemo, useSyncExternalStore } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import dynamic from "next/dynamic";
import { App as AntdApp, Button, ConfigProvider, Spin, theme } from "antd";
import zhCN from "antd/locale/zh_CN";
import { Moon, ShieldCheck, Sun } from "lucide-react";
import { localStore } from "@/lib/browser-storage";
import { AttackPilotIdentity } from "./context";
import "./attackpilot.css";

const loading = () => <div className="ap-page-loading" role="status"><Spin /><span>正在加载复盘页面…</span></div>;
const LandingWarRoom = dynamic(() => import("./pages/LandingWarRoom"), { loading });
const TaskList = dynamic(() => import("./pages/TaskList"), { loading });
const Dashboard = dynamic(() => import("./pages/Dashboard"), { loading });
const Knowledge = dynamic(() => import("./pages/LearningCenter"), { loading });
const Briefing = dynamic(() => import("./pages/Briefing"), { loading });
const appearanceKey = "riskpilot-appearance";
const appearanceEvent = "attackpilot:appearance";
const subscribeAppearance = (listener: () => void) => {
  window.addEventListener("storage", listener);
  window.addEventListener(appearanceEvent, listener);
  return () => {
    window.removeEventListener("storage", listener);
    window.removeEventListener(appearanceEvent, listener);
  };
};
const getAppearance = () => localStore.getItem(appearanceKey) === "dark" ? "dark" : "light";
const navigation = [
  ["review", "/attackpilot", "复盘工作台"],
  ["tasks", "/attackpilot/tasks", "任务库"],
  ["knowledge", "/attackpilot/knowledge", "漏洞知识库"],
  ["briefing", "/attackpilot/briefing", "项目介绍"],
] as const;

export default function AttackPilotWorkbench({ userId, onLogin }: { userId: string | null; onLogin: () => void }) {
  const pathname = usePathname();
  const section = pathname.includes("/tasks") ? "tasks" : pathname.includes("/knowledge") || pathname.includes("/learning") ? "knowledge" : pathname.includes("/briefing") ? "briefing" : "review";
  const detail = /^\/attackpilot\/tasks\/[^/]+/.test(pathname);
  const appearance = useSyncExternalStore(subscribeAppearance, getAppearance, () => "light");
  const isDark = appearance === "dark";
  const antdTheme = useMemo(
    () => ({
      algorithm: isDark ? theme.darkAlgorithm : theme.defaultAlgorithm,
      token: {
        colorPrimary: '#2563eb',
        colorInfo: '#38bdf8',
        colorSuccess: '#22c55e',
        colorWarning: '#f59e0b',
        colorError: '#ef4444',
        colorBgBase: isDark ? '#0b0f14' : '#f8fafc',
        colorTextBase: isDark ? '#e5e7eb' : '#0f172a',
        colorBorder: isDark ? '#263244' : '#dbe4f0',
        fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, sans-serif",
        borderRadius: 6,
        wireframe: false,
        fontSize: 14,
      },
      components: {
        Layout: {
          headerBg: isDark ? 'rgba(11,15,20,0.94)' : 'rgba(248,250,252,0.94)',
          bodyBg: 'transparent',
        },
        Card: {
          colorBgContainer: isDark ? '#111827' : '#ffffff',
          colorBorderSecondary: isDark ? '#263244' : '#dbe4f0',
          borderRadiusLG: 8,
        },
        Table: {
          colorBgContainer: 'transparent',
          headerBg: isDark ? 'rgba(15,23,42,0.72)' : '#f8fafc',
          headerColor: isDark ? '#94a3b8' : '#475569',
          rowHoverBg: isDark ? 'rgba(56,189,248,0.06)' : 'rgba(37,99,235,0.05)',
          borderColor: isDark ? '#263244' : '#e2e8f0',
        },
        Modal: {
          contentBg: isDark ? '#111827' : '#ffffff',
          headerBg: 'transparent',
          titleColor: isDark ? '#e5e7eb' : '#0f172a',
        },
        Button: {
          primaryShadow: 'none',
          defaultBorderColor: isDark ? '#263244' : '#dbe4f0',
          defaultColor: isDark ? '#e5e7eb' : '#0f172a',
          defaultBg: isDark ? 'transparent' : '#ffffff',
        },
        Select: {
          selectorBg: isDark ? '#0b0f14' : '#ffffff',
          optionSelectedBg: isDark ? 'rgba(59,130,246,0.12)' : 'rgba(37,99,235,0.1)',
          optionActiveBg: isDark ? 'rgba(59,130,246,0.08)' : 'rgba(37,99,235,0.06)',
        },
      },
    }),
    [isDark],
  );

  return (
    <AttackPilotIdentity.Provider value={{ userId, onLogin }}>
      <section className="attackpilot-root" data-appearance={appearance} data-ai-selection-ignore lang="zh-CN">
        <ConfigProvider locale={zhCN} theme={antdTheme} getPopupContainer={trigger => trigger?.closest(".attackpilot-root") as HTMLElement || document.querySelector<HTMLElement>(".attackpilot-root") || document.body}>
          <AntdApp>
            <div className={`app-root app-theme-${appearance}`}>
              <nav className="ap-module-nav" aria-label="AttackPilot 功能导航">
                <span className="ap-brand"><ShieldCheck size={21} /> AttackPilot</span>
                {navigation.map(([key, href, label]) => <Link key={key} href={href} aria-current={section === key ? "page" : undefined}>{label}</Link>)}
                <Button className="ap-appearance-toggle" icon={isDark ? <Sun size={16} /> : <Moon size={16} />} onClick={() => {
                  localStore.setItem(appearanceKey, isDark ? "light" : "dark");
                  window.dispatchEvent(new Event(appearanceEvent));
                }}>{isDark ? "白天模式" : "黑夜模式"}</Button>
              </nav>
              <div key={userId || "guest"}>
                {detail ? <Dashboard key={pathname} /> : section === "tasks" ? <TaskList /> : section === "knowledge" ? <Knowledge /> : section === "briefing" ? <Briefing /> : <LandingWarRoom />}
              </div>
            </div>
          </AntdApp>
        </ConfigProvider>
      </section>
    </AttackPilotIdentity.Provider>
  );
}
