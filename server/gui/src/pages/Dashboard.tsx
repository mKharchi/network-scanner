import { api, type Alert as AlertModel } from "../api/client";
import { useFetch } from "../hooks/useFetch";
import { MetricCard } from "../components/Card";
import {
  SeverityBadge,
  StatusBadge,
  ClientStatusBadge,
} from "../components/Badge";
import { Button } from "../components/Button";
import { Skeleton, ErrorState, EmptyState, Notice } from "../components/States";
import { formatDateTime, formatRelative } from "../utils/format";
import { Link } from "react-router-dom";
import "../styles/shell.css";

// ── Recent alert row ──────────────────────────────────────────────
function AlertRow({ alert }: { alert: AlertModel }) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1fr auto auto",
        gap: "var(--space-3)",
        alignItems: "center",
        padding: "var(--space-3) var(--space-4)",
        borderBottom: "1px solid var(--border-subtle)",
      }}
    >
      <div style={{ minWidth: 0 }}>
        <div
          style={{
            fontWeight: 500,
            color: "var(--text)",
            fontSize: "var(--font-sm)",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {alert.title}
        </div>
        <div
          style={{
            fontSize: "var(--font-xs)",
            color: "var(--text-muted)",
            marginTop: 2,
          }}
        >
          {alert.client?.hostname ?? "—"} · {formatRelative(alert.detected_at)}
        </div>
      </div>
      <SeverityBadge severity={alert.severity} />
      <StatusBadge status={alert.status} />
    </div>
  );
}

// ── Online client row ─────────────────────────────────────────────
function ClientRow({
  client,
}: {
  client: {
    hostname: string;
    ip_address: string | null;
    mac_address: string;
    connection: { state: string };
  };
}) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1fr auto auto",
        gap: "var(--space-3)",
        alignItems: "center",
        padding: "var(--space-3) var(--space-4)",
        borderBottom: "1px solid var(--border-subtle)",
      }}
    >
      <div style={{ minWidth: 0 }}>
        <div
          style={{
            fontWeight: 500,
            fontSize: "var(--font-sm)",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {client.hostname}
        </div>
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: "var(--font-xs)",
            color: "var(--text-muted)",
            marginTop: 2,
          }}
        >
          {client.ip_address ?? "—"}
        </div>
      </div>
      <ClientStatusBadge state={client.connection.state} />
    </div>
  );
}

