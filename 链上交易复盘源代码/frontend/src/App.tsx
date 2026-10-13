// src/App.tsx
import { useEffect, useMemo, useState } from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { ConfigProvider, theme, App as AntdApp, Button, Tooltip } from 'antd';
import { Moon, Sun } from 'lucide-react';
import LandingWarRoom from './pages/LandingWarRoom';
import LearningCenter from './pages/LearningCenter';
import Briefing from './pages/Briefing';
import TaskList from './pages/TaskList';
import Dashboard from './pages/Dashboard';
import './App.css';

type AppearanceMode = 'light' | 'dark';

const APPEARANCE_STORAGE_KEY = 'riskpilot-appearance';

function App() {
  const [appearance, setAppearance] = useState<AppearanceMode>(() => {
    const saved = window.localStorage.getItem(APPEARANCE_STORAGE_KEY);
    return saved === 'dark' || saved === 'light' ? saved : 'light';
  });

  const isDark = appearance === 'dark';

  useEffect(() => {
    document.body.dataset.appearance = appearance;
    window.localStorage.setItem(APPEARANCE_STORAGE_KEY, appearance);
  }, [appearance]);

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
    <ConfigProvider theme={antdTheme}>
      <AntdApp>
        <Router>
          <div className={`app-root app-theme-${appearance}`}>
            <Routes>
              <Route path="/" element={<LandingWarRoom />} />
              <Route path="/learning" element={<LearningCenter />} />
              <Route path="/briefing" element={<Briefing />} />
              <Route path="/tasks" element={<TaskList />} />
              <Route path="/tasks/:taskId" element={<Dashboard />} />
            </Routes>
            <Tooltip title={isDark ? '切换到白天模式' : '切换到黑夜模式'}>
              <Button
                className="appearance-toggle"
                icon={isDark ? <Sun size={16} /> : <Moon size={16} />}
                onClick={() => setAppearance(isDark ? 'light' : 'dark')}
              >
                {isDark ? '白天模式' : '黑夜模式'}
              </Button>
            </Tooltip>
          </div>
        </Router>
      </AntdApp>
    </ConfigProvider>
  );
}

export default App;
