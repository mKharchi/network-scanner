import React, { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api, type ClientPassiveNeighbourhood } from '../api/client';
import { useFetch } from '../hooks/useFetch';
import { useToast } from '../hooks/useToast';
import { OnlineBadge, OfflineBadge, Badge } from '../components/Badge';
import { Button } from '../components/Button';
import { SectionCard, MetricCard } from '../components/Card';
import { Skeleton, ErrorState, Notice } from '../components/States';
import { formatDateTime, formatRelative } from '../utils/format';

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
      <span
        style={{
          fontSize: 'var(--font-xs)',
          color: 'var(--text-muted)',
          fontWeight: 500,
        }}
      >
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

interface ProcessItem {
  pid?: number;
  name?: string;
  username?: string;
  cpu_percent?: number;
  memory_percent?: number;
  status?: string;
  [key: string]: any;
}

export function ClientDetailPage() {
  const { clientId } = useParams<{ clientId: string }>();
  const navigate = useNavigate();
  const { addToast } = useToast();

  const [activeCommand, setActiveCommand] = useState<string | null>(null);
  const [commandLoading, setCommandLoading] = useState(false);
  const [commandResult, setCommandResult] = useState<any>(null);
  const [neighbourhoodLoading, setNeighbourhoodLoading] = useState(false);
  const [passiveNeighbourhoodLoading, setPassiveNeighbourhoodLoading] = useState(false);
  const [passiveNeighbourhood, setPassiveNeighbourhood] = useState<ClientPassiveNeighbourhood | null>(null);

  // Process management states
  const [processList, setProcessList] = useState<ProcessItem[] | null>(null);
  const [processFilter, setProcessFilter] = useState('');
  const [killingProcess, setKillingProcess] = useState<string | null>(null);

  // Start process modal
  const [showStartModal, setShowStartModal] = useState(false);
  const [startProcessPath, setStartProcessPath] = useState('');

  // Activity log period selector
  const [activityPeriod, setActivityPeriod] = useState<'1d' | '1w' | '1m'>('1d');

  const { state, refetch } = useFetch(
    clientId ? () => api.getClient(clientId) : null,
    [clientId],
    ['app:client_status'],
  );

  const executeCommand = async (command: string, args?: any) => {
    if (!clientId) return;
    setActiveCommand(command);
    setCommandLoading(true);

    try {
      const response = await api.runClientCommand(clientId, command, args);
      setCommandResult(response);

      if (command === 'GET_PROCESSES') {
        const rawData = response?.data;
        const list: ProcessItem[] = Array.isArray(rawData)
          ? rawData
          : Array.isArray(rawData?.processes)
            ? rawData.processes
            : [];
        setProcessList(list);
        addToast({
          title: 'Processes Retrieved',
          message: `Loaded ${list.length} running processes from ${clientId}.`,
          severity: 'INFO',
        });
      } else if (command === 'KILL_PROCESS') {
        addToast({
          title: 'Process Terminated',
          message: `Kill command issued for ${args}.`,
          severity: 'SUCCESS',
        });
        // Auto-refresh process list if already loaded
        if (processList) {
          executeCommand('GET_PROCESSES');
        }
      } else if (command === 'START_PROCESS') {
        addToast({
          title: 'Process Started',
          message: `Launched ${args} on client.`,
          severity: 'SUCCESS',
        });
        setShowStartModal(false);
        setStartProcessPath('');
      } else if (command === 'DISCONNECT') {
        addToast({
          title: 'Client Disconnected',
          message: `Client ${clientId} disconnected at server request.`,
          severity: 'LOW',
        });
        refetch();
      } else {
        addToast({
          title: 'Command Executed',
          message: `${command} completed successfully.`,
          severity: 'SUCCESS',
        });
      }
    } catch (err: any) {
      const msg = err?.message || 'Command failed';
      addToast({
        title: 'Command Error',
        message: msg,
        severity: 'CRITICAL',
      });
    } finally {
      setCommandLoading(false);
    }
  };

  const requestNeighbourhood = async () => {
    if (!clientId) return;
    setNeighbourhoodLoading(true);
    try {
      const result = await api.requestClientNeighbourhood(clientId);
      addToast({
        title: 'Neighbourhood collected',
        message: `Received ${result.observations_sent} stored observation(s) from ${c.hostname}.`,
        severity: 'SUCCESS',
      });
      refetch();
    } catch (err: any) {
      addToast({
        title: 'Neighbourhood request failed',
        message: err?.message || 'The client did not provide its stored neighbourhood.',
        severity: 'CRITICAL',
      });
    } finally {
      setNeighbourhoodLoading(false);
    }
  };

  const requestPassiveNeighbourhood = async () => {
    if (!clientId) return;
    setPassiveNeighbourhoodLoading(true);
    try {
      const result = await api.requestClientPassiveNeighbourhood(clientId);
      setPassiveNeighbourhood(result);
      const protocols = new Set(result.observations.map((observation) => observation.protocol));
      addToast({
        title: 'Passive information received',
        message: `Received ${result.observation_count} observation(s) across ${protocols.size} protocol(s) from ${c.hostname}.`,
        severity: 'SUCCESS',
      });
    } catch (err: any) {
      addToast({
        title: 'Passive information request failed',
        message: err?.message || 'The client did not provide passive network information.',
        severity: 'CRITICAL',
      });
    } finally {
      setPassiveNeighbourhoodLoading(false);
    }
  };

  if (state.status === 'idle' || state.status === 'loading') {
    return <ClientDetailSkeleton />;
  }

  if (state.status === 'error' && !state.staleData) {
    return (
      <ErrorState
        title="Unable to load client"
        message={state.error.message}
        onRetry={refetch}
      />
    );
  }

  const d = state.status === 'success' ? state.data : state.staleData!;
  const c = d.client;
  const isOnline = c.connection.state === 'ONLINE';

  const filteredProcesses = (processList || []).filter((p) => {
    if (!processFilter) return true;
    const term = processFilter.toLowerCase();
    return (
      (p.name && p.name.toLowerCase().includes(term)) ||
      (p.pid !== undefined && String(p.pid).includes(term)) ||
      (p.username && p.username.toLowerCase().includes(term))
    );
  });

  return (
    <div>
      {/* Top navigation */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--space-3)',
          marginBottom: 'var(--space-5)',
        }}
      >
        <Button variant="quiet" size="sm" onClick={() => navigate('/clients')}>
          ← Clients
        </Button>
        <Button variant="quiet" size="sm" onClick={refetch}>
          Refresh
        </Button>
      </div>

      {state.status === 'error' && (
        <Notice variant="warning" title="Stale data shown">
          {state.error.message}
        </Notice>
      )}

      {/* Header Banner */}
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
            background: isOnline ? 'var(--success-bg)' : 'var(--surface-muted)',
            border: '1px solid var(--border)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 22,
            flexShrink: 0,
          }}
          aria-hidden="true"
        >
          💻
        </div>
        <div>
          <h1
            style={{
              fontSize: 'var(--font-xl)',
              fontWeight: 600,
              marginBottom: 'var(--space-1)',
            }}
          >
            {c.hostname}
          </h1>
          <div
            style={{
              display: 'flex',
              gap: 'var(--space-2)',
              alignItems: 'center',
              flexWrap: 'wrap',
            }}
          >
            {isOnline ? <OnlineBadge /> : <OfflineBadge />}
            <span style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)' }}>
              {isOnline
                ? `Connected ${formatRelative(c.connection.last_connected_at)}`
                : `Last seen ${formatRelative(c.connection.last_connected_at)}`}
            </span>
          </div>
        </div>

        {/* Alert Metrics */}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 'var(--space-3)' }}>
          <MetricCard
            label="New alerts"
            value={d.alert_counts.new}
            valueVariant={d.alert_counts.new > 0 ? 'danger' : 'default'}
          />
          <MetricCard label="Total alerts" value={d.alert_counts.total} />
        </div>
      </div>

      {/* Interactive Command Control Center */}
      <SectionCard title="Agent Remote Control & Telemetry">
        {!isOnline && (
          <div style={{ marginBottom: 'var(--space-3)' }}>
            <Notice variant="info" title="Client is offline">
              Agent must be online and connected to execute remote diagnostics.
            </Notice>
          </div>
        )}
        <div
          style={{
            display: 'flex',
            gap: 'var(--space-2)',
            flexWrap: 'wrap',
            alignItems: 'center',
          }}
        >
          <Button
            variant="primary"
            size="sm"
            disabled={!isOnline || commandLoading}
            onClick={() => executeCommand('GET_PROCESSES')}
          >
            📊 {commandLoading && activeCommand === 'GET_PROCESSES' ? 'Fetching...' : 'Get Processes'}
          </Button>

          <Button
            variant="secondary"
            size="sm"
            disabled={!isOnline || commandLoading}
            onClick={() => executeCommand('GET_CPU_INFO')}
          >
            ⚡ CPU Info
          </Button>

          <Button
            variant="secondary"
            size="sm"
            disabled={!isOnline || commandLoading}
            onClick={() => executeCommand('GET_MEMORY_INFO')}
          >
            🧠 Memory Info
          </Button>

          <Button
            variant="secondary"
            size="sm"
            disabled={!isOnline || commandLoading}
            onClick={() => executeCommand('GET_DISK_INFO')}
          >
            💾 Disk Info
          </Button>

          <Button
            variant="secondary"
            size="sm"
            disabled={!isOnline || commandLoading}
            onClick={() => executeCommand('GET_NETWORK_INFO')}
          >
            🌐 Network Info
          </Button>

          <Button
            variant="secondary"
            size="sm"
            disabled={!isOnline || commandLoading}
            onClick={() => executeCommand('PING')}
          >
            📡 Ping
          </Button>

          <Button
            variant="primary"
            size="sm"
            disabled={!isOnline || commandLoading || neighbourhoodLoading || passiveNeighbourhoodLoading}
            onClick={requestNeighbourhood}
          >
            {neighbourhoodLoading ? 'Collecting Neighbourhood…' : 'Collect Neighbourhood'}
          </Button>

          <Button
            variant="secondary"
            size="sm"
            disabled={!isOnline || commandLoading || neighbourhoodLoading || passiveNeighbourhoodLoading}
            onClick={requestPassiveNeighbourhood}
          >
            {passiveNeighbourhoodLoading ? 'Requesting Passive Info…' : 'Get Passive Network Information'}
          </Button>

          {/* Activity Log dropdown & button */}
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
            <select
              value={activityPeriod}
              onChange={(e) => setActivityPeriod(e.target.value as any)}
              disabled={!isOnline || commandLoading}
              style={{
                background: 'var(--surface)',
                color: 'var(--text)',
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius-sm)',
                padding: '4px 8px',
                fontSize: 'var(--font-xs)',
              }}
            >
              <option value="1d">Last 24h</option>
              <option value="1w">Last 7d</option>
              <option value="1m">Last 30d</option>
            </select>
            <Button
              variant="secondary"
              size="sm"
              disabled={!isOnline || commandLoading}
              onClick={() => executeCommand('GET_ACTIVITY_LOG', activityPeriod)}
            >
              📋 Fetch Log
            </Button>
          </div>

          <Button
            variant="secondary"
            size="sm"
            disabled={!isOnline || commandLoading}
            onClick={() => setShowStartModal(true)}
          >
            🚀 Start Process
          </Button>

          <Button
            variant="danger"
            size="sm"
            disabled={!isOnline || commandLoading}
            onClick={() => {
              if (window.confirm(`Disconnect client ${c.hostname} (${c.id})?`)) {
                executeCommand('DISCONNECT');
              }
            }}
          >
            🛑 Disconnect
          </Button>
        </div>

        {/* Start Process Modal / Bar */}
        {showStartModal && (
          <div
            style={{
              marginTop: 'var(--space-4)',
              padding: 'var(--space-3)',
              background: 'var(--surface-muted)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius)',
              display: 'flex',
              gap: 'var(--space-2)',
              alignItems: 'center',
            }}
          >
            <input
              type="text"
              placeholder="Absolute path to executable (e.g. /usr/bin/htop or notepad.exe)..."
              value={startProcessPath}
              onChange={(e) => setStartProcessPath(e.target.value)}
              style={{
                flex: 1,
                padding: 'var(--space-2)',
                background: 'var(--surface)',
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius-sm)',
                color: 'var(--text)',
                fontSize: 'var(--font-sm)',
              }}
            />
            <Button
              variant="primary"
              size="sm"
              disabled={!startProcessPath.trim() || commandLoading}
              onClick={() => executeCommand('START_PROCESS', startProcessPath.trim())}
            >
              Launch
            </Button>
            <Button variant="quiet" size="sm" onClick={() => setShowStartModal(false)}>
              Cancel
            </Button>
          </div>
        )}
      </SectionCard>

      {passiveNeighbourhood && (() => {
        const protocols = [...new Set(
          passiveNeighbourhood.observations.map((observation) => observation.protocol),
        )].sort();
        const devices = new Set(
          passiveNeighbourhood.observations.map((observation) =>
            observation.mac_address
            || observation.ip_address
            || observation.hostname
            || observation.service_name
            || observation.device_type
            || observation.raw_fields?.usn
            || observation.protocol,
          ),
        );
        const latestObservation = passiveNeighbourhood.observations.reduce<string | null>(
          (latest, observation) => (
            observation.observed_at && (!latest || observation.observed_at > latest)
              ? observation.observed_at
              : latest
          ),
          null,
        );

        return (
          <div style={{ marginTop: 'var(--space-6)' }}>
            <SectionCard title="Passive Network Information">
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
                  gap: 'var(--space-3)',
                }}
              >
                <MetricCard label="Observations" value={String(passiveNeighbourhood.observation_count)} />
                <MetricCard label="Observed endpoints" value={String(devices.size)} />
                <MetricCard label="Protocols" value={String(protocols.length)} />
              </div>
              <div style={{ marginTop: 'var(--space-4)' }}>
                <DetailRow label="Protocols detected" value={protocols.length ? protocols.join(', ') : 'None'} />
                <DetailRow label="Latest observation" value={latestObservation ? formatDateTime(latestObservation) : 'No observations'} />
                <DetailRow label="Snapshot received" value={formatDateTime(passiveNeighbourhood.observed_at)} />
                <DetailRow label="Reporter" value={passiveNeighbourhood.reporter} mono />
              </div>
              <div style={{ marginTop: 'var(--space-4)', overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--font-xs)' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--border)', textAlign: 'left' }}>
                      <th style={{ padding: '8px' }}>Protocol</th>
                      <th style={{ padding: '8px' }}>Observed device or service</th>
                      <th style={{ padding: '8px' }}>Address</th>
                      <th style={{ padding: '8px' }}>Advertisement details</th>
                      <th style={{ padding: '8px' }}>Seen</th>
                      <th style={{ padding: '8px' }}>Latest</th>
                    </tr>
                  </thead>
                  <tbody>
                    {passiveNeighbourhood.observations.length === 0 ? (
                      <tr>
                        <td colSpan={6} style={{ padding: '16px', textAlign: 'center', color: 'var(--text-muted)' }}>
                          No passive protocol observations have been collected in this client session.
                        </td>
                      </tr>
                    ) : (
                      passiveNeighbourhood.observations.map((observation, index) => {
                        const identity =`${observation.device_name}
                           ${ observation.service_name}
                           ${ observation.hostname}
                           ${observation.device_type}
                          ${observation.raw_fields?.usn}` 
                        
                          || 'Unidentified observation';
                        const address = [observation.ip_address, observation.mac_address]
                          .filter(Boolean)
                          .join('\n');
                        const details = [
                          observation.observation_kind,
                          observation.service_type,
                          observation.service_port ? `port ${observation.service_port}` : null,
                          observation.server,
                          observation.location,
                        ].filter(Boolean).join('\n');

                        return (
                          <tr key={`${observation.protocol}-${observation.observed_at ?? index}-${index}`} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                            <td style={{ padding: '8px', verticalAlign: 'top' }}>
                              <Badge variant="info">{observation.protocol}</Badge>
                            </td>
                            <td style={{ padding: '8px', verticalAlign: 'top', fontWeight: 600, maxWidth: '260px', wordBreak: 'break-word' }}>
                              {identity}
                            </td>
                            <td style={{ padding: '8px', verticalAlign: 'top', whiteSpace: 'pre-line', fontFamily: 'var(--font-mono)' }}>
                              {address || '—'}
                            </td>
                            <td style={{ padding: '8px', verticalAlign: 'top', whiteSpace: 'pre-line', maxWidth: '360px', overflowWrap: 'anywhere', color: 'var(--text-muted)' }}>
                              {details || '—'}
                            </td>
                            <td style={{ padding: '8px', verticalAlign: 'top', textAlign: 'right' }}>
                              {observation.seen_count ?? 1}
                            </td>
                            <td style={{ padding: '8px', verticalAlign: 'top', whiteSpace: 'nowrap', color: 'var(--text-muted)' }}>
                              {observation.observed_at ? formatDateTime(observation.observed_at) : '—'}
                            </td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>
            </SectionCard>
          </div>
        );
      })()}

      {/* Live Process Explorer & Manager */}
      {processList && (
        <div style={{ marginTop: 'var(--space-6)' }}>
          <SectionCard
            title={`Running Processes on ${c.hostname} (${filteredProcesses.length} / ${processList.length})`}
          >
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                marginBottom: 'var(--space-3)',
                gap: 'var(--space-3)',
                flexWrap: 'wrap',
              }}
            >
              <input
                type="search"
                placeholder="Filter by process name, PID, or user..."
                value={processFilter}
                onChange={(e) => setProcessFilter(e.target.value)}
                style={{
                  minWidth: '280px',
                  padding: 'var(--space-2) var(--space-3)',
                  background: 'var(--surface)',
                  border: '1px solid var(--border)',
                  borderRadius: 'var(--radius-sm)',
                  color: 'var(--text)',
                  fontSize: 'var(--font-sm)',
                }}
              />
              <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
                <Button
                  variant="quiet"
                  size="sm"
                  onClick={() => executeCommand('GET_PROCESSES')}
                  disabled={commandLoading}
                >
                  🔄 Refresh Processes
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setProcessList(null)}
                >
                  ✕ Close Processes
                </Button>
              </div>
            </div>

            <div style={{ overflowX: 'auto', maxHeight: '420px', overflowY: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--font-xs)' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border)', textAlign: 'left' }}>
                    <th style={{ padding: '8px' }}>PID</th>
                    <th style={{ padding: '8px' }}>Process Name</th>
                    <th style={{ padding: '8px' }}>User</th>
                    <th style={{ padding: '8px' }}>CPU %</th>
                    <th style={{ padding: '8px' }}>Memory %</th>
                    <th style={{ padding: '8px' }}>Status</th>
                    <th style={{ padding: '8px', textAlign: 'right' }}>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredProcesses.length === 0 ? (
                    <tr>
                      <td colSpan={7} style={{ padding: '16px', textAlign: 'center', color: 'var(--text-muted)' }}>
                        No processes matching filter.
                      </td>
                    </tr>
                  ) : (
                    filteredProcesses.map((p, idx) => (
                      <tr
                        key={p.pid ?? idx}
                        style={{
                          borderBottom: '1px solid var(--border-subtle)',
                          fontFamily: 'var(--font-mono)',
                        }}
                      >
                        <td style={{ padding: '8px', color: 'var(--text-muted)' }}>{p.pid ?? '—'}</td>
                        <td style={{ padding: '8px', fontWeight: 600, color: 'var(--text)' }}>
                          {p.name ?? 'unknown'}
                        </td>
                        <td style={{ padding: '8px', color: 'var(--text-muted)' }}>{p.username ?? '—'}</td>
                        <td style={{ padding: '8px' }}>
                          {p.cpu_percent !== undefined ? `${p.cpu_percent.toFixed(1)}%` : '—'}
                        </td>
                        <td style={{ padding: '8px' }}>
                          {p.memory_percent !== undefined ? `${p.memory_percent.toFixed(1)}%` : '—'}
                        </td>
                        <td style={{ padding: '8px' }}>
                          <Badge variant="info">{p.status ?? 'RUNNING'}</Badge>
                        </td>
                        <td style={{ padding: '8px', textAlign: 'right' }}>
                          <button
                            className="btn btn--danger btn--sm"
                            style={{ padding: '2px 8px', fontSize: '11px' }}
                            disabled={commandLoading}
                            onClick={() => {
                              const target = p.name || String(p.pid);
                              if (window.confirm(`Are you sure you want to kill '${target}' on ${c.hostname}?`)) {
                                setKillingProcess(target);
                                executeCommand('KILL_PROCESS', target);
                              }
                            }}
                          >
                            {killingProcess === (p.name || String(p.pid)) && commandLoading
                              ? 'Killing...'
                              : 'Kill'}
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </SectionCard>
        </div>
      )}

      {/* Command Output Inspector (when non-process commands are run) */}
      {commandResult && activeCommand !== 'GET_PROCESSES' && (
        <div style={{ marginTop: 'var(--space-6)' }}>
          <SectionCard title={`Result: ${activeCommand}`}>
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                marginBottom: 'var(--space-3)',
              }}
            >
              <Badge variant="success">Status: OK</Badge>
              <Button variant="quiet" size="sm" onClick={() => setCommandResult(null)}>
                Clear Output
              </Button>
            </div>
            <pre
              style={{
                background: 'var(--surface-muted)',
                padding: 'var(--space-4)',
                borderRadius: 'var(--radius)',
                border: '1px solid var(--border)',
                fontFamily: 'var(--font-mono)',
                fontSize: 'var(--font-xs)',
                overflowX: 'auto',
                maxHeight: '360px',
                color: 'var(--text)',
              }}
            >
              {JSON.stringify(commandResult.data ?? commandResult, null, 2)}
            </pre>
          </SectionCard>
        </div>
      )}

      {/* Two columns Details */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))',
          gap: 'var(--space-6)',
          marginTop: 'var(--space-6)',
        }}
      >
        {/* Identity */}
        <SectionCard title="Identity">
          <div>
            <DetailRow label="Client ID" value={c.id} mono />
            <DetailRow label="Hostname" value={c.hostname} />
            <DetailRow label="IP Address" value={c.ip_address} mono />
            <DetailRow label="MAC Address" value={c.mac_address} mono />
            <DetailRow label="Registered" value={formatDateTime(c.created_at)} />
            <DetailRow label="Last updated" value={formatDateTime(c.updated_at)} />
          </div>
        </SectionCard>

        {/* Operating system */}
        <SectionCard title="Operating System">
          <div>
            <DetailRow label="System" value={c.os.system} />
            <DetailRow label="Release" value={c.os.release} />
            <DetailRow label="Version" value={c.os.version} />
            <DetailRow label="Arch" value={c.os.machine} />
          </div>
        </SectionCard>

        {/* Connection history */}
        <SectionCard title="Recent Connections">
          {d.recent_connections.length === 0 ? (
            <p style={{ fontSize: 'var(--font-sm)', color: 'var(--text-muted)' }}>
              No connection records.
            </p>
          ) : (
            <div
              style={{
                display: 'flex',
                flexDirection: 'column',
                gap: 'var(--space-3)',
              }}
            >
              {d.recent_connections.slice(0, 8).map((conn, i) => (
                <div
                  key={i}
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '1fr 1fr',
                    gap: 'var(--space-2)',
                    fontSize: 'var(--font-xs)',
                    padding: 'var(--space-2)',
                    background: 'var(--surface-muted)',
                    borderRadius: 'var(--radius-sm)',
                  }}
                >
                  <div>
                    <span style={{ color: 'var(--text-muted)' }}>Connected </span>
                    {formatDateTime(conn.connected_at)}
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)' }}>Disconnected </span>
                    {conn.disconnected_at ? (
                      formatDateTime(conn.disconnected_at)
                    ) : (
                      <span style={{ color: 'var(--success)' }}>Active</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </SectionCard>

        {/* Latest activity log */}
        {d.latest_activity_log && (
          <SectionCard title="Latest Activity Log">
            <div>
              <DetailRow label="Log ID" value={String(d.latest_activity_log.id)} />
              <DetailRow label="Period" value={d.latest_activity_log.period} />
              <DetailRow
                label="Generated"
                value={formatDateTime(d.latest_activity_log.generated_at)}
              />
              <DetailRow
                label="Received"
                value={formatDateTime(d.latest_activity_log.received_at)}
              />
            </div>
            <div style={{ marginTop: 'var(--space-3)' }}>
              <a
                href={`/activity/${d.latest_activity_log.id}`}
                className="btn btn--secondary btn--sm"
                style={{ textDecoration: 'none' }}
              >
                View log →
              </a>
            </div>
          </SectionCard>
        )}
      </div>
    </div>
  );
}

function ClientDetailSkeleton() {
  return (
    <div>
      <div
        style={{
          display: 'flex',
          gap: 'var(--space-3)',
          marginBottom: 'var(--space-5)',
        }}
      >
        <Skeleton variant="text-sm" width="5rem" />
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
        <Skeleton
          style={{
            width: 48,
            height: 48,
            borderRadius: 'var(--radius)',
            flexShrink: 0,
          }}
        />
        <div style={{ flex: 1 }}>
          <Skeleton variant="title" style={{ marginBottom: 'var(--space-2)' }} />
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
        {Array.from({ length: 2 }).map((_, i) => (
          <div key={i} className="section-card">
            <div className="section-card__header">
              <Skeleton variant="text-lg" width="8rem" />
            </div>
            <div className="section-card__body">
              {Array.from({ length: 4 }).map((_, j) => (
                <div
                  key={j}
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '10rem 1fr',
                    gap: 'var(--space-3)',
                    padding: 'var(--space-2) 0',
                  }}
                >
                  <Skeleton variant="text-sm" />
                  <Skeleton variant="text" />
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
