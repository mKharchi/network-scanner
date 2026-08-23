import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  api,
  type GlobalNeighbourhoodCollection,
  type NetworkDeviceSummary,
} from "../api/client";
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

export function AllDevicesPage() {
  const navigate = useNavigate();
  const [filter, setFilter] = useState<"ALL" | "MANAGED" | "UNMANAGED">("ALL");
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState("last_seen");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const { state, refetch } = useFetch(
    () => api.listNetworkDevices({ limit: 500 }),
    [],
    ["app:network_update", "network_update", "client_neighbourhood_update"]
  );

  const handleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  };

  const rawDevices: NetworkDeviceSummary[] =
    state.status === "success"
      ? state.data.devices
      : state.status === "error" && state.staleData
        ? state.staleData.devices
        : [];

  const totalCount =
    state.status === "success"
      ? state.data.total
      : state.status === "error" && state.staleData
        ? state.staleData.total
        : rawDevices.length;

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
    } else if (sortKey === "first_seen") {
      av = a.first_seen ?? "";
      bv = b.first_seen ?? "";
    } else if (sortKey === "last_seen") {
      av = a.last_seen ?? "";
      bv = b.last_seen ?? "";
    }
    return sortDir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
  });

  const columns: Column<NetworkDeviceSummary>[] = [
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
      key: "first_seen",
      label: "First Seen",
      sortable: true,
      render: (d) =>
        d.first_seen ? (
          <div style={{ display: "flex", flexDirection: "column" }}>
            <span style={{ fontSize: "var(--font-xs)", fontWeight: 500, color: "var(--text)" }}>
              {formatDateTime(d.first_seen)}
            </span>
            <span style={{ fontSize: "11px", color: "var(--text-muted)" }}>
              {formatRelative(d.first_seen)}
            </span>
          </div>
        ) : null,
    },
    {
      key: "last_seen",
      label: "Last Seen",
      sortable: true,
      align: "right",
      render: (d) => (
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end" }}>
          <span style={{ fontSize: "var(--font-xs)", fontWeight: 500, color: "var(--text)" }}>
            {formatDateTime(d.last_seen)}
          </span>
          <span style={{ fontSize: "11px", color: "var(--text-muted)" }}>
            {formatRelative(d.last_seen)}
          </span>
        </div>
      ),
    },
  ];

  const { addToast } = useToast();
  const [isCollectingNeighbourhoods, setIsCollectingNeighbourhoods] = useState(false);
  const [neighbourhoodCollection, setNeighbourhoodCollection] =
    useState<GlobalNeighbourhoodCollection | null>(null);

  const handleCollectAllNeighbourhoods = async () => {
    setIsCollectingNeighbourhoods(true);
    try {
      let collection = await api.startGlobalNeighbourhoodCollection();
      setNeighbourhoodCollection(collection);

      while (
        collection.status === "started" ||
        collection.status === "already_running" ||
        collection.status === "pending" ||
        collection.status === "running"
      ) {
        await new Promise((resolve) => window.setTimeout(resolve, 750));
        collection = await api.getGlobalNeighbourhoodCollection(collection.id);
        setNeighbourhoodCollection(collection);
      }

      addToast({
        title:
          collection.status === "completed"
            ? "Neighbourhood collection complete"
            : "Neighbourhood collection partially complete",
        message: `${collection.clients_succeeded}/${collection.clients_requested} clients responded; ${collection.devices_discovered} device(s) discovered.`,
        severity: collection.status === "completed" ? "SUCCESS" : "INFO",
      });
      refetch();
    } catch (err: any) {
      addToast({
        title: "Neighbourhood collection failed",
        message: err?.message || "Could not start or monitor global neighbourhood collection.",
        severity: "CRITICAL",
      });
    } finally {
      setIsCollectingNeighbourhoods(false);
    }
  };

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">All Known Devices</h1>
          <p className="page-description">
            Comprehensive registry of all devices discovered across all client neighbourhood scans ({totalCount} total).
          </p>
        </div>
        <div style={{ display: "flex", gap: "var(--space-2)", alignItems: "center" }}>
          <Button
            variant="primary"
            size="md"
            disabled={isCollectingNeighbourhoods}
            onClick={handleCollectAllNeighbourhoods}
          >
            {isCollectingNeighbourhoods
              ? "Collecting Client Neighbourhoods…"
              : "Collect All Client Neighbourhoods"}
          </Button>
          <Button variant="quiet" size="sm" onClick={refetch}>
            Refresh
          </Button>
        </div>
      </div>

      {neighbourhoodCollection && (
        <div style={{ marginBottom: "var(--space-4)" }}>
          <Notice
            variant={neighbourhoodCollection.status === "completed" ? "success" : "info"}
            title="Global neighbourhood collection"
          >
            {neighbourhoodCollection.status === "started" ||
            neighbourhoodCollection.status === "pending" ||
            neighbourhoodCollection.status === "running"
              ? `Collecting from ${neighbourhoodCollection.clients_requested} client(s): ${neighbourhoodCollection.buckets_completed}/${neighbourhoodCollection.buckets_total} buckets completed.`
              : `${neighbourhoodCollection.clients_succeeded}/${neighbourhoodCollection.clients_requested} clients succeeded; ${neighbourhoodCollection.clients_timed_out} timed out; ${neighbourhoodCollection.clients_failed} failed; ${neighbourhoodCollection.devices_discovered} device(s) discovered.`}
          </Notice>
        </div>
      )}

      {state.status === "error" && (
        <Notice variant="warning" title="Device data is stale or unavailable">
          {state.staleData ? "Showing previously loaded devices. " : ""}
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
        <SkeletonTable rows={8} columns={7} />
      ) : state.status === "error" && !state.staleData ? (
        <ErrorState
          title="Unable to load devices"
          message={state.error.message}
          onRetry={refetch}
        />
      ) : sortedDevices.length === 0 ? (
        <EmptyState
          icon="🖥️"
          title="No devices found"
          body={
            search || filter !== "ALL"
              ? "No devices match your current filters."
              : "No devices recorded in the database yet."
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
          aria-label="All network devices"
          sortKey={sortKey}
          sortDir={sortDir}
          onSort={handleSort}
        />
      )}
    </div>
  );
}
