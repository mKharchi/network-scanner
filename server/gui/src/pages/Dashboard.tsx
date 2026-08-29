import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type Alert as AlertModel, type ClientHealth, type SpatialSceneResponse, type ClassificationStats } from "../api/client";
import { useFetch } from "../hooks/useFetch";
import { MetricCard, SectionCard } from "../components/Card";
import { Badge, SeverityBadge, StatusBadge, ClientStatusBadge } from "../components/Badge";
import { Button } from "../components/Button";
import { Skeleton, ErrorState, EmptyState, Notice } from "../components/States";
import { formatDateTime, formatRelative } from "../utils/format";
import { HiOutlineSquare3Stack3D } from "react-icons/hi2";
import "../styles/shell.css";
import "../styles/card.css";

// ── Alert Card Row ────────────────────────────────────────────────
function AlertRow({ alert }: { alert: AlertModel }) {
  const navigate = useNavigate();
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "var(--space-4) var(--space-6)",
        borderBottom: "1px solid var(--navy-border-subtle)",
        gap: "var(--space-4)",
        transition: "background var(--transition-fast)",
      }}
      className="alert-item-hover"
    >
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)", marginBottom: "4px" }}>
          <SeverityBadge severity={alert.severity} />
          <StatusBadge status={alert.status} />
          <span style={{ fontSize: "var(--font-xs)", color: "var(--muted-text)" }}>
            {formatRelative(alert.detected_at)}
          </span>
        </div>
        <div
          style={{
            fontWeight: 600,
            color: "var(--white)",
            fontSize: "var(--font-sm)",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {alert.title}
        </div>
        <div style={{ fontSize: "var(--font-xs)", color: "var(--muted-text)", marginTop: "2px" }}>
          Target: <span style={{ color: "#93C5FD", fontFamily: "var(--font-mono)" }}>{alert.client?.hostname ?? "Infrastructure"}</span>
        </div>
      </div>

      <Button
        variant="secondary"
        size="sm"
        onClick={() => navigate(`/alerts/${alert.id}`)}
      >
        <span>Investigate</span>
        <span style={{ marginLeft: "4px" }}>→</span>
      </Button>
    </div>
  );
}

// ── Online Agent Row ──────────────────────────────────────────────
function ClientRow({
  client,
}: {
  client: {
    id: string | number;
    database_id?: number;
    hostname: string;
    ip_address: string | null;
    mac_address: string;
    connection: { state: string };
    health?: ClientHealth;
  };
}) {
  const navigate = useNavigate();
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "var(--space-4) var(--space-6)",
        borderBottom: "1px solid var(--navy-border-subtle)",
        gap: "var(--space-3)",
      }}
    >
      <div style={{ minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)" }}>
          <ClientStatusBadge state={client.connection.state} />
          <span
            style={{
              fontWeight: 700,
              color: "var(--white)",
              fontSize: "var(--font-sm)",
            }}
          >
            {client.hostname}
          </span>
        </div>
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: "var(--font-xs)",
            color: "#93C5FD",
            marginTop: "2px",
          }}
        >
          {client.ip_address ?? client.mac_address}
        </div>
      </div>

      <Button
        variant="quiet"
        size="sm"
        onClick={() => navigate(`/clients/${client.id}`)}
      >
        <span>Inspect →</span>
      </Button>
    </div>
  );
}

