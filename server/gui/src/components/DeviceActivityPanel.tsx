import { useState, useMemo, useEffect } from 'react';
import {
  api,
  type DeviceActivityResponse,
  type DeviceActivityPrediction,
} from '../api/client';
import { useFetch } from '../hooks/useFetch';
import { SectionCard } from './Card';
import { Button } from './Button';
import { Badge, type BadgeVariant } from './Badge';
import { DataTable, type Column } from './DataTable';
import { SkeletonTable, ErrorState, EmptyState } from './States';
import { formatDateTime, formatRelative, normalizeMac } from '../utils/format';
import '../styles/device-activity.css';

interface DeviceActivityPanelProps {
  deviceMac: string;
  initialLookback?: string;
}

const LOOKBACK_OPTIONS = [
  { label: 'Last 10 Minutes', value: '10m' },
  { label: 'Last 15 Minutes (Default)', value: '15m' },
  { label: 'Last 30 Minutes', value: '30m' },
  { label: 'Last 1 Hour', value: '1h' },
  { label: 'Last 4 Hours', value: '4h' },
  { label: 'Last 24 Hours', value: '24h' },
];

const AUTO_REFRESH_INTERVALS = [
  { label: 'Off', value: 0 },
  { label: '10s', value: 10000 },
  { label: '30s', value: 30000 },
  { label: '60s', value: 60000 },
];

interface ActivityConfig {
  label: string;
  icon: string;
  color: string;
  badgeVariant: BadgeVariant;
  description: string;
}

const ACTIVITY_MAP: Record<string, ActivityConfig> = {
  streaming: {
    label: 'Streaming Media',
    icon: '🎬',
    color: '#60a5fa',
    badgeVariant: 'primary',
    description: 'Video or music streaming playback (e.g. YouTube, Netflix, Spotify)',
  },
  file_transfer: {
    label: 'File Transfer / Backup',
    icon: '📦',
    color: '#c084fc',
    badgeVariant: 'info',
    description: 'Sustained bulk download, upload, cloud sync, or local backup',
  },
  chat: {
    label: 'Messaging / Chat',
    icon: '💬',
    color: '#34d399',
    badgeVariant: 'success',
    description: 'Interactive chat messages, Slack, WhatsApp, or instant messaging',
  },
  voip: {
    label: 'Voice / Video Call',
    icon: '📞',
    color: '#fbbf24',
    badgeVariant: 'warning',
    description: 'Real-time two-way audio or video communication (e.g. Zoom, Teams)',
  },
  other: {
    label: 'Web / Other Traffic',
    icon: '🌐',
    color: '#94a3b8',
    badgeVariant: 'muted',
    description: 'General web browsing, API polling, or non-bulk background traffic',
  },
  idle: {
    label: 'Idle / Ambient',
    icon: '🌙',
    color: '#64748b',
    badgeVariant: 'muted',
    description: 'Beacon/keepalive traffic without active user workload',
  },
  unknown: {
    label: 'Unknown / Mixed',
    icon: '❓',
    color: '#94a3b8',
    badgeVariant: 'muted',
    description: 'Traffic pattern does not strongly match a known profile',
  },
};

function getActivityConfig(activity: string): ActivityConfig {
  const norm = activity.toLowerCase().trim();
  return (
    ACTIVITY_MAP[norm] || {
      label: activity,
      icon: '⚡',
      color: '#94a3b8',
      badgeVariant: 'muted',
      description: 'Derived network activity',
    }
  );
}

function getStatusBadge(status?: string): { label: string; variant: BadgeVariant } {
  switch (status) {
    case 'ok':
      return { label: 'Active Inference', variant: 'success' };
    case 'low_confidence':
      return { label: 'Low Confidence', variant: 'warning' };
    case 'domain_shift':
      return { label: 'Domain Shift', variant: 'danger' };
    case 'no_recent_window':
      return { label: 'No Active Window', variant: 'muted' };
    case 'model_unavailable':
      return { label: 'Model Offline', variant: 'danger' };
    case 'model_incompatible':
      return { label: 'Model Mismatch', variant: 'warning' };
    default:
      return { label: status || 'Standard', variant: 'info' };
  }
}

