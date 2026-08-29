import { useState } from 'react';
import { api, type NetworkDevice } from '../api/client';
import { useFetch } from '../hooks/useFetch';
import { ClassificationBadge } from '../components/Badge';
import { Button } from '../components/Button';
import { DataTable, type Column } from '../components/DataTable';
import { SectionCard } from '../components/Card';
import { SkeletonTable, ErrorState, EmptyState, Notice } from '../components/States';
import { formatDateTime, normalizeMac } from '../utils/format';
import { MetricCard } from '../components/Card';
import '../styles/operations.css';

interface ScanSummaryItem {
  id: string;
  completed_at: string;
  devices_found: number;
  network: Record<string, unknown>;
}

export function ScanHistoryPage() {
  const [selectedScanId, setSelectedScanId] = useState<string | null>(null);
  const [fromDate, setFromDate] = useState('');
  const [toDate, setToDate] = useState('');

  const { state: historyState, refetch: refetchHistory } = useFetch(
    () => api.getScanHistory({ from: fromDate || undefined, to: toDate || undefined }),
    [fromDate, toDate],
  );

  const { state: scanDetailState, refetch: refetchDetail } = useFetch(
    selectedScanId ? () => api.getScan(selectedScanId) : null,
    [selectedScanId],
  );

  const historyItems: ScanSummaryItem[] =
    historyState.status === 'success'
      ? historyState.data.items
      : historyState.status === 'error' && historyState.staleData
        ? historyState.staleData.items
        : [];

  const scanColumns: Column<ScanSummaryItem>[] = [
    {
      key: 'completed_at',
      label: 'Completed At',
      render: (item) => (
        <span style={{ fontWeight: 500 }}>{formatDateTime(item.completed_at)}</span>
      ),
    },
    {
      key: 'devices_found',
      label: 'Devices Found',
      align: 'right',
      render: (item) => (
        <span style={{ fontVariantNumeric: 'tabular-nums' }}>{item.devices_found}</span>
      ),
    },
    {
      key: 'id',
      label: 'Scan ID',
      mono: true,
      render: (item) => item.id,
    },
  ];

  const deviceColumns: Column<NetworkDevice>[] = [
    {
      key: 'ip_address',
      label: 'IP Address',
      mono: true,
      render: (d) => d.ip_address ?? null,
    },
    {
      key: 'mac_address',
      label: 'MAC Address',
      mono: true,
      render: (d) => normalizeMac(d.mac_address),
    },
    {
      key: 'hostname',
      label: 'Hostname',
      render: (d) => d.hostname ?? null,
    },
    {
      key: 'vendor',
      label: 'Vendor',
      render: (d) => d.vendor ?? null,
    },
    {
      key: 'classification',
      label: 'Classification',
      render: (d) => <ClassificationBadge managed={d.is_managed} />,
    },
  ];

  return (
    <div>
      <div className="page-header operations-page-header">
        <div>
          <span className="eyebrow eyebrow--accent">NETWORK / SCAN HISTORY</span>
          <h1 className="page-title">Discovery history</h1>
          <p className="page-description">Historical network discovery scans and snapshots for change analysis.</p>
        </div>
        <div className="operations-page-header__actions"><Button variant="quiet" size="sm" onClick={refetchHistory}>Refresh</Button></div>
      </div>
      <div className="operations-metric-grid">
        <MetricCard label="Recorded scans" value={historyItems.length} context="Matching the selected date range" />
        <MetricCard label="Devices in latest" value={historyItems[0]?.devices_found ?? '—'} valueVariant="info" context="Most recent completed scan" />
        <MetricCard label="From" value={fromDate || 'Any'} context="Start of date range" />
        <MetricCard label="To" value={toDate || 'Any'} context="End of date range" />
      </div>

      {historyState.status === 'error' && (
        <Notice variant="warning" title="History data is stale">
          {historyState.error.message}
        </Notice>
      )}

      {/* Date filters */}
      <div
        style={{
          display: 'flex',
          gap: 'var(--space-3)',
          marginBottom: 'var(--space-5)',
          alignItems: 'center',
          flexWrap: 'wrap',
        }}
      >
        <label style={{ fontSize: 'var(--font-sm)', color: 'var(--text-muted)' }}>
          From:
          <input
            type="date"
            value={fromDate}
            onChange={(e) => setFromDate(e.target.value)}
            style={{
              marginLeft: 'var(--space-2)',
              padding: '0 var(--space-2)',
              height: 36,
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius)',
              fontFamily: 'var(--font-sans)',
              background: 'var(--surface)',
              color: 'var(--text)',
            }}
          />
        </label>
        <label style={{ fontSize: 'var(--font-sm)', color: 'var(--text-muted)' }}>
          To:
          <input
            type="date"
            value={toDate}
            onChange={(e) => setToDate(e.target.value)}
            style={{
              marginLeft: 'var(--space-2)',
              padding: '0 var(--space-2)',
              height: 36,
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius)',
              fontFamily: 'var(--font-sans)',
              background: 'var(--surface)',
              color: 'var(--text)',
            }}
          />
        </label>
        {(fromDate || toDate) && (
          <Button
            variant="quiet"
            size="sm"
            onClick={() => {
              setFromDate('');
              setToDate('');
            }}
          >
            Clear dates
          </Button>
        )}
      </div>

      {/* Scan list */}
      <div style={{ marginBottom: 'var(--space-6)' }}>
        {historyState.status === 'idle' || historyState.status === 'loading' ? (
          <SkeletonTable rows={5} columns={3} />
        ) : historyState.status === 'error' && !historyState.staleData ? (
          <ErrorState
            title="Unable to load scan history"
            message={historyState.error.message}
            onRetry={refetchHistory}
          />
        ) : historyItems.length === 0 ? (
          <EmptyState
            icon="🗂️"
            title="No scan history found"
            body="No scans match the selected date range."
          />
        ) : (
          <DataTable
            columns={scanColumns}
            data={historyItems}
            rowKey={(item) => item.id}
            onRowClick={(item) => setSelectedScanId(item.id)}
            aria-label="Scan history"
          />
        )}
      </div>

      {/* Selected Scan Detail Drawer/Panel */}
      {selectedScanId && (
        <SectionCard
          title={`Scan: ${selectedScanId}`}
          headerAction={
            <Button variant="quiet" size="sm" onClick={() => setSelectedScanId(null)}>
              Close
            </Button>
          }
        >
          {scanDetailState.status === 'loading' ? (
            <SkeletonTable rows={4} columns={5} />
          ) : scanDetailState.status === 'error' ? (
            <ErrorState
              title="Unable to load scan details"
              message={scanDetailState.error.message}
              onRetry={refetchDetail}
            />
          ) : scanDetailState.status === 'success' ? (
            <div>
              <p
                style={{
                  fontSize: 'var(--font-xs)',
                  color: 'var(--text-muted)',
                  marginBottom: 'var(--space-4)',
                }}
              >
                Completed {formatDateTime(scanDetailState.data.scan.completed_at)} ·{' '}
                {scanDetailState.data.scan.devices_found} device(s) observed
              </p>
              <DataTable
                columns={deviceColumns}
                data={scanDetailState.data.scan.devices}
                rowKey={(d) => d.mac_address}
                aria-label="Devices in selected scan"
              />
            </div>
          ) : null}
        </SectionCard>
      )}
    </div>
  );
}