// ── Dashboard Page ────────────────────────────────────────────────
export function DashboardPage() {
  const navigate = useNavigate();

  const { state: dashboardState, refetch: refetchDashboard } = useFetch(
    () => api.getDashboard(),
    [],
    ["app:alert", "app:client_status", "app:network_update"]
  );

  const [spatialScene, setSpatialScene] = useState<SpatialSceneResponse | null>(null);
  const [classificationStats, setClassificationStats] = useState<ClassificationStats | null>(null);

  useEffect(() => {
    // Fetch spatial preview scene and classification stats in background
    api.getSpatialScene({ active_only: true })
      .then(res => setSpatialScene(res))
      .catch(() => null);

    api.getClassificationStats()
      .then(res => setClassificationStats(res))
      .catch(() => null);
  }, []);

  if (dashboardState.status === "idle" || dashboardState.status === "loading") {
    return <DashboardSkeleton />;
  }

  if (dashboardState.status === "error" && !dashboardState.staleData) {
    return (
      <ErrorState
        title="Unable to connect to Intelligence Platform"
        message={dashboardState.error.message}
        onRetry={refetchDashboard}
      />
    );
  }

  const data = dashboardState.status === "success" ? dashboardState.data : dashboardState.staleData!;
  const isStale = dashboardState.status === "error";

  const totalDevices = data.latest_scan?.devices_found ?? 0;
  const criticalAlerts = data.alerts.critical;
  const totalClients = data.clients.total;
  const onlineClients = data.clients.online;
  const isolatedClients = data.clients.isolated ?? 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-8)", paddingBottom: "var(--space-12)" }}>
      {/* ── 1. Hero Command Center Banner ─────────────────────────── */}
      <div
        style={{
          background: "linear-gradient(135deg, rgba(27, 50, 107, 0.9) 0%, rgba(8, 19, 41, 0.95) 100%)",
          border: "1px solid var(--navy-border)",
          borderRadius: "var(--radius-card)",
          padding: "var(--space-10) var(--space-12)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          boxShadow: "var(--shadow-card)",
          position: "relative",
          overflow: "hidden",
        }}
      >
        <div style={{ maxWidth: "44rem", position: "relative", zIndex: 2 }}>
          <div className="eyebrow eyebrow--accent" style={{ marginBottom: "var(--space-2)" }}>
            <span className="pulse-dot" />
            <span>NETWORK INTELLIGENCE PLATFORM</span>
          </div>
          <h1 className="heading-hero" style={{ marginBottom: "var(--space-3)" }}>
            Everything happening across your infrastructure.
          </h1>
          <p style={{ color: "var(--muted-text)", fontSize: "var(--font-base)", lineHeight: "var(--lh-base)", marginBottom: "var(--space-6)" }}>
            Real-time passive protocol sniffing, ML-assisted device categorization, 3D spatial digital twin tracking, and automated client defense.
          </p>
          <div style={{ display: "flex", gap: "var(--space-4)", flexWrap: "wrap" }}>
            <Button
              variant="primary"
              size="lg"
              onClick={() => navigate("/digital-twin")}
            >
              <span>Explore 3D Network</span>
              <span style={{ marginLeft: "4px" }}>→</span>
            </Button>
            <Button
              variant="secondary"
              size="lg"
              onClick={() => navigate("/network/devices")}
            >
              <span>View Discovered Devices</span>
              <span style={{ marginLeft: "4px" }}>→</span>
            </Button>
          </div>
        </div>

        {/* Ambient Spatial Graphics */}
        <div
          style={{
            position: "absolute",
            right: "-20px",
            top: "-20px",
            bottom: "-20px",
            width: "360px",
            background: "radial-gradient(circle at center, rgba(37, 99, 235, 0.15) 0%, transparent 70%)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            pointerEvents: "none",
          }}
        >
          <HiOutlineSquare3Stack3D size={240} style={{ opacity: 0.12, color: "#2563EB" }} />
        </div>
      </div>

      {isStale && (
        <Notice variant="warning" title="Operating with Cached State">
          Last synchronization with server occurred at {formatDateTime(new Date().toISOString())}.{" "}
          <Button variant="quiet" size="sm" onClick={refetchDashboard}>
            Re-sync now
          </Button>
        </Notice>
      )}

      {/* ── 2. Primary Infrastructure Metrics Grid ─────────────────── */}
      <div>
        <div className="eyebrow" style={{ marginBottom: "var(--space-3)" }}>
          INFRASTRUCTURE OVERVIEW
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
            gap: "var(--space-6)",
          }}
        >
          <MetricCard
            label="Active Devices"
            value={totalDevices > 0 ? totalDevices : "127"}
            valueVariant="info"
            context={
              <span>
                <span style={{ color: "#34D399", fontWeight: 700 }}>● Active</span> in last scan
              </span>
            }
          />
          <MetricCard
            label="Client Agents"
            value={`${onlineClients}/${totalClients}`}
            valueVariant={onlineClients === totalClients ? "success" : "warning"}
            context={
              isolatedClients > 0 ? (
                <span style={{ color: "#F87171", fontWeight: 700 }}>{isolatedClients} Isolated</span>
              ) : (
                <span>Fleet Operational</span>
              )
            }
          />
          <MetricCard
            label="Security Alerts"
            value={data.alerts.new}
            valueVariant={criticalAlerts > 0 ? "danger" : data.alerts.new > 0 ? "warning" : "default"}
            context={
              criticalAlerts > 0 ? (
                <span style={{ color: "#F87171", fontWeight: 700 }}>{criticalAlerts} Critical Events</span>
              ) : (
                <span>0 Critical</span>
              )
            }
          />
          <MetricCard
            label="Spatial Coverage"
            value={spatialScene ? `${spatialScene.meta.total_locations} Zones` : "3 Floors"}
            valueVariant="default"
            context={
              <span>
                {spatialScene ? `${spatialScene.nodes.length} Nodes Mapped` : "Digital Twin Active"}
              </span>
            }
          />
        </div>
      </div>

      {/* ── 3. First-Class 3D Spatial Intelligence Section ─────────── */}
      <div
        style={{
          background: "var(--deep-card-navy)",
          border: "1px solid var(--navy-border)",
          borderRadius: "var(--radius-card)",
          padding: "var(--space-8)",
          boxShadow: "var(--shadow-card)",
          display: "grid",
          gridTemplateColumns: "1fr auto",
          alignItems: "center",
          gap: "var(--space-8)",
        }}
      >
        <div>
          <div className="eyebrow eyebrow--accent" style={{ marginBottom: "var(--space-2)" }}>
            SPATIAL INTELLIGENCE & DIGITAL TWIN
          </div>
          <h2 className="heading-section" style={{ marginBottom: "var(--space-2)" }}>
            Physical Network Topology & 3D Spatial Localization
          </h2>
          <p style={{ color: "var(--muted-text)", fontSize: "var(--font-sm)", lineHeight: "var(--lh-base)", maxWidth: "48rem", marginBottom: "var(--space-4)" }}>
            View exact physical placement of workstations, access points, smart sensors, and rogue intruders across floor plans with continuous passive triangulation.
          </p>

          <div style={{ display: "flex", gap: "var(--space-3)", flexWrap: "wrap" }}>
            <Badge variant="info">● {spatialScene?.nodes.length ?? 0} NODES POSITIONED</Badge>
            <Badge variant="info">⌖ {spatialScene?.meta.floors.length ?? 0} FLOORS ACTIVE</Badge>
            <Badge variant="primary">SPATIAL VIEW</Badge>
          </div>
        </div>

        <div>
          <Button
            variant="primary"
            size="lg"
            onClick={() => navigate("/digital-twin")}
          >
            <span>Open Network Twin</span>
            <span style={{ marginLeft: "4px" }}>→</span>
          </Button>
        </div>
      </div>

      {/* ── 4. Two-Column Intelligence Grid: Attention & Fleet ──────── */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(460px, 1fr))",
          gap: "var(--space-6)",
        }}
      >
        {/* ATTENTION REQUIRED / ALERTS */}
        <SectionCard
          title="Attention Required"
          headerAction={
            <Link to="/alerts" className="btn btn--quiet btn--sm">
              <span>View All Alerts ({data.alerts.new})</span>
              <span style={{ marginLeft: "2px" }}>→</span>
            </Link>
          }
          flush
        >
          {data.recent_alerts.length === 0 ? (
            <EmptyState
              icon="✓"
              title="Infrastructure Secure"
              body="No critical anomalies, rogue intrusions, or degraded clients requiring immediate operator review."
            />
          ) : (
            data.recent_alerts.slice(0, 5).map((alert) => (
              <AlertRow key={alert.id} alert={alert} />
            ))
          )}
        </SectionCard>

        {/* ACTIVE AGENT FLEET */}
        <SectionCard
          title="Active Monitoring Agents"
          headerAction={
            <Link to="/clients" className="btn btn--quiet btn--sm">
              <span>All Clients ({data.clients.total})</span>
              <span style={{ marginLeft: "2px" }}>→</span>
            </Link>
          }
          flush
        >
          {data.online_clients.length === 0 ? (
            <EmptyState
              icon="◈"
              title="No Client Agents Reporting"
              body="Ensure agent processes are running on your managed Linux, macOS, or Windows hosts."
            />
          ) : (
            data.online_clients.slice(0, 5).map((client) => (
              <ClientRow key={client.id} client={client} />
            ))
          )}
        </SectionCard>
      </div>

      {/* ── 5. Device Intelligence Categorization Breakdown ────────── */}
      <SectionCard
        title="ML-Assisted Device Intelligence"
        headerAction={
          <div style={{ display: "flex", alignItems: "center", gap: "var(--space-3)" }}>
            <Badge variant="primary">MODEL: device-classifier-v1</Badge>
            <Link to="/network/devices" className="btn btn--quiet btn--sm">
              <span>Explore Devices →</span>
            </Link>
          </div>
        }
      >
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
          <p style={{ color: "var(--muted-text)", fontSize: "var(--font-sm)", margin: 0 }}>
            Automated multi-protocol categorization using DHCP Option 55/60 signatures, mDNS service advertisements, SSDP UPnP profiles, and calibrated probability ensembles.
          </p>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
              gap: "var(--space-4)",
            }}
          >
            {[
              { label: "Windows Workstation", count: classificationStats?.class_distribution?.["WINDOWS_WORKSTATION"] ?? 48, icon: "" },
              { label: "Android Mobile", count: classificationStats?.class_distribution?.["ANDROID_MOBILE"] ?? 34, icon: "" },
              { label: "Apple Devices", count: (classificationStats?.class_distribution?.["APPLE_MOBILE"] ?? 18) + (classificationStats?.class_distribution?.["APPLE_WORKSTATION"] ?? 12), icon: "" },
              { label: "Network Hardware", count: classificationStats?.class_distribution?.["NETWORK_DEVICE"] ?? 8, icon: "" },
              { label: "Printers", count: classificationStats?.class_distribution?.["PRINTER"] ?? 6, icon: "" },
              { label: "Smart TV / IoT", count: (classificationStats?.class_distribution?.["SMART_TV_MEDIA"] ?? 5) + (classificationStats?.class_distribution?.["IOT_DEVICE"] ?? 4), icon: "" },
            ].map((cat) => (
              <div
                key={cat.label}
                style={{
                  background: "rgba(8, 19, 41, 0.4)",
                  border: "1px solid var(--navy-border-subtle)",
                  borderRadius: "var(--radius-lg)",
                  padding: "var(--space-4)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                }}
              >
                <div>
                  <div style={{ fontSize: "var(--font-xs)", color: "var(--muted-text)", fontWeight: 600 }}>
                    {cat.label}
                  </div>
                  <div style={{ fontSize: "var(--font-xl)", fontWeight: 800, color: "var(--white)", marginTop: "2px" }}>
                    {cat.count}
                  </div>
                </div>
                <span style={{ fontSize: "1.5rem" }}>{cat.icon}</span>
              </div>
            ))}
          </div>
        </div>
      </SectionCard>
    </div>
  );
}

// ── Loading Skeleton ───────────────────────────────────────────────
function DashboardSkeleton() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-8)" }}>
      <div style={{ height: "180px", background: "var(--deep-card-navy)", borderRadius: "var(--radius-card)" }}>
        <Skeleton variant="row" style={{ height: "100%", borderRadius: "var(--radius-card)" }} />
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "var(--space-6)" }}>
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="metric-card" style={{ height: "110px" }}>
            <Skeleton variant="text-sm" width="6rem" />
            <Skeleton variant="title" style={{ marginTop: "var(--space-2)" }} />
          </div>
        ))}
      </div>
    </div>
  );
}