export function DeviceActivityPanel({
  deviceMac,
  initialLookback = '15m',
}: DeviceActivityPanelProps) {
  const [lookback, setLookback] = useState<string>(initialLookback);
  const [limit, setLimit] = useState<number>(50);
  const [refreshInterval, setRefreshInterval] = useState<number>(30000);
  const [selectedActivityFilter, setSelectedActivityFilter] = useState<string>('ALL');
  const [selectedWindow, setSelectedWindow] = useState<DeviceActivityPrediction | null>(null);

  const fetchActivity = () => {
    if (!deviceMac) return Promise.reject(new Error('No MAC address provided.'));
    return api.getDeviceActivity(deviceMac, {
      lookback,
      limit,
    });
  };

  const { state, refetch } = useFetch<DeviceActivityResponse>(
    deviceMac ? fetchActivity : null,
    [deviceMac, lookback, limit],
  );

  // Auto-refresh interval
  useEffect(() => {
    if (!refreshInterval || refreshInterval <= 0) return;
    const timer = setInterval(() => {
      refetch();
    }, refreshInterval);
    return () => clearInterval(timer);
  }, [refreshInterval, refetch]);

  const data: DeviceActivityResponse | undefined =
    state.status === 'success' ? state.data : state.status === 'error' ? state.staleData : undefined;
  const currentPrediction = data?.current ?? null;
  const recentPredictions: DeviceActivityPrediction[] = useMemo(() => data?.recent ?? [], [data]);

  // Display prediction (selected or current)
  const activeFocusPrediction = selectedWindow || currentPrediction;

  // Filtered prediction windows
  const filteredPredictions: DeviceActivityPrediction[] = useMemo(() => {
    if (selectedActivityFilter === 'ALL') return recentPredictions;
    return recentPredictions.filter(
      (p: DeviceActivityPrediction) => p.activity.toLowerCase() === selectedActivityFilter.toLowerCase(),
    );
  }, [recentPredictions, selectedActivityFilter]);

  // Summary statistics
  const stats = useMemo(() => {
    if (!recentPredictions.length) return null;
    const totalWindows = recentPredictions.length;
    const counts: Record<string, number> = {};
    let confSum = 0;
    let lowConfCount = 0;

    recentPredictions.forEach((p: DeviceActivityPrediction) => {
      counts[p.activity] = (counts[p.activity] || 0) + 1;
      confSum += p.confidence;
      if (p.status === 'low_confidence' || p.confidence < 0.5) {
        lowConfCount++;
      }
    });

    let topActivity = 'unknown';
    let topCount = 0;
    Object.entries(counts).forEach(([act, cnt]) => {
      if (cnt > topCount) {
        topCount = cnt;
        topActivity = act;
      }
    });

    return {
      totalWindows,
      topActivity,
      topActivityShare: Math.round((topCount / totalWindows) * 100),
      avgConfidence: Math.round((confSum / totalWindows) * 100),
      lowConfCount,
      estimatedActiveSeconds: totalWindows * 30,
    };
  }, [recentPredictions]);

  const columns: Column<DeviceActivityPrediction>[] = [
    {
      key: 'window_time',
      label: 'Window Interval (30s)',
      render: (item: DeviceActivityPrediction) => {
        const start = formatDateTime(item.window_start);
        const rel = formatRelative(item.window_end);
        const isFocused = selectedWindow?.window_id === item.window_id;
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--font-xs)', fontWeight: isFocused ? 700 : 500 }}>
              {start}
            </span>
            <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
              {rel}
            </span>
          </div>
        );
      },
    },
    {
      key: 'activity',
      label: 'Predicted Activity',
      render: (item: DeviceActivityPrediction) => {
        const cfg = getActivityConfig(item.activity);
        return (
          <Badge variant={cfg.badgeVariant}>
            <span style={{ marginRight: '4px' }}>{cfg.icon}</span>
            {cfg.label}
          </Badge>
        );
      },
    },
    {
      key: 'confidence',
      label: 'Confidence',
      align: 'right',
      render: (item: DeviceActivityPrediction) => {
        const pct = Math.round(item.confidence * 100);
        const cfg = getActivityConfig(item.activity);
        return (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 'var(--space-2)' }}>
            <div
              style={{
                width: '45px',
                height: '4px',
                background: 'var(--surface-muted)',
                borderRadius: '2px',
                overflow: 'hidden',
              }}
            >
              <div
                style={{
                  width: `${pct}%`,
                  height: '100%',
                  background: cfg.color,
                }}
              />
            </div>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--font-xs)', minWidth: '32px' }}>
              {pct}%
            </span>
          </div>
        );
      },
    },
    {
      key: 'runner_up',
      label: 'Secondary Competitor',
      render: (item: DeviceActivityPrediction) => {
        if (!item.probabilities) return <span style={{ color: 'var(--text-faint)' }}>—</span>;
        const sorted = (Object.entries(item.probabilities) as [string, number][])
          .filter(([act]) => act.toLowerCase() !== item.activity.toLowerCase())
          .sort((a, b) => b[1] - a[1]);
        if (!sorted.length || sorted[0][1] <= 0.01) {
          return <span style={{ color: 'var(--text-faint)', fontSize: 'var(--font-xs)' }}>None (&lt;1%)</span>;
        }
        const [runnerAct, runnerProb] = sorted[0];
        const runnerCfg = getActivityConfig(runnerAct);
        return (
          <span style={{ fontSize: 'var(--font-xs)', color: 'var(--text-secondary)' }}>
            {runnerCfg.icon} {runnerCfg.label} ({Math.round(runnerProb * 100)}%)
          </span>
        );
      },
    },
    {
      key: 'status',
      label: 'Model Status',
      render: (item: DeviceActivityPrediction) => {
        const s = getStatusBadge(item.status);
        return <Badge variant={s.variant}>{s.label}</Badge>;
      },
    },
    {
      key: 'action',
      label: 'Detail',
      align: 'right',
      render: (item: DeviceActivityPrediction) => {
        const isSelected = selectedWindow?.window_id === item.window_id;
        return (
          <Button
            size="sm"
            variant={isSelected ? 'primary' : 'quiet'}
            onClick={(e) => {
              e.stopPropagation();
              setSelectedWindow(isSelected ? null : item);
            }}
          >
            {isSelected ? 'Focused 👁' : 'Inspect'}
          </Button>
        );
      },
    },
  ];

  return (
    <div className="activity-panel">
      {/* Top Toolbar */}
      <div className="activity-toolbar">
        <div className="activity-toolbar__controls">
          <label style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
            <span>Lookback:</span>
            <select
              className="activity-toolbar__select"
              value={lookback}
              onChange={(e) => setLookback(e.target.value)}
            >
              {LOOKBACK_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>

          <label style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
            <span>Windows:</span>
            <select
              className="activity-toolbar__select"
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
            >
              <option value={20}>20 (10 min)</option>
              <option value={50}>50 (25 min)</option>
              <option value={100}>100 (50 min)</option>
            </select>
          </label>

          <label style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
            <span>Auto-Refresh:</span>
            <select
              className="activity-toolbar__select"
              value={refreshInterval}
              onChange={(e) => setRefreshInterval(Number(e.target.value))}
            >
              {AUTO_REFRESH_INTERVALS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
          {data?.status && (
            <Badge variant={getStatusBadge(data.status).variant}>
              {getStatusBadge(data.status).label}
            </Badge>
          )}
          <Button
            size="sm"
            variant="secondary"
            onClick={refetch}
            disabled={state.status === 'loading'}
          >
            {state.status === 'loading' ? 'Refetching…' : '↻ Refresh Now'}
          </Button>
        </div>
      </div>

      {/* Loading & Error States */}
      {state.status === 'loading' && !data && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
          <SkeletonTable rows={4} columns={4} />
        </div>
      )}

      {state.status === 'error' && !data && (
        <ErrorState
          title="Could not load activity predictions"
          message={state.error.message}
          onRetry={refetch}
        />
      )}

      {/* Main Content Area */}
      {data && (
        <>
          {/* Active / Current Activity Hero */}
          {activeFocusPrediction ? (
            <div className="activity-hero">
              <div className="activity-hero__current">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span className="eyebrow eyebrow--accent">
                    {selectedWindow ? 'SELECTED PREDICTION WINDOW' : 'CURRENT REAL-TIME INFERENCE'}
                  </span>
                  {selectedWindow && (
                    <Button
                      size="sm"
                      variant="quiet"
                      onClick={() => setSelectedWindow(null)}
                    >
                      ✕ Reset to Latest
                    </Button>
                  )}
                </div>

                <div className="activity-hero__header">
                  <div className={`activity-icon-badge activity-icon-badge--${activeFocusPrediction.activity}`}>
                    {getActivityConfig(activeFocusPrediction.activity).icon}
                  </div>
                  <div>
                    <h2 className="activity-title">
                      {getActivityConfig(activeFocusPrediction.activity).label}
                    </h2>
                    <div style={{ color: 'var(--text-muted)', fontSize: 'var(--font-xs)' }}>
                      {getActivityConfig(activeFocusPrediction.activity).description}
                    </div>
                  </div>
                </div>

                <div className="activity-confidence-meter">
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 'var(--font-xs)' }}>
                    <span style={{ color: 'var(--text-muted)' }}>Confidence Score</span>
                    <strong style={{ fontFamily: 'var(--font-mono)', color: 'var(--primary)' }}>
                      {Math.round(activeFocusPrediction.confidence * 100)}%
                    </strong>
                  </div>
                  <div className="activity-confidence-bar">
                    <div
                      className="activity-confidence-fill"
                      style={{
                        width: `${Math.round(activeFocusPrediction.confidence * 100)}%`,
                        background: getActivityConfig(activeFocusPrediction.activity).color,
                      }}
                    />
                  </div>
                </div>

                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-2)', marginTop: 'var(--space-2)' }}>
                  <Badge variant="muted">
                    Model: {activeFocusPrediction.model_version || 'activity-rf-v2'}
                  </Badge>
                  <Badge variant="muted">
                    Window: 30s ({formatRelative(activeFocusPrediction.window_end)})
                  </Badge>
                  {activeFocusPrediction.status && activeFocusPrediction.status !== 'ok' && (
                    <Badge variant={getStatusBadge(activeFocusPrediction.status).variant}>
                      {getStatusBadge(activeFocusPrediction.status).label}
                    </Badge>
                  )}
                </div>
              </div>

              {/* Multi-Class Probability Distribution */}
              <div className="activity-hero__probabilities">
                <span className="eyebrow" style={{ marginBottom: 'var(--space-1)' }}>
                  TAXONOMY PROBABILITY VECTOR
                </span>
                {(Object.entries(activeFocusPrediction.probabilities || {}) as [string, number][])
                  .sort((a, b) => b[1] - a[1])
                  .map(([act, prob]) => {
                    const cfg = getActivityConfig(act);
                    const isTop = act.toLowerCase() === activeFocusPrediction.activity.toLowerCase();
                    const pct = Math.round(prob * 100);
                    return (
                      <div
                        key={act}
                        className={`prob-row ${isTop ? 'prob-row--winner' : ''}`}
                      >
                        <span className="prob-label">
                          {cfg.icon} {act}
                        </span>
                        <div className="prob-bar">
                          <div
                            className="prob-bar__fill"
                            style={{
                              width: `${pct}%`,
                              background: cfg.color,
                            }}
                          />
                        </div>
                        <span className="prob-value">{pct}%</span>
                      </div>
                    );
                  })}
              </div>
            </div>
          ) : (
            <SectionCard title="Current Activity State">
              <EmptyState
                title="No recent activity windows"
                body={`No derived 30s traffic windows detected for ${normalizeMac(deviceMac)} in the selected lookback period (${lookback}).`}
              />
            </SectionCard>
          )}

          {/* Quick Aggregate Stats Grid */}
          {stats && (
            <div className="activity-stats-grid">
              <div className="activity-stat-card">
                <span className="eyebrow">DOMINANT ACTIVITY</span>
                <strong>
                  {getActivityConfig(stats.topActivity).icon} {getActivityConfig(stats.topActivity).label}
                </strong>
                <span>{stats.topActivityShare}% of observed traffic</span>
              </div>
              <div className="activity-stat-card">
                <span className="eyebrow">MEAN CONFIDENCE</span>
                <strong>{stats.avgConfidence}%</strong>
                <span>Across {stats.totalWindows} window evaluations</span>
              </div>
              <div className="activity-stat-card">
                <span className="eyebrow">OBSERVED ACTIVE TIME</span>
                <strong>~{Math.round(stats.estimatedActiveSeconds / 60)} min</strong>
                <span>{stats.totalWindows} consecutive 30s slices</span>
              </div>
              <div className="activity-stat-card">
                <span className="eyebrow">RELIABILITY INDEX</span>
                <strong>
                  {Math.round(((stats.totalWindows - stats.lowConfCount) / stats.totalWindows) * 100)}%
                </strong>
                <span>{stats.lowConfCount} marginal confidence windows</span>
              </div>
            </div>
          )}

          {/* Activity Prediction Windows History Table */}
          <SectionCard
            title={`Chronological Activity Inferences (${filteredPredictions.length} Windows)`}
            headerAction={
              <div style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
                {['ALL', 'streaming', 'file_transfer', 'chat', 'voip', 'other'].map((act) => (
                  <Button
                    key={act}
                    size="sm"
                    variant={selectedActivityFilter === act ? 'primary' : 'quiet'}
                    onClick={() => setSelectedActivityFilter(act)}
                  >
                    {act === 'ALL' ? 'All Classes' : `${getActivityConfig(act).icon} ${act}`}
                  </Button>
                ))}
              </div>
            }
          >
            {filteredPredictions.length > 0 ? (
              <DataTable<DeviceActivityPrediction>
                columns={columns}
                data={filteredPredictions}
                rowKey={(row) => row.window_id}
                onRowClick={(row) => setSelectedWindow(selectedWindow?.window_id === row.window_id ? null : row)}
              />
            ) : (
              <EmptyState
                title="No matching prediction windows"
                body="Try widening the lookback window or selecting All Classes."
              />
            )}
          </SectionCard>
        </>
      )}
    </div>
  );
}
