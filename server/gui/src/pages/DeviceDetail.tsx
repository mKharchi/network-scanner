import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { useFetch } from '../hooks/useFetch';
import { ClassificationBadge } from '../components/Badge';
import { Button } from '../components/Button';
import { SectionCard } from '../components/Card';
import { Skeleton, SkeletonTable, ErrorState, EmptyState, Notice } from '../components/States';
import { DataTable, type Column } from '../components/DataTable';
import { formatDateTime, formatRelative, normalizeMac } from '../utils/format';

interface ObservationItem {
  source_type: string;
  source_client_id: string | null;
  ip_address: string | null;
  interface: string | null;
  entry_type: string;
  observed_at: string;
}

function DetailRow({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '10rem 1fr',
        gap: 'var(--space-3)',
        padding: 'var(--space-2) 0',
        borderBottom: '1px solid var(--border-subtle)',
        alignItems: 'baseline',
      }}
    >
      <span style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', fontWeight: 500 }}>
        {label}
      </span>
      <span
        style={{
          fontSize: 'var(--font-sm)',
          fontFamily: mono ? 'var(--font-mono)' : undefined,
          wordBreak: 'break-all',
        }}
      >
        {value ?? <span style={{ color: 'var(--text-faint)' }}>—</span>}
      </span>
    </div>
  );
}

const obsColumns: Column<ObservationItem>[] = [
  {
    key: 'source_type',
    label: 'Source',
    render: (item) => <span style={{ fontWeight: 500 }}>{item.source_type}</span>,
  },
  {
    key: 'source_client_id',
    label: 'Reporting Client',
    mono: true,
    render: (item) => item.source_client_id ?? null,
  },
  {
    key: 'ip_address',
    label: 'IP Address',
    mono: true,
    render: (item) => item.ip_address ?? null,
  },
  {
    key: 'interface',
    label: 'Interface',
    render: (item) => item.interface ?? null,
  },
  {
    key: 'entry_type',
    label: 'Type',
    render: (item) => item.entry_type,
  },
  {
    key: 'observed_at',
    label: 'Observed At',
    align: 'right',
    render: (item) => (
      <span style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)' }}>
        {formatDateTime(item.observed_at)}
      </span>
    ),
  },
];

