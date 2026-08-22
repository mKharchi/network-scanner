import { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api, type ActivityLogRecord } from '../api/client';
import { useFetch } from '../hooks/useFetch';
import { Button } from '../components/Button';
import { DataTable, type Column } from '../components/DataTable';
import { SectionCard } from '../components/Card';
import { SkeletonTable, ErrorState, EmptyState, Notice } from '../components/States';
import { formatDateTime, formatRelative } from '../utils/format';

interface ActivityItem {
  time: string;
  type: string;
  detail: unknown;
}

export function ActivityLogsPage() {
  const { logId } = useParams<{ logId?: string }>();
  const navigate = useNavigate();
  const selectedLogId = logId ? parseInt(logId, 10) : null;

  const [periodFilter, setPeriodFilter] = useState('');

  const { state: logsListState, refetch: refetchLogs } = useFetch(
    () => api.getActivityLogs({ period: periodFilter || undefined }),
    [periodFilter],
  );

  const { state: logDetailState, refetch: refetchLogDetail } = useFetch(
    selectedLogId ? () => api.getActivityLog(selectedLogId) : null,
    [selectedLogId],
  );

  const logs: ActivityLogRecord[] =
    logsListState.status === 'success'
      ? logsListState.data.items
      : logsListState.status === 'error' && logsListState.staleData
        ? logsListState.staleData.items
        : [];

  const columns: Column<ActivityLogRecord>[] = [
    {
      key: 'id',
      label: 'Log ID',
      mono: true,
      render: (l) => `#${l.id}`,
    },
    {
      key: 'client',
      label: 'Client',
      render: (l) => l.client?.hostname ?? null,
    },
    {
      key: 'period',
      label: 'Period',
      render: (l) => (
        <span
          style={{
            display: 'inline-block',
            padding: '2px 8px',
            borderRadius: 'var(--radius-sm)',
            background: 'var(--surface-muted)',
            fontSize: 'var(--font-xs)',
            fontWeight: 500,
          }}
        >
          {l.period}
        </span>
      ),
    },
    {
      key: 'generated_at',
      label: 'Generated At',
      render: (l) => formatDateTime(l.generated_at),
    },
    {
      key: 'received_at',
      label: 'Received',
      align: 'right',
      render: (l) => (
        <span style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)' }}>
          {formatRelative(l.received_at)}
        </span>
      ),
    },
  ];

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Activity Logs</h1>
          <p className="page-description">
            Periodic client activity audits, including running processes and shell executions.
          </p>
        </div>
        <Button variant="quiet" size="sm" onClick={refetchLogs}>
          Refresh
        </Button>
      </div>

      {logsListState.status === 'error' && (
        <Notice variant="warning" title="Logs data is stale">
          {logsListState.error.message}
        </Notice>
      )}

      {/* Filter toolbar */}
      <div
        style={{
          display: 'flex',
          gap: 'var(--space-3)',
          marginBottom: 'var(--space-5)',
          alignItems: 'center',
        }}
      >
        <select
          value={periodFilter}
          onChange={(e) => setPeriodFilter(e.target.value)}
          aria-label="Filter by period"
          style={{
            padding: '0 var(--space-3)',
            height: 36,
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius)',
            fontFamily: 'var(--font-sans)',
            fontSize: 'var(--font-sm)',
            background: 'var(--surface)',
            color: 'var(--text)',
          }}
        >
          <option value="">All Periods</option>
          <option value="1h">1 Hour</option>
          <option value="1d">1 Day</option>
          <option value="1w">1 Week</option>
        </select>
      </div>

      {/* Log list table */}
      <div style={{ marginBottom: 'var(--space-6)' }}>
        {logsListState.status === 'idle' || logsListState.status === 'loading' ? (
          <SkeletonTable rows={6} columns={5} />
        ) : logsListState.status === 'error' && !logsListState.staleData ? (
          <ErrorState
            title="Unable to load activity logs"
            message={logsListState.error.message}
            onRetry={refetchLogs}
          />
        ) : logs.length === 0 ? (
          <EmptyState
            icon="📜"
            title="No activity logs found"
            body="No client activity summaries match the current criteria."
          />
        ) : (
          <DataTable
            columns={columns}
            data={logs}
            rowKey={(l) => String(l.id)}
            onRowClick={(l) => navigate(`/activity/${l.id}`)}
            aria-label="Activity logs table"
          />
        )}
      </div>

      {/* Selected Log Timeline Detail */}
      {selectedLogId !== null && (
        <SectionCard
          title={`Activity Log Content (#${selectedLogId})`}
          headerAction={
            <Button variant="quiet" size="sm" onClick={() => navigate('/activity')}>
              Close
            </Button>
          }
        >
          {logDetailState.status === 'loading' ? (
            <div style={{ padding: 'var(--space-4)' }}>Loading log details...</div>
          ) : logDetailState.status === 'error' ? (
            <ErrorState
              title="Log content unavailable"
              message={logDetailState.error.message}
              onRetry={refetchLogDetail}
            />
          ) : logDetailState.status === 'success' ? (
            <div>
              <div
                style={{
                  fontSize: 'var(--font-xs)',
                  color: 'var(--text-muted)',
                  marginBottom: 'var(--space-4)',
                }}
              >
                Client: <strong>{logDetailState.data.log.client?.hostname ?? '—'}</strong> · Period:{' '}
                <strong>{logDetailState.data.log.period}</strong> · Received:{' '}
                {formatDateTime(logDetailState.data.log.received_at)}
              </div>

              {logDetailState.data.activity.length === 0 ? (
                <EmptyState
                  icon="📝"
                  title="Empty log payload"
                  body="No individual activity entries were contained in this log payload."
                />
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
                  {logDetailState.data.activity.map((item: ActivityItem, idx: number) => (
                    <div
                      key={idx}
                      style={{
                        padding: 'var(--space-3)',
                        borderRadius: 'var(--radius-sm)',
                        background: 'var(--surface-muted)',
                        border: '1px solid var(--border-subtle)',
                        fontSize: 'var(--font-sm)',
                      }}
                    >
                      <div
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          marginBottom: 'var(--space-1)',
                        }}
                      >
                        <span style={{ fontWeight: 600, color: 'var(--primary)' }}>
                          {item.type}
                        </span>
                        <span
                          style={{
                            fontSize: 'var(--font-xs)',
                            color: 'var(--text-muted)',
                            fontFamily: 'var(--font-mono)',
                          }}
                        >
                          {formatDateTime(item.time)}
                        </span>
                      </div>
                      <pre
                        style={{
                          fontSize: 'var(--font-xs)',
                          fontFamily: 'var(--font-mono)',
                          color: 'var(--text-muted)',
                          whiteSpace: 'pre-wrap',
                          wordBreak: 'break-all',
                          margin: 0,
                        }}
                      >
                        {typeof item.detail === 'string'
                          ? item.detail
                          : JSON.stringify(item.detail, null, 2)}
                      </pre>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : null}
        </SectionCard>
      )}
    </div>
  );
}
