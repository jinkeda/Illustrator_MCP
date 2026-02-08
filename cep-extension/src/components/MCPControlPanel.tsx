import React, { useEffect, useRef, useMemo, useState } from 'react';
import { Zap, Activity } from 'lucide-react';
import { useMCP } from '../hooks/useMCP';

// Professional palette
const COLORS = {
  bgRoot: '#09090b',
  bgHeader: '#111113',
  textPrimary: 'rgba(255,255,255,0.95)',
  textSecondary: 'rgba(255,255,255,0.55)',
  textMuted: 'rgba(255,255,255,0.30)',
  success: '#4ade80',
  accent: '#60a5fa',
  warning: '#fbbf24',
  danger: '#f87171',
  border: 'rgba(255,255,255,0.08)',
};

interface GroupedLog {
  id: string;
  timestamp: string;
  message: string;
  type: string;
  count: number;
}

function groupLogs(logs: Array<{ id: string; timestamp: string; message: string; type: string }>): GroupedLog[] {
  if (logs.length === 0) return [];
  const grouped: GroupedLog[] = [];
  let current: GroupedLog | null = null;
  for (const log of logs) {
    if (current && current.message === log.message) {
      current.count++;
      current.timestamp = log.timestamp;
    } else {
      if (current) grouped.push(current);
      current = { ...log, count: 1 };
    }
  }
  if (current) grouped.push(current);
  return grouped;
}

export function MCPControlPanel() {
  const { status, logs, connect, disconnect } = useMCP();
  const scrollRef = useRef<HTMLDivElement>(null);
  const prevStatus = useRef(status);
  const [flash, setFlash] = useState(false);

  useEffect(() => {
    if (prevStatus.current !== 'connected' && status === 'connected') {
      setFlash(true);
      setTimeout(() => setFlash(false), 600);
    }
    prevStatus.current = status;
  }, [status]);

  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  const toggleConnection = () => {
    if (status === 'connected') disconnect();
    else connect();
  };

  const groupedLogs = useMemo(() => groupLogs(logs), [logs]);

  const statusConfig = {
    connected: { color: COLORS.success, label: 'Connected', btnLabel: 'Stop', btnColor: COLORS.danger },
    connecting: { color: COLORS.accent, label: 'Connecting...', btnLabel: 'Wait', btnColor: COLORS.textMuted },
    disconnected: { color: COLORS.textMuted, label: 'Disconnected', btnLabel: 'Connect', btnColor: COLORS.success },
    error: { color: COLORS.danger, label: 'Error', btnLabel: 'Retry', btnColor: COLORS.accent },
  };
  const cfg = statusConfig[status] || statusConfig.disconnected;

  const getLogColor = (type: string) => ({
    success: COLORS.success,
    error: COLORS.danger,
    warning: COLORS.warning,
    debug: COLORS.accent,
  }[type] || COLORS.textSecondary);

  return (
    <div style={{
      width: '100%',
      height: '100%',
      display: 'flex',
      flexDirection: 'column',
      backgroundColor: COLORS.bgRoot,
      fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", system-ui, sans-serif',
      color: COLORS.textPrimary,
      overflow: 'hidden',
    }}>

      {/* ===== COMPACT HEADER ===== */}
      <header style={{
        height: '44px',
        flexShrink: 0,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 14px',
        backgroundColor: COLORS.bgHeader,
        borderBottom: `1px solid ${COLORS.border}`,
      }}>
        {/* Sleek Status Pill */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
          padding: '4px 10px 4px 8px',
          borderRadius: '12px',
          backgroundColor: `${cfg.color}12`,
          border: `1px solid ${cfg.color}25`,
        }}>
          <div style={{
            width: '6px',
            height: '6px',
            borderRadius: '50%',
            backgroundColor: cfg.color,
            boxShadow: flash ? `0 0 6px ${cfg.color}` : 'none',
            transition: 'box-shadow 0.3s',
          }} />
          <span style={{ fontSize: '11px', color: cfg.color, fontWeight: 500, letterSpacing: '0.02em' }}>
            {cfg.label}
          </span>
        </div>

        {/* Right: Icon Button */}
        <button
          onClick={toggleConnection}
          disabled={status === 'connecting'}
          title={status === 'connected' ? 'Disconnect' : 'Connect'}
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: '32px',
            height: '32px',
            borderRadius: '8px',
            border: `1px solid ${COLORS.border}`,
            cursor: status === 'connecting' ? 'default' : 'pointer',
            backgroundColor: 'transparent',
            color: status === 'connected' ? COLORS.success : COLORS.textMuted,
            opacity: status === 'connecting' ? 0.5 : 1,
            transition: 'all 0.15s',
          }}
          onMouseEnter={(e) => {
            if (status === 'connected') {
              e.currentTarget.style.backgroundColor = 'rgba(248,113,113,0.12)';
              e.currentTarget.style.color = COLORS.danger;
            } else if (status !== 'connecting') {
              e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.06)';
              e.currentTarget.style.color = COLORS.textPrimary;
            }
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.backgroundColor = 'transparent';
            e.currentTarget.style.color = status === 'connected' ? COLORS.success : COLORS.textMuted;
          }}
        >
          {status === 'connected' ? <Activity size={15} /> : <Zap size={15} />}
        </button>
      </header>

      {/* ===== LOG TERMINAL ===== */}
      <main style={{
        flex: 1,
        minHeight: 0,
        overflow: 'auto',
        padding: '8px 12px',
        fontFamily: '"SF Mono", "Fira Code", Menlo, Monaco, monospace',
        fontSize: '11px',
        lineHeight: '18px',
      }}>
        {groupedLogs.length === 0 ? (
          <div style={{ color: COLORS.textMuted, padding: '4px 0' }}>
            Waiting for activity...
          </div>
        ) : (
          groupedLogs.map((log) => (
            <div key={log.id} style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              whiteSpace: 'nowrap',
              overflow: 'hidden',
            }}>
              {/* Dot indicator */}
              <span style={{
                width: '4px',
                height: '4px',
                borderRadius: '50%',
                backgroundColor: getLogColor(log.type),
                flexShrink: 0,
              }} />
              {/* Timestamp */}
              <span style={{
                color: COLORS.textMuted,
                flexShrink: 0,
                fontVariantNumeric: 'tabular-nums',
              }}>
                {log.timestamp}
              </span>
              {/* Message */}
              <span style={{
                color: getLogColor(log.type),
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}>
                {log.message}
                {log.count > 1 && (
                  <span style={{ color: COLORS.textMuted, marginLeft: '4px' }}>×{log.count}</span>
                )}
              </span>
            </div>
          ))
        )}
        <div ref={scrollRef} />
      </main>

      {/* ===== FOOTER ===== */}
      <footer style={{
        height: '22px',
        flexShrink: 0,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 12px',
        backgroundColor: COLORS.bgHeader,
        borderTop: `1px solid ${COLORS.border}`,
        fontSize: '10px',
        color: COLORS.textMuted,
        fontFamily: '"SF Mono", Menlo, monospace',
      }}>
        <span>ws://127.0.0.1:8081</span>
        <span>v1.0.1</span>
      </footer>

      <style>{`
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.08); border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.15); }
      `}</style>
    </div>
  );
}