export function DeviceDetailPage() {
  const { mac } = useParams<{ mac: string }>();
  const navigate = useNavigate();

  const { state, refetch } = useFetch(mac ? () => api.getNetworkDevice(mac) : null, [mac]);

  if (state.status === 'idle' || state.status === 'loading') {
    return <DeviceDetailSkeleton />;
  }

  if (state.status === 'error' && !state.staleData) {
    return (
      <ErrorState
        title="Unable to load device details"
        message={state.error.message}
        onRetry={refetch}
      />
    );
  }

  const d = state.status === 'success' ? state.data : state.staleData!;
  const dev = d.device;

  return (
    <div>
      {/* Back and Refresh toolbar */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--space-3)',
          marginBottom: 'var(--space-5)',
        }}
      >
        <Button variant="quiet" size="sm" onClick={() => navigate('/network/latest')}>
          ← Latest Scan
        </Button>
        <Button variant="quiet" size="sm" onClick={refetch}>
          Refresh
        </Button>
      </div>

      {state.status === 'error' && (
        <Notice variant="warning" title="Showing stale device details">
          {state.error.message}
        </Notice>
      )}

      {/* Header */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--space-4)',
          marginBottom: 'var(--space-6)',
          paddingBottom: 'var(--space-4)',
          borderBottom: '1px solid var(--border)',
        }}
      >
        <div
          style={{
            width: 48,
            height: 48,
            borderRadius: 'var(--radius)',
            background: dev.is_managed ? 'var(--primary)' : 'var(--surface-muted)',
            color: dev.is_managed ? '#fff' : 'var(--text-muted)',
            border: '1px solid var(--border)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 20,
            flexShrink: 0,
          }}
          aria-hidden="true"
        >
          {dev.is_managed ? '🛡️' : '🌐'}
        </div>
        <div>
          <h1
            style={{
              fontSize: 'var(--font-xl)',
              fontWeight: 600,
              fontFamily: dev.hostname ? 'var(--font-sans)' : 'var(--font-mono)',
              marginBottom: 'var(--space-1)',
            }}
          >
            {dev.hostname || normalizeMac(dev.mac_address)}
          </h1>
          <div
            style={{
              fontSize: 'var(--font-sm)',
              color: 'var(--text-muted)',
              marginBottom: 'var(--space-2)',
              fontWeight: 500,
            }}
          >
            Last seen: {formatDateTime(dev.last_observed_at)} ({formatRelative(dev.last_observed_at)})
          </div>
          <div
            style={{
              display: 'flex',
              gap: 'var(--space-2)',
              alignItems: 'center',
              flexWrap: 'wrap',
            }}
          >
            <ClassificationBadge managed={dev.is_managed} />
            {dev.vendor && (
              <span style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)' }}>
                {dev.vendor}
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Two columns: Identity & OS */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))',
          gap: 'var(--space-6)',
          marginBottom: 'var(--space-6)',
        }}
      >
        <SectionCard title="Device Identity">
          <div>
            <DetailRow label="MAC Address" value={normalizeMac(dev.mac_address)} mono />
            <DetailRow label="IP Address" value={dev.ip_address} mono />
            <DetailRow label="Hostname" value={dev.hostname} />
            <DetailRow label="Vendor / OUI" value={dev.vendor} />
            <DetailRow
              label="Last Seen"
              value={`${formatDateTime(dev.last_observed_at)} (${formatRelative(dev.last_observed_at)})`}
            />
            <DetailRow
              label="Classification"
              value={<ClassificationBadge managed={dev.is_managed} />}
            />
            {dev.managed_client_id && (
              <DetailRow
                label="Managed Client"
                value={
                  <a
                    href={`/clients/${encodeURIComponent(dev.managed_client_id)}`}
                    style={{ color: 'var(--primary)', textDecoration: 'underline' }}
                  >
                    {dev.managed_client_id}
                  </a>
                }
                mono
              />
            )}
          </div>
        </SectionCard>

        <SectionCard title="Operating System & Enrichment">
          <div>
            <DetailRow label="OS Name" value={dev.os.name} />
            <DetailRow label="OS Family" value={dev.os.family} />
            <DetailRow
              label="Confidence"
              value={dev.os.confidence !== null ? `${Math.round(dev.os.confidence * 100)}%` : null}
            />
            <DetailRow
              label="Discovery Sources"
              value={dev.sources.length ? dev.sources.join(', ') : 'None recorded'}
            />
          </div>
        </SectionCard>
      </div>

      {/* Observation History */}
      <SectionCard title="Observation History">
        {d.observations.length === 0 ? (
          <EmptyState
            icon="📋"
            title="No observation records"
            body="No individual observation events recorded for this MAC address."
          />
        ) : (
          <DataTable
            columns={obsColumns}
            data={d.observations}
            rowKey={(item, idx) => `${item.observed_at}-${item.source_type}-${idx}`}
            aria-label="Device observations"
          />
        )}
      </SectionCard>
    </div>
  );
}

function DeviceDetailSkeleton() {
  return (
    <div>
      <div style={{ display: 'flex', gap: 'var(--space-3)', marginBottom: 'var(--space-5)' }}>
        <Skeleton variant="text-sm" width="6rem" />
      </div>
      <div
        style={{
          display: 'flex',
          gap: 'var(--space-4)',
          marginBottom: 'var(--space-6)',
          paddingBottom: 'var(--space-4)',
          borderBottom: '1px solid var(--border)',
        }}
      >
        <Skeleton style={{ width: 48, height: 48, borderRadius: 'var(--radius)' }} />
        <div style={{ flex: 1 }}>
          <Skeleton variant="title" style={{ marginBottom: 'var(--space-1)' }} />
          <Skeleton variant="text-sm" width="14rem" style={{ marginBottom: 'var(--space-2)' }} />
          <Skeleton variant="badge" />
        </div>
      </div>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))',
          gap: 'var(--space-6)',
        }}
      >
        <SkeletonTable rows={4} columns={2} />
        <SkeletonTable rows={4} columns={2} />
      </div>
    </div>
  );
}
