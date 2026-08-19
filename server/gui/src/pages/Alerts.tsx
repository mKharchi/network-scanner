import { useState } from 'react';
import { api, type Alert } from '../api/client';
import { useFetch } from '../hooks/useFetch';
import { SeverityBadge, StatusBadge, type AlertSeverity, type AlertStatus } from '../components/Badge';
import { Button } from '../components/Button';
import { DataTable, type Column } from '../components/DataTable';
import { SectionCard } from '../components/Card';
import { SkeletonTable, ErrorState, EmptyState, Notice } from '../components/States';
import { formatDateTime, formatRelative } from '../utils/format';

export function AlertsPage() {
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [severityFilter, setSeverityFilter] = useState<string>('');
  const [selectedAlertId, setSelectedAlertId] = useState<number | null>(null);

  const { state: alertListState, refetch: refetchAlerts } = useFetch(
    () =>
      api.getAlerts({
        status: statusFilter || undefined,
        severity: severityFilter || undefined,
      }),
    [statusFilter, severityFilter],
    ['app:alert', 'alert'],
  );

  const { state: alertDetailState, refetch: refetchDetail } = useFetch(
    selectedAlertId ? () => api.getAlert(selectedAlertId) : null,
    [selectedAlertId],
  );

  const alerts: Alert[] =
    alertListState.status === 'success'
      ? alertListState.data.items
      : alertListState.status === 'error' && alertListState.staleData
        ? alertListState.staleData.items
        : [];

  const columns: Column<Alert>[] = [
    {
      key: 'title',
      label: 'Alert',
      render: (a) => (
        <div>
          <div style={{ fontWeight: 500 }}>{a.title}</div>
          <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)' }}>{a.type}</div>
        </div>
      ),
    },
    {
      key: 'client',
      label: 'Client',
      render: (a) => a.client?.hostname ?? null,
    },
    {
      key: 'severity',
      label: 'Severity',
      render: (a) => <SeverityBadge severity={a.severity as AlertSeverity} />,
    },
    {
      key: 'status',
      label: 'Status',
      render: (a) => <StatusBadge status={a.status as AlertStatus} />,
    },
    {
      key: 'detected_at',
      label: 'Detected',
      align: 'right',
      render: (a) => (
        <span style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)' }}>
          {formatRelative(a.detected_at)}
        </span>
      ),
    },
  ];

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Security & System Alerts</h1>
          <p className="page-description">
            Operational anomalies, forbidden process executions, and connection incidents.
          </p>
        </div>
        <Button variant="quiet" size="sm" onClick={refetchAlerts}>
          Refresh
        </Button>
      </div>

      {alertListState.status === 'error' && (
        <Notice variant="warning" title="Alerts data is stale">
          {alertListState.error.message}
        </Notice>
      )}

      {/* Filter Toolbar */}
      <div
        style={{
          display: 'flex',
          gap: 'var(--space-3)',
          marginBottom: 'var(--space-5)',
          flexWrap: 'wrap',
        }}
      >
        <select
          value={severityFilter}
          onChange={(e) => setSeverityFilter(e.target.value)}
          aria-label="Filter by severity"
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
          <option value="">All Severities</option>
          <option value="CRITICAL">Critical</option>
          <option value="HIGH">High</option>
          <option value="MEDIUM">Medium</option>
          <option value="LOW">Low</option>
        </select>

        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          aria-label="Filter by status"
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
          <option value="">All Statuses</option>
          <option value="NEW">New</option>
          <option value="ACKNOWLEDGED">Acknowledged</option>
          <option value="RESOLVED">Resolved</option>
        </select>
      </div>

      {/* Table */}
      <div style={{ marginBottom: 'var(--space-6)' }}>
        {alertListState.status === 'idle' || alertListState.status === 'loading' ? (
          <SkeletonTable rows={6} columns={5} />
        ) : alertListState.status === 'error' && !alertListState.staleData ? (
          <ErrorState
            title="Unable to load alerts"
            message={alertListState.error.message}
            onRetry={refetchAlerts}
          />
        ) : alerts.length === 0 ? (
          <EmptyState
            icon="🛡️"
            title="No alerts match these filters"
            body="All monitored devices and agents are operating within normal parameters."
          />
        ) : (
          <DataTable
            columns={columns}
            data={alerts}
            rowKey={(a) => String(a.id)}
            onRowClick={(a) => setSelectedAlertId(a.id)}
            aria-label="Alerts table"
          />
        )}
      </div>

      {/* Alert Detail Panel */}
      {selectedAlertId !== null && (
        <SectionCard
          title={`Alert Details (#${selectedAlertId})`}
          headerAction={
            <Button variant="quiet" size="sm" onClick={() => setSelectedAlertId(null)}>
              Close
            </Button>
          }
        >
          {alertDetailState.status === 'loading' ? (
            <div style={{ padding: 'var(--space-4)' }}>Loading alert details...</div>
          ) : alertDetailState.status === 'error' ? (
            <ErrorState
              title="Unable to load alert detail"
              message={alertDetailState.error.message}
              onRetry={refetchDetail}
            />
          ) : alertDetailState.status === 'success' ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
              <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center' }}>
                <SeverityBadge severity={alertDetailState.data.alert.severity} />
                <StatusBadge status={alertDetailState.data.alert.status} />
                <span style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)' }}>
                  Detected at {formatDateTime(alertDetailState.data.alert.detected_at)}
                </span>
              </div>

              <div>
                <h3 style={{ fontSize: 'var(--font-lg)', fontWeight: 600, marginBottom: 'var(--space-1)' }}>
                  {alertDetailState.data.alert.title}
                </h3>
                <p style={{ fontSize: 'var(--font-sm)', color: 'var(--text-muted)', lineHeight: 1.6 }}>
                  {alertDetailState.data.alert.description}
                </p>
              </div>

              {alertDetailState.data.alert.activity_log_id && (
                <div style={{ marginTop: 'var(--space-2)' }}>
                  <a
                    href={`/activity/${alertDetailState.data.alert.activity_log_id}`}
                    className="btn btn--secondary btn--sm"
                    style={{ textDecoration: 'none' }}
                  >
                    View Related Activity Log →
                  </a>
                </div>
              )}
            </div>
          ) : null}
        </SectionCard>
      )}
    </div>
  );
}
