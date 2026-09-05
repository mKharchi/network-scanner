import { useState, useMemo, useEffect } from 'react';
import {
  api,
  type WirelessObservation,
  type DeviceWirelessObservationsResponse,
} from '../api/client';
import { useFetch } from '../hooks/useFetch';
import { SectionCard } from './Card';
import { Button } from './Button';
import { Badge, type BadgeVariant } from './Badge';
import { DataTable, type Column } from './DataTable';
import { SkeletonTable, ErrorState, EmptyState, Notice } from './States';
import { formatDateTime, normalizeMac } from '../utils/format';

interface WirelessInvestigationPanelProps {
  deviceMac: string;
  initialLookback?: string;
  initialStart?: string;
  initialEnd?: string;
}

const LOOKBACK_OPTIONS = [
  { label: 'Last 15 Minutes (Default)', value: '15m' },
  { label: 'Last 30 Minutes', value: '30m' },
  { label: 'Last 1 Hour', value: '1h' },
  { label: 'Last 4 Hours', value: '4h' },
  { label: 'Last 24 Hours', value: '24h' },
  { label: 'Custom Range', value: 'custom' },
];

function getRssiQuality(rssi: number | null): { label: string; variant: BadgeVariant } {
  if (rssi === null) return { label: 'Unknown', variant: 'muted' };
  if (rssi >= -55) return { label: 'Excellent', variant: 'success' };
  if (rssi >= -68) return { label: 'Good', variant: 'info' };
  if (rssi >= -78) return { label: 'Fair', variant: 'warning' };
  return { label: 'Weak', variant: 'danger' };
}

function getFrameBadgeVariant(frameType: string): BadgeVariant {
  const t = frameType.toLowerCase();
  if (t.includes('data')) return 'primary';
  if (t.includes('mgmt') || t.includes('management')) return 'info';
  if (t.includes('ctrl') || t.includes('control')) return 'warning';
  return 'muted';
}

function getRoleBadgeVariant(role: string): BadgeVariant {
  switch (role) {
    case 'SOURCE':
      return 'success';
    case 'TRANSMITTER':
      return 'primary';
    case 'DESTINATION':
      return 'info';
    default:
      return 'muted';
  }
}

