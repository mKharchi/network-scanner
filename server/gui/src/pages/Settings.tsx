import { api } from '../api/client';
import { useFetch } from '../hooks/useFetch';
import { SeverityBadge, type AlertSeverity } from '../components/Badge';
import { SectionCard } from '../components/Card';
import { Button } from '../components/Button';
import { SkeletonTable, ErrorState, Notice } from '../components/States';
import { DAY_NAMES, formatDateTime } from '../utils/format';

interface WorkingHoursData {
  rules: { day_of_week: number; start_time: string; end_time: string; enabled: boolean }[];
  current_status: { within_working_hours: boolean; checked_at: string };
}

interface ForbiddenProcessesData {
  items: { process_name: string; severity: string; enabled: boolean; description: string | null }[];
}

export function SettingsPage() {
  const {
    state: whState,
    refetch: refetchWh,
  } = useFetch<WorkingHoursData>(() => api.getWorkingHours(), []);

  const {
    state: fpState,
    refetch: refetchFp,
  } = useFetch<ForbiddenProcessesData>(() => api.getForbiddenProcesses(), []);

  const isStale = whState.status === 'error' || fpState.status === 'error';

  const whData: WorkingHoursData | null =
    whState.status === 'success'
      ? whState.data
      : whState.status === 'error' && whState.staleData
        ? whState.staleData
        : null;

  const fpData: ForbiddenProcessesData | null =
    fpState.status === 'success'
      ? fpState.data
      : fpState.status === 'error' && fpState.staleData
        ? fpState.staleData
        : null;

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Monitoring Policies & Settings</h1>
          <p className="page-description">
            Read-only configuration policies enforced across network clients and alerts.
          </p>
        </div>
        <Button
          variant="quiet"
          size="sm"
          onClick={() => {
            refetchWh();
            refetchFp();
          }}
        >
          Refresh All
        </Button>
      </div>

      {isStale && (
        <Notice variant="warning" title="Some configuration settings could not be verified">
          Showing cached policies from server.
        </Notice>
      )}

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(400px, 1fr))',
          gap: 'var(--space-6)',
        }}
      >
        {/* Working Hours Policy */}
        <SectionCard title="Working Hours Policy">
          {whState.status === 'loading' || whState.status === 'idle' ? (
            <SkeletonTable rows={5} columns={3} />
          ) : whState.status === 'error' && !whData ? (
            <ErrorState
              title="Unable to load working hours"
              message={whState.error.message}
              onRetry={refetchWh}
            />
          ) : whData ? (
            <div>
              <div
                style={{
                  padding: 'var(--space-3)',
                  borderRadius: 'var(--radius-sm)',
                  background: whData.current_status.within_working_hours
                    ? 'var(--success-bg)'
                    : 'var(--warning-bg)',
                  color: whData.current_status.within_working_hours
                    ? 'var(--success)'
                    : 'var(--warning)',
                  fontSize: 'var(--font-xs)',
                  fontWeight: 600,
                  marginBottom: 'var(--space-4)',
                }}
              >
                Current status:{' '}
                {whData.current_status.within_working_hours
                  ? 'Within Working Hours'
                  : 'Outside Working Hours'}{' '}
                · Verified at {formatDateTime(whData.current_status.checked_at)}
              </div>

              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--font-sm)' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border)', textAlign: 'left' }}>
                    <th style={{ padding: 'var(--space-2) 0', color: 'var(--text-muted)' }}>Day</th>
                    <th style={{ padding: 'var(--space-2) 0', color: 'var(--text-muted)' }}>Schedule</th>
                    <th style={{ padding: 'var(--space-2) 0', color: 'var(--text-muted)', textAlign: 'right' }}>
                      Status
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {whData.rules.map((r) => (
                    <tr key={r.day_of_week} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                      <td style={{ padding: 'var(--space-2) 0', fontWeight: 500 }}>
                        {DAY_NAMES[r.day_of_week] ?? `Day ${r.day_of_week}`}
                      </td>
                      <td style={{ padding: 'var(--space-2) 0', fontFamily: 'var(--font-mono)', fontSize: 'var(--font-xs)' }}>
                        {r.start_time} – {r.end_time}
                      </td>
                      <td style={{ padding: 'var(--space-2) 0', textAlign: 'right' }}>
                        <span
                          style={{
                            fontSize: 'var(--font-xs)',
                            color: r.enabled ? 'var(--success)' : 'var(--text-faint)',
                          }}
                        >
                          {r.enabled ? 'Active' : 'Disabled'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </SectionCard>

        {/* Forbidden Processes */}
        <SectionCard title="Forbidden Process Rules">
          {fpState.status === 'loading' || fpState.status === 'idle' ? (
            <SkeletonTable rows={4} columns={3} />
          ) : fpState.status === 'error' && !fpData ? (
            <ErrorState
              title="Unable to load process rules"
              message={fpState.error.message}
              onRetry={refetchFp}
            />
          ) : fpData ? (
            <div>
              <p
                style={{
                  fontSize: 'var(--font-xs)',
                  color: 'var(--text-muted)',
                  marginBottom: 'var(--space-4)',
                }}
              >
                Agents actively terminate or alert when any of these binaries execute on a managed client.
              </p>

              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
                {fpData.items.map((item) => (
                  <div
                    key={item.process_name}
                    style={{
                      padding: 'var(--space-3)',
                      borderRadius: 'var(--radius-sm)',
                      border: '1px solid var(--border-subtle)',
                      background: 'var(--surface-muted)',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ fontWeight: 600, fontFamily: 'var(--font-mono)' }}>
                        {item.process_name}
                      </span>
                      <SeverityBadge severity={item.severity as AlertSeverity} />
                    </div>
                    {item.description && (
                      <div
                        style={{
                          fontSize: 'var(--font-xs)',
                          color: 'var(--text-muted)',
                          marginTop: 'var(--space-1)',
                        }}
                      >
                        {item.description}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </SectionCard>
      </div>
    </div>
  );
}