// ── Dashboard page ────────────────────────────────────────────────
export function DashboardPage() {
  const { state, refetch } = useFetch(
    () => api.getDashboard(),
    [],
    ["app:alert", "app:client_status", "app:network_update"]
  );

  if (state.status === "idle" || state.status === "loading") {
    return <DashboardSkeleton />;
  }

  if (state.status === "error" && !state.staleData) {
    return (
      <ErrorState
        title="Unable to load dashboard"
        message={state.error.message}
        onRetry={refetch}
      />
    );
  }

  const data = state.status === "success" ? state.data : state.staleData!;
  const isStale = state.status === "error";

  return (
    <div className="dashboard">
      {/* ── Professional Header ── */}
      <div className="page-header" style={{ paddingBottom: "var(--space-4)", marginBottom: "-var(--space-4)" , borderBottom:"1px solid var(--border-subtle)" }}>
        <div style={{
          display:"flex",
          flexDirection:"column",
          gap:"var(--space-1)",

        }}>
          <h1 className="page-title">System Overview</h1>
          <p className="page-description">
            Real-time metrics, alerts, and status for your managed network.
          </p>
        </div>
      </div>

      {isStale && (
        <div className="dashboard__notice">
          <Notice variant="warning" title="Data is stale">
            Last successful load at{" "}
            {formatDateTime(
              new Date(
                state.status === "error" && state.staleData
                  ? Date.now() - 1
                  : Date.now()
              ).toISOString()
            )}
            .{" "}
            <Button variant="quiet" size="sm" onClick={refetch}>
              Retry
            </Button>
          </Notice>
        </div>
      )}

      {/* ── Summary metrics ── */}
      <div className="dashboard__metrics">
        <MetricCard
          label="Clients online"
          value={data.clients.online}
          valueVariant="success"
          context={`of ${data.clients.total} registered`}
        />
        {(data.clients.isolated ?? 0) > 0 && (
          <MetricCard
            label="Clients isolated"
            value={data.clients.isolated!}
            valueVariant="danger"
            context="device isolation active"
          />
        )}
        <MetricCard
          label="Clients offline"
          value={data.clients.offline}
          valueVariant={data.clients.offline > 0 ? "warning" : "default"}
          context="not connected"
        />
        {(data.clients.unassigned ?? 0) > 0 && (
          <MetricCard
            label="Location unassigned"
            value={data.clients.unassigned!}
            valueVariant="warning"
            context={
              <Link to="/clients?location=unassigned" style={{ color: "inherit" }}>
                Assign physical locations
              </Link>
            }
          />
        )}
        <MetricCard
          label="New alerts"
          value={data.alerts.new}
          valueVariant={data.alerts.new > 0 ? "danger" : "default"}
          context={
            data.alerts.critical > 0
              ? `${data.alerts.critical} critical`
              : "none critical"
          }
        />
        <MetricCard
          label="Devices in latest scan"
          value={data.latest_scan?.devices_found ?? "—"}
          context={
            data.latest_scan
              ? formatRelative(data.latest_scan.completed_at)
              : "No scan yet"
          }
        />
        {data.dhcp_today && (
          <MetricCard
            label="DHCP observations today"
            value={data.dhcp_today.observations}
            context={`on ${data.dhcp_today.date}`}
          />
        )}
      </div>

      {/* ── Two-column detail panels ── */}
      <div className="dashboard__content">
        {/* Recent alerts */}
        <div className="section-card dashboard__panel">
          <div className="section-card__header">
            <h2 className="section-card__title">Recent Alerts</h2>
            <a
              href="/alerts"
              className="btn btn--quiet btn--sm"
              style={{ textDecoration: "none" }}
            >
              View all
            </a>
          </div>
          <div className="section-card__body section-card__body--flush">
            {data.recent_alerts.length === 0 ? (
              <EmptyState
                icon="✓"
                title="No recent alerts"
                body="The system is currently operating normally."
              />
            ) : (
              data.recent_alerts.map((a) => <AlertRow key={a.id} alert={a} />)
            )}
          </div>
        </div>

        {/* Right Column: Clients & Scans */}
        <div className="dashboard_right dashboard__panel">
          <div className="section-card">
            <div className="section-card__header">
              <h2 className="section-card__title">Online Clients</h2>
              <a
                href="/clients"
                className="btn btn--quiet btn--sm"
                style={{ textDecoration: "none" }}
              >
                View all
              </a>
            </div>
            <div className="section-card__body section-card__body--flush">
              {data.online_clients.length === 0 ? (
                <EmptyState
                  icon="-"
                  title="No clients connected"
                  body="No monitoring agents are currently reporting as online."
                />
              ) : (
                data.online_clients.map((c) => (
                  <ClientRow key={c.id} client={c} />
                ))
              )}
            </div>
          </div>

          {/* Latest scan summary */}
          {data.latest_scan ? (
            <div className="section-card">
              <div className="section-card__header">
                <h2 className="section-card__title">Latest Network Scan</h2>
                <a
                  href="/network/latest"
                  className="btn btn--quiet btn--sm"
                  style={{ textDecoration: "none" }}
                >
                  Details
                </a>
              </div>
              <div className="section-card__body">
                <div
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    gap: "var(--space-2)",
                  }}
                >
                  <Row
                    label="Completed"
                    value={formatDateTime(data.latest_scan.completed_at)}
                  />
                  <Row
                    label="Devices found"
                    value={String(data.latest_scan.devices_found)}
                  />
                  <Row label="Scan ID" value={data.latest_scan.scan_id} mono />
                </div>
              </div>
            </div>
          ) : (
            <div className="section-card">
              <div className="section-card__header">
                <h2 className="section-card__title">Latest Network Scan</h2>
              </div>
              <div className="section-card__body">
                <EmptyState
                  icon="-"
                  title="No completed scan yet"
                  body="Network scan results will populate here upon completion."
                />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Helper: label + value row ─────────────────────────────────────
function Row({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div style={{ display: "flex", gap: "var(--space-3)", alignItems: "baseline" }}>
      <span
        style={{
          fontSize: "var(--font-xs)",
          color: "var(--text-muted)",
          width: "9rem",
          flexShrink: 0,
        }}
      >
        {label}
      </span>
      <span
        style={{
          fontSize: "var(--font-sm)",
          fontFamily: mono ? "var(--font-mono)" : undefined,
          wordBreak: "break-all",
        }}
      >
        {value}
      </span>
    </div>
  );
}

// ── Loading skeleton ───────────────────────────────────────────────
function DashboardSkeleton() {
  return (
    <div className="dashboard">
      <div className="page-header" style={{ marginBottom: "var(--space-4)" }}>
        <div>
          <Skeleton variant="title" width="16rem" style={{ height: "2.5rem" }} />
          <Skeleton variant="text" width="24rem" style={{ marginTop: "0.5rem" }} />
        </div>
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
          gap: "var(--space-4)",
          marginBottom: "var(--space-6)",
        }}
      >
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="metric-card">
            <Skeleton variant="text-sm" width="6rem" />
            <Skeleton variant="title" style={{ marginTop: "var(--space-2)" }} />
            <Skeleton
              variant="text-sm"
              width="5rem"
              style={{ marginTop: "var(--space-1)" }}
            />
          </div>
        ))}
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))",
          gap: "var(--space-6)",
        }}
      >
        {Array.from({ length: 2 }).map((_, i) => (
          <div key={i} className="section-card">
            <div className="section-card__header">
              <Skeleton variant="text-lg" width="8rem" />
            </div>
            <div className="section-card__body section-card__body--flush">
              {Array.from({ length: 3 }).map((_, j) => (
                <Skeleton
                  key={j}
                  variant="row"
                  style={{ borderBottom: "1px solid var(--border-subtle)" }}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}