export function WirelessInvestigationPanel({
  deviceMac,
  initialLookback = '15m',
  initialStart,
  initialEnd,
}: WirelessInvestigationPanelProps) {
  const [lookback, setLookback] = useState<string>(initialStart || initialEnd ? 'custom' : initialLookback);
  const [customStart, setCustomStart] = useState<string>(initialStart || '');
  const [customEnd, setCustomEnd] = useState<string>(initialEnd || '');
  const [includeNoise, setIncludeNoise] = useState<boolean>(false);
  const [limit, setLimit] = useState<number>(500);

  // Client-side filtering
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [selectedRole, setSelectedRole] = useState<string>('ALL');
  const [selectedFrameType, setSelectedFrameType] = useState<string>('ALL');

  useEffect(() => {
    if (initialStart || initialEnd) {
      setLookback('custom');
      if (initialStart) setCustomStart(initialStart);
      if (initialEnd) setCustomEnd(initialEnd);
    } else if (initialLookback) {
      setLookback(initialLookback);
    }
  }, [initialLookback, initialStart, initialEnd]);

  const fetchObservations = () => {
    if (!deviceMac) return Promise.reject(new Error('No MAC address provided.'));
    const isCustom = lookback === 'custom';
    return api.getDeviceWirelessObservations(deviceMac, {
      lookback: !isCustom ? lookback : undefined,
      start: isCustom && customStart ? customStart : undefined,
      end: isCustom && customEnd ? customEnd : undefined,
      include_noise: includeNoise,
      limit,
    });
  };

  const { state, refetch } = useFetch<DeviceWirelessObservationsResponse>(
    deviceMac ? fetchObservations : null,
    [deviceMac, lookback, customStart, customEnd, includeNoise, limit]
  );

  const data: DeviceWirelessObservationsResponse | undefined =
    state.status === 'success' ? state.data : state.status === 'error' ? state.staleData : undefined;
  const observations: WirelessObservation[] = data?.observations ?? [];
  const summary = data?.summary;
  const queryWindow = data?.query_window;

  // Filter observations based on search & selectors
  const filteredObservations = useMemo(() => {
    return observations.filter((obs: WirelessObservation) => {
      if (selectedRole !== 'ALL' && obs.role !== selectedRole) {
        return false;
      }
      if (selectedFrameType !== 'ALL') {
        const ft = `${obs.frame_type}: ${obs.frame_subtype}`;
        if (!ft.toLowerCase().includes(selectedFrameType.toLowerCase()) && !obs.frame_type.toLowerCase().includes(selectedFrameType.toLowerCase())) {
          return false;
        }
      }
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchMac =
          obs.source_mac.toLowerCase().includes(q) ||
          obs.destination_mac.toLowerCase().includes(q) ||
          obs.transmitter_mac.toLowerCase().includes(q);
        const matchFrame =
          obs.frame_type.toLowerCase().includes(q) ||
          obs.frame_subtype.toLowerCase().includes(q);
        const matchSensor = obs.sensor.toLowerCase().includes(q) || obs.capture_file.toLowerCase().includes(q);
        const matchChannel = String(obs.channel).includes(q);
        if (!matchMac && !matchFrame && !matchSensor && !matchChannel) {
          return false;
        }
      }
      return true;
    });
  }, [observations, selectedRole, selectedFrameType, searchQuery]);

  const exportToJson = () => {
    if (!data) return;
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `kismet_investigation_${normalizeMac(deviceMac)}_${lookback}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const exportToCsv = () => {
    if (!observations.length) return;
    const headers = [
      'timestamp',
      'role',
      'frame_type',
      'frame_subtype',
      'signal_dbm',
      'channel',
      'frequency_khz',
      'packet_length',
      'source_mac',
      'destination_mac',
      'transmitter_mac',
      'sensor',
      'capture_file',
      'packet_hash',
    ];
    const rows = observations.map((o: WirelessObservation) => [
      `"${o.timestamp}"`,
      `"${o.role}"`,
      `"${o.frame_type}"`,
      `"${o.frame_subtype}"`,
      o.signal_dbm ?? '',
      o.channel ?? '',
      o.frequency_khz ?? '',
      o.packet_length,
      `"${o.source_mac}"`,
      `"${o.destination_mac}"`,
      `"${o.transmitter_mac}"`,
      `"${o.sensor}"`,
      `"${o.capture_file}"`,
      `"${o.packet_hash}"`,
    ]);
    const csvContent = [headers.join(','), ...rows.map((r: (string | number)[]) => r.join(','))].join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `kismet_observations_${normalizeMac(deviceMac)}_${lookback}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const columns: Column<WirelessObservation>[] = [
    {
      key: 'timestamp',
      label: 'Observed Time (UTC)',
      render: (item) => (
        <div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--font-xs)', fontWeight: 600 }}>
            {formatDateTime(item.timestamp)}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
            +{String(item.epoch_usec).padStart(6, '0')} µs
          </div>
        </div>
      ),
    },
    {
      key: 'role',
      label: 'Role',
      render: (item) => (
        <Badge variant={getRoleBadgeVariant(item.role)}>
          {item.role}
        </Badge>
      ),
    },
    {
      key: 'frame',
      label: '802.11 Frame Type',
      render: (item) => (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-1)' }}>
            <Badge variant={getFrameBadgeVariant(item.frame_type)}>
              {item.frame_type}
            </Badge>
            <span style={{ fontSize: 'var(--font-xs)', fontWeight: 500 }}>
              {item.frame_subtype}
            </span>
          </div>
        </div>
      ),
    },
    {
      key: 'signal_dbm',
      label: 'Signal (RSSI)',
      align: 'right',
      render: (item) => {
        if (item.signal_dbm === null) {
          return <span style={{ color: 'var(--text-faint)' }}>—</span>;
        }
        const qual = getRssiQuality(item.signal_dbm);
        return (
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-1)' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--font-xs)', fontWeight: 600 }}>
              {item.signal_dbm} dBm
            </span>
            <Badge variant={qual.variant} dot>
              {qual.label}
            </Badge>
          </div>
        );
      },
    },
    {
      key: 'channel',
      label: 'Channel & Freq',
      render: (item) => (
        <div>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--font-xs)', fontWeight: 600 }}>
            {item.channel ? `Ch ${item.channel}` : '—'}
          </span>
          {item.frequency_khz && (
            <span style={{ fontSize: '11px', color: 'var(--text-muted)', marginLeft: 'var(--space-1)' }}>
              ({(item.frequency_khz / 1000).toFixed(0)} MHz)
            </span>
          )}
        </div>
      ),
    },
    {
      key: 'packet_length',
      label: 'Length',
      align: 'right',
      render: (item) => (
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--font-xs)' }}>
          {item.packet_length.toLocaleString()} B
        </span>
      ),
    },
    {
      key: 'addresses',
      label: 'Correlated MACs',
      mono: true,
      render: (item) => (
        <div style={{ fontSize: '11px', lineHeight: 1.3 }}>
          {item.role !== 'SOURCE' && (
            <div><span style={{ color: 'var(--text-muted)' }}>Src:</span> {normalizeMac(item.source_mac)}</div>
          )}
          {item.role !== 'DESTINATION' && (
            <div><span style={{ color: 'var(--text-muted)' }}>Dst:</span> {normalizeMac(item.destination_mac)}</div>
          )}
          {item.transmitter_mac && item.transmitter_mac !== item.source_mac && (
            <div><span style={{ color: 'var(--text-muted)' }}>Tx:</span> {normalizeMac(item.transmitter_mac)}</div>
          )}
        </div>
      ),
    },
    {
      key: 'sensor',
      label: 'Sensor / Capture',
      render: (item) => (
        <div style={{ fontSize: '11px' }}>
          <div style={{ fontWeight: 500 }}>{item.sensor}</div>
          <div style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }} title={item.capture_file}>
            {item.capture_file}
          </div>
        </div>
      ),
    },
  ];

  return (
    <SectionCard title="Kismet Passive Wireless Investigation">
      {/* Search and Time Range Toolbar */}
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: 'var(--space-3)',
          alignItems: 'center',
          justifyContent: 'space-between',
          paddingBottom: 'var(--space-4)',
          borderBottom: '1px solid var(--border)',
          marginBottom: 'var(--space-4)',
        }}
      >
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-3)', alignItems: 'center' }}>
          <div>
            <label
              htmlFor="investigation-lookback"
              style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', display: 'block', marginBottom: '4px', fontWeight: 500 }}
            >
              Time Window:
            </label>
            <select
              id="investigation-lookback"
              value={lookback}
              onChange={(e) => setLookback(e.target.value)}
              style={{
                padding: '6px 12px',
                borderRadius: 'var(--radius)',
                border: '1px solid var(--border)',
                background: 'var(--surface-input)',
                color: 'var(--text-primary)',
                fontSize: 'var(--font-sm)',
              }}
            >
              {LOOKBACK_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          {lookback === 'custom' && (
            <>
              <div>
                <label
                  htmlFor="custom-start-time"
                  style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', display: 'block', marginBottom: '4px', fontWeight: 500 }}
                >
                  Start Time (UTC / ISO):
                </label>
                <input
                  id="custom-start-time"
                  type="text"
                  placeholder="2026-09-05T12:00:00Z"
                  value={customStart}
                  onChange={(e) => setCustomStart(e.target.value)}
                  style={{
                    padding: '6px 10px',
                    borderRadius: 'var(--radius)',
                    border: '1px solid var(--border)',
                    background: 'var(--surface-input)',
                    color: 'var(--text-primary)',
                    fontSize: 'var(--font-sm)',
                    fontFamily: 'var(--font-mono)',
                    width: '190px',
                  }}
                />
              </div>
              <div>
                <label
                  htmlFor="custom-end-time"
                  style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', display: 'block', marginBottom: '4px', fontWeight: 500 }}
                >
                  End Time (UTC / ISO):
                </label>
                <input
                  id="custom-end-time"
                  type="text"
                  placeholder="2026-09-05T15:00:00Z"
                  value={customEnd}
                  onChange={(e) => setCustomEnd(e.target.value)}
                  style={{
                    padding: '6px 10px',
                    borderRadius: 'var(--radius)',
                    border: '1px solid var(--border)',
                    background: 'var(--surface-input)',
                    color: 'var(--text-primary)',
                    fontSize: 'var(--font-sm)',
                    fontFamily: 'var(--font-mono)',
                    width: '190px',
                  }}
                />
              </div>
            </>
          )}

          <div>
            <label
              htmlFor="investigation-limit"
              style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', display: 'block', marginBottom: '4px', fontWeight: 500 }}
            >
              Max Observations:
            </label>
            <select
              id="investigation-limit"
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
              style={{
                padding: '6px 12px',
                borderRadius: 'var(--radius)',
                border: '1px solid var(--border)',
                background: 'var(--surface-input)',
                color: 'var(--text-primary)',
                fontSize: 'var(--font-sm)',
              }}
            >
              <option value={100}>100 frames</option>
              <option value={250}>250 frames</option>
              <option value={500}>500 frames</option>
              <option value={1000}>1000 frames</option>
            </select>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', marginTop: '18px' }}>
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: 'var(--font-sm)', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={includeNoise}
                onChange={(e) => setIncludeNoise(e.target.checked)}
              />
              Include Noise (ACK/CTS Control Frames)
            </label>
          </div>
        </div>

        <div style={{ display: 'flex', gap: 'var(--space-2)', marginTop: 'auto' }}>
          <Button variant="secondary" size="sm" onClick={() => refetch()}>
            Query Observations
          </Button>
          {observations.length > 0 && (
            <>
              <Button variant="quiet" size="sm" onClick={exportToCsv} title="Export CSV table">
                Export CSV
              </Button>
              <Button variant="quiet" size="sm" onClick={exportToJson} title="Export full JSON payload">
                Export JSON
              </Button>
            </>
          )}
        </div>
      </div>

      {/* Query Window & Stale Warning */}
      {state.status === 'error' && (
        <Notice variant="warning" title="Failed to refresh wireless observations">
          {state.error.message}
        </Notice>
      )}

      {/* RF Summary Metric Cards */}
      {summary && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
            gap: 'var(--space-3)',
            marginBottom: 'var(--space-4)',
          }}
        >
          <div className="device-detail-stat">
            <span className="eyebrow">OBSERVATION FRAMES</span>
            <strong>{summary.observation_count.toLocaleString()}</strong>
            <span>
              {queryWindow ? `${queryWindow.lookback_minutes}m lookback (${formatDateTime(queryWindow.start)} → ${formatDateTime(queryWindow.end)})` : 'Time range'}
            </span>
          </div>

          <div className="device-detail-stat">
            <span className="eyebrow">AVG SIGNAL STRENGTH</span>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 'var(--space-2)' }}>
              <strong>{summary.avg_signal_dbm !== null ? `${summary.avg_signal_dbm} dBm` : '—'}</strong>
              {summary.avg_signal_dbm !== null && (
                <Badge variant={getRssiQuality(summary.avg_signal_dbm).variant} dot>
                  {getRssiQuality(summary.avg_signal_dbm).label}
                </Badge>
              )}
            </div>
            <span>
              {summary.min_signal_dbm !== null && summary.max_signal_dbm !== null
                ? `Range: ${summary.min_signal_dbm} dBm to ${summary.max_signal_dbm} dBm`
                : 'No RSSI telemetry'}
            </span>
          </div>

          <div className="device-detail-stat">
            <span className="eyebrow">ACTIVE CHANNELS</span>
            <strong>{summary.channels.length ? `Ch ${summary.channels.join(', ')}` : 'None'}</strong>
            <span>
              {summary.channels.some((c: number) => c > 14) ? 'Dual-Band (2.4 GHz + 5 GHz)' : summary.channels.length ? '2.4 GHz Band' : 'No RF channel data'}
            </span>
          </div>

          <div className="device-detail-stat">
            <span className="eyebrow">NOISE FILTERING</span>
            <strong>{summary.noise_filtered ? 'FILTERED' : 'UNFILTERED'}</strong>
            <span>{summary.noise_filtered ? 'Control ACKs/CTSs omitted' : 'Full frame capture'}</span>
          </div>
        </div>
      )}

      {/* Frame Subtype breakdown chips */}
      {summary && Object.keys(summary.frame_types).length > 0 && (
        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            alignItems: 'center',
            gap: 'var(--space-2)',
            padding: 'var(--space-2) var(--space-3)',
            background: 'var(--surface-subtle)',
            borderRadius: 'var(--radius)',
            marginBottom: 'var(--space-4)',
          }}
        >
          <span style={{ fontSize: 'var(--font-xs)', fontWeight: 600, color: 'var(--text-muted)' }}>
            Frame Breakdown:
          </span>
          <button
            type="button"
            onClick={() => setSelectedFrameType('ALL')}
            style={{
              all: 'unset',
              cursor: 'pointer',
            }}
          >
            <Badge variant={selectedFrameType === 'ALL' ? 'primary' : 'muted'}>
              All ({summary.observation_count})
            </Badge>
          </button>
          {Object.entries(summary.frame_types).map(([ft, count]) => {
            const isSelected = selectedFrameType.toLowerCase() === ft.toLowerCase();
            return (
              <button
                key={ft}
                type="button"
                onClick={() => setSelectedFrameType(isSelected ? 'ALL' : ft)}
                style={{
                  all: 'unset',
                  cursor: 'pointer',
                }}
                title={`Filter by ${ft}`}
              >
                <Badge variant={isSelected ? 'success' : 'info'}>
                  {ft}: {String(count)}
                </Badge>
              </button>
            );
          })}
        </div>
      )}

      {/* Client-side filter bar */}
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: 'var(--space-3)',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 'var(--space-3)',
        }}
      >
        <div style={{ display: 'flex', gap: 'var(--space-2)', flex: 1, minWidth: '240px' }}>
          <input
            type="text"
            placeholder="Filter by MAC, Frame, Channel, Sensor..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            style={{
              flex: 1,
              padding: '6px 10px',
              borderRadius: 'var(--radius)',
              border: '1px solid var(--border)',
              background: 'var(--surface-input)',
              color: 'var(--text-primary)',
              fontSize: 'var(--font-sm)',
            }}
          />
        </div>

        <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center' }}>
          <label
            htmlFor="investigation-role-filter"
            style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', fontWeight: 500 }}
          >
            Role:
          </label>
          <select
            id="investigation-role-filter"
            value={selectedRole}
            onChange={(e) => setSelectedRole(e.target.value)}
            style={{
              padding: '4px 8px',
              borderRadius: 'var(--radius)',
              border: '1px solid var(--border)',
              background: 'var(--surface-input)',
              color: 'var(--text-primary)',
              fontSize: 'var(--font-xs)',
            }}
          >
            <option value="ALL">All Roles</option>
            <option value="SOURCE">SOURCE</option>
            <option value="TRANSMITTER">TRANSMITTER</option>
            <option value="DESTINATION">DESTINATION</option>
          </select>
        </div>
      </div>

      {/* Observations Timeline Table */}
      {state.status === 'loading' && !data ? (
        <SkeletonTable rows={5} columns={6} />
      ) : state.status === 'error' && !data ? (
        <ErrorState
          title="Unable to query wireless observations"
          message={state.error.message}
          onRetry={() => refetch()}
        />
      ) : filteredObservations.length === 0 ? (
        <EmptyState
          icon="📡"
          title={observations.length === 0 ? 'No wireless observations in time window' : 'No observations match your filters'}
          body={
            observations.length === 0
              ? `No 802.11 frames observed for MAC ${normalizeMac(deviceMac)} in the selected lookback period (${lookback}). Try expanding the time window or checking another active capture.`
              : 'Try clearing the search query or resetting the role/frame filters.'
          }
        />
      ) : (
        <DataTable
          columns={columns}
          data={filteredObservations}
          rowKey={(obs, idx) => `${obs.packet_hash}-${obs.epoch_sec}-${obs.epoch_usec}-${idx}`}
          aria-label="Kismet wireless observations"
        />
      )}
    </SectionCard>
  );
}
