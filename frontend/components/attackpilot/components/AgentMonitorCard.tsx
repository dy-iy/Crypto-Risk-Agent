// src/components/AgentMonitorCard.tsx
import React, { useEffect, useRef } from 'react';
import { Card, Badge, Typography } from 'antd';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { LogMessage } from '../types';

interface AgentProps {
  name: string;
  status: 'idle' | 'running' | 'error';
  logs: LogMessage[];
}

const AgentMonitorCard: React.FC<AgentProps> = ({ name, status, logs }) => {
  const logEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  return (
    <Card
      size="small"
      title={
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ fontSize: '13px', fontWeight: 500 }}>{name}</span>
          <Badge status={status === 'running' ? 'processing' : 'default'} text={status.toUpperCase()} />
        </div>
      }
      style={{ height: '100%', display: 'flex', flexDirection: 'column', background: '#18181b', border: '1px solid rgba(255,255,255,0.06)', borderRadius: '8px' }}
      styles={{ body: { flex: 1, overflow: 'hidden', padding: '12px' } }}
    >
      <div style={{ height: '300px', overflowY: 'auto', fontSize: '12px', color: '#e4e4e7', lineHeight: '1.6' }} className="log-container">
        {logs.map((log, index) => (
          <div key={index} style={{ marginBottom: '6px', paddingBottom: '6px', borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
            <Typography.Text style={{ fontSize: '10px', color: '#52525b', fontVariantNumeric: 'tabular-nums' }}>
              [{new Date(log.timestamp).toLocaleTimeString()}]
            </Typography.Text>
            <div className="markdown-body">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{log.message}</ReactMarkdown>
            </div>
          </div>
        ))}
        <div ref={logEndRef} />
      </div>
    </Card>
  );
};

export default AgentMonitorCard;
