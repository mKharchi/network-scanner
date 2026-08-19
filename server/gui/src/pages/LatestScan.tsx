import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type GlobalNetworkScan, type NetworkDevice } from "../api/client";
import { useFetch } from "../hooks/useFetch";
import { useToast } from "../hooks/useToast";
import { ClassificationBadge } from "../components/Badge";
import { Button } from "../components/Button";
import { DataTable, type Column } from "../components/DataTable";
import {
  SkeletonTable,
  ErrorState,
  EmptyState,
  Notice,
} from "../components/States";
import { formatDateTime, formatRelative, normalizeMac } from "../utils/format";

export function LatestScanPage() {
  const navigate = useNavigate();
  const [filter, setFilter] = useState<"ALL" | "MANAGED" | "UNMANAGED">("ALL");
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState("ip_address");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  const { state, refetch } = useFetch(
    () => api.getLatestScan(),
    [],
    ["app:network_update", "network_update"]
  );
  const { state: activeGlobalScanState } = useFetch(
    () => api.getGlobalActiveScan(),
    [],
  );
  const [globalScan, setGlobalScan] = useState<GlobalNetworkScan | null>(null);

  useEffect(() => {
    if (activeGlobalScanState.status === "success") {
      setGlobalScan(activeGlobalScanState.data);
    }
  }, [activeGlobalScanState]);

  useEffect(() => {
    if (!globalScan || !["started", "already_running", "pending", "running"].includes(globalScan.status)) {
      return;
    }
    const timer = window.setInterval(() => {
      api.getGlobalActiveScan(globalScan.id).then(setGlobalScan).catch(() => undefined);
    }, 1500);
    return () => window.clearInterval(timer);
  }, [globalScan?.id, globalScan?.status]);

  const handleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  };

  const scan =
    state.status === "success"
      ? state.data.scan
      : state.status === "error" && state.staleData
        ? state.staleData.scan
        : null;

  const rawDevices: NetworkDevice[] = scan?.devices ?? [];

  const filteredDevices = rawDevices.filter((d) => {
    if (filter === "MANAGED" && !d.is_managed) return false;
    if (filter === "UNMANAGED" && d.is_managed) return false;
    if (search.trim()) {
      const q = search.toLowerCase();
      const ip = (d.ip_address ?? "").toLowerCase();
      const mac = (d.mac_address ?? "").toLowerCase();
      const host = (d.hostname ?? "").toLowerCase();
      const vendor = (d.vendor ?? "").toLowerCase();
      if (
        !ip.includes(q) &&
        !mac.includes(q) &&
        !host.includes(q) &&
        !vendor.includes(q)
      ) {
        return false;
      }
    }
    return true;
  });

  const sortedDevices = [...filteredDevices].sort((a, b) => {
    let av = "";
    let bv = "";
    if (sortKey === "ip_address") {
      av = a.ip_address ?? "";
      bv = b.ip_address ?? "";
    } else if (sortKey === "hostname") {
      av = a.hostname ?? "";
      bv = b.hostname ?? "";
    } else if (sortKey === "mac_address") {
      av = a.mac_address ?? "";
      bv = b.mac_address ?? "";
    } else if (sortKey === "vendor") {
      av = a.vendor ?? "";
      bv = b.vendor ?? "";
    }
    return sortDir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
  });

  const columns: Column<NetworkDevice>[] = [
    {
      key: "ip_address",
      label: "IP Address",
      sortable: true,
      mono: true,
      render: (d) => d.ip_address ?? null,
    },
    {
      key: "mac_address",
      label: "MAC Address",
      sortable: true,
      mono: true,
      render: (d) => normalizeMac(d.mac_address),
    },
    {
      key: "hostname",
      label: "Hostname",
      sortable: true,
      render: (d) => (
        <span style={{ fontWeight: d.hostname ? 500 : 400 }}>
          {d.hostname ?? null}
        </span>
      ),
    },
    {
      key: "vendor",
      label: "Vendor",
      sortable: true,
      render: (d) => d.vendor ?? null,
    },
    {
      key: "classification",
      label: "Classification",
      render: (d) => <ClassificationBadge managed={d.is_managed} />,
    },
    {
      key: "last_observed_at",
      label: "Observed",
      align: "right",
      render: (d) => (
        <span
          style={{ fontSize: "var(--font-xs)", color: "var(--text-muted)" }}
        >
          {formatRelative(d.last_observed_at)}
        </span>
      ),
    },
  ];

  const { addToast } = useToast();
  const [isScanning, setIsScanning] = useState(false);
  const [isActiveScanning, setIsActiveScanning] = useState(false);
  const [isGlobalActiveScanning, setIsGlobalActiveScanning] = useState(false);

  const handleRunScan = async () => {
    setIsScanning(true);
    try {
      const res = await api.triggerManualScan();
      addToast({
        title: "Network Discovery Completed",
        message: `Merged client reports: found ${res?.devices_found ?? 0} devices.`,
        severity: "SUCCESS",
      });
      refetch();
    } catch (err: any) {
      addToast({
        title: "Scan Failed",
        message: err?.message || "Failed to trigger network scan.",
        severity: "CRITICAL",
      });
    } finally {
      setIsScanning(false);
    }
  };

  const handleActiveScan = async () => {
    const staringtime = Date.now();
    setIsActiveScanning(true);
    addToast({
      title: "Active ARP Scan Started",
      message: "Server is running ARP discovery — this may take 10–30 seconds…",
      severity: "INFO",
    });
    try {
      const res = await api.triggerActiveScan();
      const elapsed = ((Date.now() - staringtime) / 1000).toFixed(1);
      addToast({
        title: "Active Scan Completed",
        message: `ARP scan found ${res?.devices_found ?? 0} device(s) on the network. Elapsed time: ${elapsed}s.`,
        severity: "SUCCESS",
      });
      refetch();
    } catch (err: any) {
      addToast({
        title: "Active Scan Failed",
        message: err?.message || "Server ARP scan failed. Is the server running as root?",
        severity: "CRITICAL",
      });
    } finally {
      setIsActiveScanning(false);
    }
  };

  const handleGlobalActiveScan = async () => {
    setIsGlobalActiveScanning(true);
    addToast({
      title: "Global Active Scan Started",
      message: "Requesting an active ARP scan from every connected client…",
      severity: "INFO",
    });
    try {
      const res = await api.triggerGlobalActiveScan();
      setGlobalScan(res);
      addToast({
        title: "Global Active Scan Started",
        message: `${res.total_clients} client(s) queued; up to ${res.max_concurrent_clients} scan at once. Results will appear as clients finish.`,
        severity: "SUCCESS",
      });
      refetch();
    } catch (err: any) {
      addToast({
        title: "Global Active Scan Failed",
        message: err?.message || "Could not scan the connected clients.",
        severity: "CRITICAL",
      });
    } finally {
      setIsGlobalActiveScanning(false);
    }
  };

  const globalScanActive = Boolean(
    globalScan && ["started", "already_running", "pending", "running"].includes(globalScan.status),
  );
  const globalProgress = globalScan?.total_clients
    ? Math.round(((globalScan.completed + globalScan.failed + globalScan.skipped) / globalScan.total_clients) * 100)
    : 0;

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Latest Network Scan</h1>
          <p className="page-description">
            {scan
              ? `Completed ${formatDateTime(scan.completed_at)} · Found ${scan.devices_found} device(s)`
              : "Devices observed in the most recent network scan."}
          </p>
        </div>
        <div style={{ display: "flex", gap: "var(--space-2)", alignItems: "center" }}>
          <Button
            variant="primary"
            size="md"
            disabled={isScanning || isActiveScanning || isGlobalActiveScanning || globalScanActive}
            onClick={handleRunScan}
          >
            {isScanning ? "Scanning & Merging…" : " Run Scan (Merge Reports)"}
          </Button>
          <Button
            variant="secondary"
            size="md"
            disabled={isScanning || isActiveScanning || isGlobalActiveScanning}
            onClick={handleActiveScan}
            title="Runs a real ARP scan from the server — requires root. Takes 10–30s."
          >
            {isActiveScanning ? "Running ARP Scan…" : " Active Server Scan (ARP)"}
          </Button>
          <Button
            variant="secondary"
            size="md"
            disabled={isScanning || isActiveScanning || isGlobalActiveScanning}
            onClick={handleGlobalActiveScan}
            title="Requests an active ARP scan from every connected client."
          >
            {isGlobalActiveScanning
              ? "Scanning Connected Clients…"
              : globalScanActive
                ? " Global Scan Running…"
                : " Global Active Scan (Clients)"}
          </Button>
          <Button variant="quiet" size="sm" onClick={refetch}>
            Refresh
          </Button>
        </div>
      </div>

      {state.status === "error" && (
        <Notice variant="warning" title="Scan data is stale or unavailable">
          {state.staleData ? "Showing previously loaded scan. " : ""}
          {state.error.message}
          <Button
            variant="quiet"
            size="sm"
            onClick={refetch}
            style={{ marginLeft: "var(--space-2)" }}
          >
            Retry
          </Button>
        </Notice>
      )}

      {globalScan && (
        <Notice
          variant={globalScan.status === "partial" ? "warning" : "info"}
          title={`Global Network Scan · ${globalScan.status.replace("_", " ")}`}
        >
          <div style={{ display: "grid", gap: "var(--space-2)" }}>
            <span>
              {globalScan.completed} / {globalScan.total_clients} clients completed · {globalScan.devices_found} unique device(s) discovered
            </span>
            <div
              aria-label="Global scan progress"
              style={{ height: 8, borderRadius: 999, overflow: "hidden", background: "var(--surface-raised)" }}
            >
              <div style={{ width: `${globalProgress}%`, height: "100%", background: "var(--accent)", transition: "width 180ms ease" }} />
            </div>
            <span style={{ color: "var(--text-muted)", fontSize: "var(--font-sm)" }}>
              Running: {globalScan.running} · Pending: {globalScan.pending} · Failed: {globalScan.failed}
              {globalScan.skipped ? ` · Skipped: ${globalScan.skipped}` : ""}
            </span>
          </div>
        </Notice>
      )}

      {/* Filter and Search Bar */}
      <div
        style={{
          display: "flex",
          gap: "var(--space-3)",
          marginBottom: "var(--space-5)",
          flexWrap: "wrap",
        }}
      >
        <div
          style={{
            display: "flex",
            borderRadius: "var(--radius)",
            border: "1px solid var(--border)",
            overflow: "hidden",
            background: "var(--surface)",
          }}
        >
          {(["ALL", "MANAGED", "UNMANAGED"] as const).map((opt) => (
            <button
              key={opt}
              onClick={() => setFilter(opt)}
              aria-pressed={filter === opt}
              style={{
                padding: "0 var(--space-4)",
                minHeight: 36,
                border: "none",
                background: filter === opt ? "var(--primary)" : "transparent",
                color: filter === opt ? "#fff" : "var(--text-muted)",
                fontFamily: "var(--font-sans)",
                fontSize: "var(--font-sm)",
                fontWeight: filter === opt ? 600 : 400,
                cursor: "pointer",
                transition:
                  "background var(--transition-fast), color var(--transition-fast)",
              }}
            >
              {opt === "ALL"
                ? "All Devices"
                : opt === "MANAGED"
                  ? "Managed"
                  : "Unmanaged"}
            </button>
          ))}
        </div>

        <input
          type="search"
          placeholder="Filter by IP, MAC, hostname, or vendor…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label="Filter devices"
          style={{
            flex: "1 1 240px",
            padding: "0 var(--space-3)",
            height: 36,
            border: "1px solid var(--border)",
            borderRadius: "var(--radius)",
            fontFamily: "var(--font-sans)",
            fontSize: "var(--font-sm)",
            background: "var(--surface)",
            color: "var(--text)",
            outline: "none",
          }}
        />
      </div>

      {state.status === "idle" || state.status === "loading" ? (
        <SkeletonTable rows={8} columns={6} />
      ) : state.status === "error" && !state.staleData ? (
        <ErrorState
          title="Unable to load latest scan"
          message={state.error.message}
          onRetry={refetch}
        />
      ) : sortedDevices.length === 0 ? (
        <EmptyState
          icon="📡"
          title="No devices found"
          body={
            search || filter !== "ALL"
              ? "No devices match your current filters."
              : "No devices were observed in the latest scan."
          }
        />
      ) : (
        <DataTable
          columns={columns}
          data={sortedDevices}
          rowKey={(d) => d.mac_address}
          onRowClick={(d) =>
            navigate(`/network/devices/${encodeURIComponent(d.mac_address)}`)
          }
          aria-label="Latest scan devices"
          sortKey={sortKey}
          sortDir={sortDir}
          onSort={handleSort}
        />
      )}
    </div>
  );
}
