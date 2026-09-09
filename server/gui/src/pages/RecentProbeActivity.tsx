import { useEffect, useMemo, useState } from 'react';
import {
  api,
  type ProbeCandidateGroup,
  type ProbeObservation,
  type RecentWifiProbesResponse,
} from '../api/client';
import { useFetch } from '../hooks/useFetch';
import { Badge, type BadgeVariant } from '../components/Badge';
import { Button } from '../components/Button';
import { DataTable, type Column } from '../components/DataTable';
import { MetricCard, SectionCard } from '../components/Card';
import { EmptyState, ErrorState, Notice, SkeletonTable } from '../components/States';
import { formatDateTime, normalizeMac } from '../utils/format';

const LOOKBACKS = ['5m', '15m', '30m', '1h', '4h', '24h', 'all'];

function mac(value: string | null) {
  return value ? normalizeMac(value) : '—';
}

function signalBadge(signal: number | null): BadgeVariant {
  if (signal === null) return 'muted';
  if (signal >= -55) return 'success';
  if (signal >= -70) return 'info';
  if (signal >= -80) return 'warning';
  return 'danger';
}

function download(name: string, text: string, type: string) {
  const blob = new Blob([text], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function RecentProbeActivityPage() {
  const [lookback, setLookback] = useState('15m');
  const [subtype, setSubtype] = useState<'all' | 'request' | 'response'>('all');
  const [randomized, setRandomized] = useState<'all' | 'true' | 'false'>('all');
  const [channel, setChannel] = useState('');
  const [bssid, setBssid] = useState('');
  const [minSignal, setMinSignal] = useState('');
  const [search, setSearch] = useState('');
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [selected, setSelected] = useState<ProbeObservation | null>(null);

  const fetchProbes = () => api.getRecentWifiProbes({
    lookback,
    subtype,
    randomized: randomized === 'all' ? undefined : randomized === 'true',
    channel: channel ? Number(channel) : undefined,
    bssid: bssid.trim() || undefined,
    min_signal: minSignal ? Number(minSignal) : undefined,
    limit: 700,
  });
  const { state, refetch } = useFetch<RecentWifiProbesResponse>(
    fetchProbes, [lookback, subtype, randomized, channel, bssid, minSignal],
  );
  const data = state.status === 'success' ? state.data : state.status === 'error' ? state.staleData : undefined;
  const probes = data?.observations ?? [];
  const groups = data?.candidate_groups ?? [];

  useEffect(() => {
    if (!autoRefresh) return undefined;
    const interval = window.setInterval(() => refetch(), 15_000);
    return () => window.clearInterval(interval);
  }, [autoRefresh, refetch]);

  const filteredProbes = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return probes;
    return probes.filter((probe) => [
      probe.source_mac, probe.destination_mac, probe.transmitter_mac, probe.bssid,
      probe.capture_file, probe.sensor, probe.frame_subtype, String(probe.channel ?? ''),
    ].some((value) => String(value ?? '').toLowerCase().includes(query)));
  }, [probes, search]);

  const filteredGroups = useMemo(() => groups.filter((group) => {
    const query = search.trim().toLowerCase();
    return !query || group.fingerprint_signature.includes(query) || group.mac_addresses.some((value) => value.toLowerCase().includes(query));
  }), [groups, search]);

  const exportJson = () => data && download(
    `kismet_recent_probes_${lookback}.json`, JSON.stringify({ ...data, observations: filteredProbes }, null, 2), 'application/json',
  );
  const exportCsv = () => {
    const headers = ['timestamp', 'subtype', 'source_mac', 'randomized', 'destination_mac', 'destination_kind', 'bssid', 'channel', 'signal_dbm', 'supported_rates_mbps', 'vendor_ouis', 'fingerprint_signature', 'capture_file'];
    const quote = (value: unknown) => `"${String(value ?? '').replace(/"/g, '""')}"`;
    const rows = filteredProbes.map((probe) => [
      probe.timestamp, probe.frame_subtype, probe.source_mac, probe.is_randomized_mac,
      probe.destination_mac, probe.destination_kind, probe.bssid, probe.channel, probe.signal_dbm,
      probe.supported_rates_mbps.join('|'), probe.vendor_ouis.join('|'), probe.fingerprint_signature, probe.capture_file,
    ].map(quote).join(','));
    download(`kismet_recent_probes_${lookback}.csv`, [headers.join(','), ...rows].join('\n'), 'text/csv;charset=utf-8');
  };

  const probeColumns: Column<ProbeObservation>[] = [
    {
      key: 'timestamp', label: 'Observed (UTC)', sortable: true,
      render: (item) => <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--font-xs)' }}>{formatDateTime(item.timestamp)}</span>,
    },
    {
      key: 'frame_subtype', label: 'Probe', sortable: true,
      render: (item) => <Badge variant={item.frame_subtype === 'Probe Request' ? 'info' : 'primary'}>{item.frame_subtype}</Badge>,
    },
    {
      key: 'source_mac', label: 'Source MAC', mono: true,
      render: (item) => <div><div>{mac(item.source_mac)}</div><Badge variant={item.is_randomized_mac ? 'warning' : 'muted'}>{item.is_randomized_mac ? 'Randomized' : 'Stable'}</Badge></div>,
    },
    {
      key: 'destination_mac', label: 'Destination / BSSID', mono: true,
      render: (item) => <div><div>{mac(item.destination_mac)} <span style={{ color: 'var(--text-muted)' }}>({item.destination_kind})</span></div><div style={{ color: 'var(--text-muted)' }}>BSSID: {mac(item.bssid)}</div></div>,
    },
    {
      key: 'channel', label: 'RF', sortable: true,
      render: (item) => <div><div>Ch {item.channel ?? '—'}</div><Badge variant={signalBadge(item.signal_dbm)}>{item.signal_dbm === null ? 'RSSI —' : `${item.signal_dbm} dBm`}</Badge></div>,
    },
    {
      key: 'fingerprint_signature', label: 'Candidate Signature', mono: true,
      render: (item) => <code>{item.fingerprint_signature}</code>,
    },
    {
      key: 'capture_file', label: 'Capture',
      render: (item) => <div><div>{item.sensor}</div><small style={{ color: 'var(--text-muted)' }}>{item.capture_file}</small></div>,
    },
  ];
  const groupColumns: Column<ProbeCandidateGroup>[] = [
    { key: 'fingerprint_signature', label: 'Candidate Signature', mono: true, render: (item) => <code>{item.fingerprint_signature}</code> },
    { key: 'probe_count', label: 'Probes', align: 'right', sortable: true },
    { key: 'unique_mac_count', label: 'MACs', align: 'right', sortable: true },
    { key: 'mac_addresses', label: 'Observed MACs', mono: true, render: (item) => item.mac_addresses.map(normalizeMac).join(', ') || '—' },
    { key: 'channels', label: 'Channels', render: (item) => item.channels.map((value) => `Ch ${value}`).join(', ') || '—' },
    { key: 'last_seen', label: 'Last Seen', render: (item) => formatDateTime(item.last_seen) },
  ];

  return (
    <div className="page-container">
      <div className="page-header">
        <div><p className="eyebrow">KISMET MONITOR-MODE SENSOR</p><h1 className="page-title">Recent Probe Activity</h1><p className="page-subtitle">Decoded Probe Requests and Responses from all observed MAC addresses. Candidate groups are similarities, not confirmed identities.</p></div>
        <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center' }}>
          <Button variant="quiet" size="sm" onClick={() => setAutoRefresh((value) => !value)}>{autoRefresh ? 'Auto-refresh: on' : 'Auto-refresh: off'}</Button>
          <Button variant="secondary" size="sm" onClick={() => refetch()}>Refresh</Button>
        </div>
      </div>

      <SectionCard title="Probe Filters" headerAction={<span style={{ color: 'var(--text-muted)', fontSize: 'var(--font-xs)' }}>Raw frame bytes and plaintext SSIDs are never displayed.</span>}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-3)', alignItems: 'end' }}>
          <label>Lookback<select value={lookback} onChange={(event) => setLookback(event.target.value)}>{LOOKBACKS.map((value) => <option key={value}>{value}</option>)}</select></label>
          <label>Subtype<select value={subtype} onChange={(event) => setSubtype(event.target.value as typeof subtype)}><option value="all">All probes</option><option value="request">Probe Request</option><option value="response">Probe Response</option></select></label>
          <label>MAC mode<select value={randomized} onChange={(event) => setRandomized(event.target.value as typeof randomized)}><option value="all">All MACs</option><option value="true">Randomized only</option><option value="false">Stable only</option></select></label>
          <label>Channel<input value={channel} onChange={(event) => setChannel(event.target.value)} inputMode="numeric" placeholder="e.g. 1" /></label>
          <label>BSSID<input value={bssid} onChange={(event) => setBssid(event.target.value)} placeholder="AA:BB:CC:DD:EE:FF" /></label>
          <label>Minimum RSSI<input value={minSignal} onChange={(event) => setMinSignal(event.target.value)} inputMode="numeric" placeholder="e.g. -75" /></label>
          <label style={{ flex: 1, minWidth: 210 }}>Search<input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="MAC, BSSID, channel, sensor…" /></label>
        </div>
      </SectionCard>

      {data && <div className="metric-grid" style={{ margin: 'var(--space-4) 0' }}>
        <MetricCard label="PROBES" value={data.summary.observation_count} context={`${data.summary.probe_request_count} requests · ${data.summary.probe_response_count} responses`} />
        <MetricCard label="RANDOMIZED MACS" value={data.summary.randomized_source_mac_count} valueVariant={data.summary.randomized_source_mac_count ? 'warning' : 'default'} context={`${data.summary.unique_source_mac_count} unique sources`} />
        <MetricCard label="CANDIDATE GROUPS" value={data.summary.candidate_group_count} context="MAC-independent feature signatures" />
        <MetricCard label="CHANNELS" value={data.summary.channels.length ? data.summary.channels.map((value) => `Ch ${value}`).join(', ') : '—'} context={`${data.capture_files_scanned} capture file(s) scanned`} />
      </div>}

      {data?.rejected_captures && Object.keys(data.rejected_captures).length > 0 && (
        <Notice variant="warning" title="Some Kismet captures were skipped">
          {Object.entries(data.rejected_captures).map(([file, reason]) => <div key={file}><code>{file}</code>: {reason}</div>)}
        </Notice>
      )}
      {data?.degraded_captures && Object.keys(data.degraded_captures).length > 0 && (
        <Notice variant="warning" title="Live Kismet capture is a committed snapshot">
          {Object.entries(data.degraded_captures).map(([file, reason]) => <div key={file}><code>{file}</code>: {reason}</div>)}
        </Notice>
      )}
      {data?.truncated_captures && Object.keys(data.truncated_captures).length > 0 && (
        <Notice variant="warning" title="Probe scan safety limit reached">
          {Object.entries(data.truncated_captures).map(([file, reason]) => <div key={file}><code>{file}</code>: {reason}</div>)}
        </Notice>
      )}

      <SectionCard title="Latest Probe Frames" headerAction={<div style={{ display: 'flex', gap: 'var(--space-2)' }}><Button size="sm" variant="quiet" onClick={exportJson} disabled={!data}>JSON</Button><Button size="sm" variant="quiet" onClick={exportCsv} disabled={!probes.length}>CSV</Button></div>}>
        {state.status === 'loading' && !data ? <SkeletonTable rows={8} columns={7} /> : state.status === 'error' && !data ? <ErrorState title="Unable to query Kismet probes" message={state.error.message} onRetry={() => refetch()} /> : filteredProbes.length ? <DataTable columns={probeColumns} data={filteredProbes} rowKey={(item) => item.observation_id} onRowClick={setSelected} aria-label="Recent Kismet probe observations" /> : <EmptyState icon="📡" title="No probes in this window" body="Kismet may be capturing on another channel, the selected filter may be too narrow, or no client scanned during the selected period." />}
      </SectionCard>

      <SectionCard title="Candidate Fingerprint Groups">
        {filteredGroups.length ? <DataTable columns={groupColumns} data={filteredGroups} rowKey={(item) => item.fingerprint_signature} aria-label="Candidate probe fingerprint groups" /> : <EmptyState icon="◌" title="No candidate groups" body="Groups appear when probe frames match on information-element and capability features." />}
      </SectionCard>

      {selected && <SectionCard title="Decoded Probe Metadata" headerAction={<Button size="sm" variant="quiet" onClick={() => setSelected(null)}>Close</Button>}>
        <pre style={{ margin: 0, overflowX: 'auto', whiteSpace: 'pre-wrap', fontSize: 'var(--font-xs)' }}>{JSON.stringify(selected, null, 2)}</pre>
      </SectionCard>}
    </div>
  );
}
