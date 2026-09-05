import { useLocation, useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import { useFetch } from '../hooks/useFetch';
import { ClassificationBadge } from '../components/Badge';
import { Button } from '../components/Button';
import { SectionCard } from '../components/Card';
import { Skeleton, SkeletonTable, ErrorState, EmptyState, Notice } from '../components/States';
import { DataTable, type Column } from '../components/DataTable';
import { Badge } from '../components/Badge';
import { WirelessInvestigationPanel } from '../components/WirelessInvestigationPanel';
import { formatDateTime, formatRelative, normalizeMac } from '../utils/format';
import '../styles/devices.css';
import '../styles/device-detail.css';

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
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const returnTo = typeof location.state?.from === "string" ? location.state.from : "/network/latest";
  const returnLabel = typeof location.state?.label === "string" ? location.state.label : "Latest Scan";

  const activeTab = searchParams.get('tab') || 'overview';
  const lookbackParam = searchParams.get('lookback') || '15m';
  const startParam = searchParams.get('start') || undefined;
  const endParam = searchParams.get('end') || undefined;

  const handleTabChange = (tab: string) => {
    const nextParams = new URLSearchParams(searchParams);
    nextParams.set('tab', tab);
    setSearchParams(nextParams);
  };

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
        <Button variant="quiet" size="sm" onClick={() => navigate(returnTo)}>
          ← {returnLabel}
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

      <div className="device-detail-hero">
        <div className="device-detail-hero__identity">
          <div className="device-detail-icon" aria-hidden="true">{dev.is_managed ? '◈' : '◌'}</div>
          <div>
            <span className="eyebrow eyebrow--accent">DEVICE INTELLIGENCE</span>
            <h1 className="device-detail-title">{dev.hostname || normalizeMac(dev.mac_address)}</h1>
            <p className="device-detail-subtitle">{dev.vendor || 'Unknown vendor'} · {dev.ip_address || 'No IP address recorded'}</p>
            <div className="device-detail-badges">
              <ClassificationBadge managed={dev.is_managed} />
              <Badge variant={dev.last_observed_at ? 'success' : 'muted'} dot>{dev.last_observed_at ? 'Observed' : 'No recent observation'}</Badge>
              {dev.os.name && <Badge variant="info">{dev.os.name}</Badge>}
            </div>
          </div>
        </div>
        <div className="device-detail-hero__meta">
          <span className="eyebrow">LAST SEEN</span>
          <strong>{formatRelative(dev.last_observed_at)}</strong>
          <span>{formatDateTime(dev.last_observed_at)}</span>
        </div>
      </div>

      <div className="device-detail-stat-grid">
        <div className="device-detail-stat"><span className="eyebrow">DISCOVERY SOURCES</span><strong>{dev.sources.length}</strong><span>{dev.sources.length ? dev.sources.join(' · ') : 'None recorded'}</span></div>
        <div className="device-detail-stat"><span className="eyebrow">OBSERVATIONS</span><strong>{d.observations.length}</strong><span>Recorded evidence events</span></div>
        <div className="device-detail-stat"><span className="eyebrow">OS CONFIDENCE</span><strong>{dev.os.confidence !== null ? `${Math.round(dev.os.confidence * 100)}%` : '—'}</strong><span>{dev.os.family || 'Classification unavailable'}</span></div>
        <div className="device-detail-stat"><span className="eyebrow">MANAGED LINK</span><strong>{dev.is_managed ? 'YES' : 'NO'}</strong><span>{dev.managed_client_id || 'No client linked'}</span></div>
      </div>

      {/* Navigation Tabs */}
      <div
        style={{
          display: 'flex',
          gap: 'var(--space-2)',
          marginBottom: 'var(--space-5)',
          borderBottom: '1px solid var(--border)',
          paddingBottom: 'var(--space-3)',
          flexWrap: 'wrap',
        }}
      >
        <Button
          variant={activeTab === 'overview' ? 'primary' : 'quiet'}
          size="sm"
          onClick={() => handleTabChange('overview')}
        >
          Overview & Identity
        </Button>
        <Button
          variant={activeTab === 'network' ? 'primary' : 'quiet'}
          size="sm"
          onClick={() => handleTabChange('network')}
        >
          Network Intelligence & Telemetry
        </Button>
        <Button
          variant={activeTab === 'investigation' ? 'primary' : 'quiet'}
          size="sm"
          onClick={() => handleTabChange('investigation')}
        >
          📡 Kismet Wireless Investigation
        </Button>
      </div>

      {/* Tab 1: Overview & Identity */}
      {activeTab === 'overview' && (
        <>
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

          <SectionCard title="Wireless RF Evidence & Passive Capture">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 'var(--space-4)' }}>
              <div>
                <div style={{ fontWeight: 600, fontSize: 'var(--font-base)', marginBottom: '4px' }}>
                  Kismet Passive 802.11 Wireless Capture Available
                </div>
                <div style={{ color: 'var(--text-muted)', fontSize: 'var(--font-sm)' }}>
                  Inspect historical 802.11 frames, RSSI signal levels, channels, and probe activity captured for MAC {normalizeMac(dev.mac_address)}.
                </div>
              </div>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => handleTabChange('investigation')}
              >
                Launch Wireless Investigation (15m Lookback) →
              </Button>
            </div>
          </SectionCard>
        </>
      )}

      {/* Tab 2: Network Intelligence & Telemetry */}
      {activeTab === 'network' && (
        <>
          {(() => {
            const sni: string[] = dev.sni_domains ?? [];
            const dns: string[] = dev.dns_queries ?? [];
            const ja3: string[] = dev.ja3_hashes ?? [];
            const asns: Array<{ provider: string; description: string; destination_ip?: string; count: number }> =
              dev.destination_asns ?? [];
            const traffic = dev.traffic_profile ?? {};
            const hasIntel = sni.length > 0 || dns.length > 0 || ja3.length > 0 || asns.length > 0 || traffic.behavioral_pattern;
            if (!hasIntel) return null;
            return (
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))",
                  gap: "var(--space-6)",
                  marginBottom: "var(--space-6)",
                }}
              >
                {sni.length > 0 && (
                  <SectionCard title="TLS / SNI Hostnames">
                    <ul style={{ margin: 0, padding: "0 0 0 var(--space-4)", listStyle: "disc" }}>
                      {sni.map((d) => (
                        <li key={d} style={{ fontSize: "var(--font-sm)", fontFamily: "var(--font-mono)", padding: "2px 0" }}>
                          {d}
                        </li>
                      ))}
                    </ul>
                  </SectionCard>
                )}

                {dns.length > 0 && (
                  <SectionCard title="Passive DNS Queries">
                    <ul style={{ margin: 0, padding: "0 0 0 var(--space-4)", listStyle: "disc" }}>
                      {dns.map((d) => (
                        <li key={d} style={{ fontSize: "var(--font-sm)", fontFamily: "var(--font-mono)", padding: "2px 0" }}>
                          {d}
                        </li>
                      ))}
                    </ul>
                  </SectionCard>
                )}

                {ja3.length > 0 && (
                  <SectionCard title="JA3 TLS Fingerprints">
                    {ja3.map((h) => (
                      <div
                        key={h}
                        style={{
                          fontFamily: "var(--font-mono)",
                          fontSize: "var(--font-xs)",
                          padding: "var(--space-1) 0",
                          borderBottom: "1px solid var(--border-subtle)",
                          wordBreak: "break-all",
                        }}
                      >
                        {h}
                      </div>
                    ))}
                  </SectionCard>
                )}

                {asns.length > 0 && (
                  <SectionCard title="Cloud / ASN Destinations">
                    {asns.map((a) => (
                      <div
                        key={a.provider}
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "baseline",
                          padding: "var(--space-1) 0",
                          borderBottom: "1px solid var(--border-subtle)",
                          fontSize: "var(--font-sm)",
                        }}
                      >
                        <span style={{ fontWeight: 600 }}>{a.provider}</span>
                        <span style={{ color: "var(--text-muted)", fontSize: "var(--font-xs)" }}>
                          {a.description} · {a.count}×
                        </span>
                      </div>
                    ))}
                  </SectionCard>
                )}

                {traffic.behavioral_pattern && (
                  <SectionCard title="Traffic Profile">
                    <div>
                      <DetailRow label="Pattern" value={traffic.behavioral_pattern} />
                      {traffic.bytes_per_window != null && (
                        <DetailRow label="Bytes / min" value={traffic.bytes_per_window.toLocaleString()} />
                      )}
                      {traffic.packets_per_window != null && (
                        <DetailRow label="Packets / min" value={traffic.packets_per_window} />
                      )}
                      {traffic.avg_interval_sec != null && (
                        <DetailRow label="Avg interval" value={`${traffic.avg_interval_sec}s`} />
                      )}
                    </div>
                  </SectionCard>
                )}
              </div>
            );
          })()}

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
        </>
      )}

      {/* Tab 3: Kismet Wireless Investigation */}
      {activeTab === 'investigation' && dev.mac_address && (
        <WirelessInvestigationPanel
          deviceMac={dev.mac_address}
          initialLookback={lookbackParam}
          initialStart={startParam}
          initialEnd={endParam}
        />
      )}
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
