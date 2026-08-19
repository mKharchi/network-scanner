import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type ManagedClientSummary } from "../api/client";
import { useFetch } from "../hooks/useFetch";
import { OnlineBadge, OfflineBadge } from "../components/Badge";
import { Button } from "../components/Button";
import { DataTable, type Column } from "../components/DataTable";
import {
  SkeletonTable,
  ErrorState,
  EmptyState,
  Notice,
} from "../components/States";
import { formatRelative } from "../utils/format";

// ── Filter bar ────────────────────────────────────────────────────
interface FilterBarProps {
  stateFilter: string;
  onStateFilter: (v: string) => void;
  search: string;
  onSearch: (v: string) => void;
}

function FilterBar({
  stateFilter,
  onStateFilter,
  search,
  onSearch,
}: FilterBarProps) {
  return (
    <div
      style={{
        display: "flex",
        gap: "var(--space-3)",
        marginBottom: "var(--space-5)",
        flexWrap: "wrap",
      }}
    >
      {/* State toggle */}
      <div
        style={{
          display: "flex",
          borderRadius: "var(--radius)",
          border: "1px solid var(--border)",
          overflow: "hidden",
          background: "var(--surface)",
        }}
      >
        {[
          { value: "", label: "All" },
          { value: "ONLINE", label: "Online" },
          { value: "OFFLINE", label: "Offline" },
        ].map(({ value, label }) => (
          <button
            key={value}
            onClick={() => onStateFilter(value)}
            aria-pressed={stateFilter === value}
            style={{
              padding: "0 var(--space-4)",
              minHeight: 36,
              border: "none",
              background:
                stateFilter === value ? "var(--primary)" : "transparent",
              color: stateFilter === value ? "#fff" : "var(--text-muted)",
              fontFamily: "var(--font-sans)",
              fontSize: "var(--font-sm)",
              fontWeight: stateFilter === value ? 600 : 400,
              cursor: "pointer",
              transition:
                "background var(--transition-fast), color var(--transition-fast)",
            }}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Search */}
      <input
        type="search"
        placeholder="Search clients…"
        value={search}
        onChange={(e) => onSearch(e.target.value)}
        aria-label="Search clients"
        style={{
          flex: "1 1 200px",
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
  );
}

// ── Column definitions ────────────────────────────────────────────
const columns: Column<ManagedClientSummary>[] = [
  {
    key: "hostname",
    label: "Hostname",
    sortable: true,
    render: (c) => <span style={{ fontWeight: 500 }}>{c.hostname || "—"}</span>,
  },
  {
    key: "ip_address",
    label: "IP Address",
    mono: true,
    render: (c) => c.ip_address ?? null,
  },
  {
    key: "mac_address",
    label: "MAC",
    mono: true,
    render: (c) => c.mac_address,
  },
  {
    key: "connection",
    label: "Status",
    render: (c) =>
      c.connection.state === "ONLINE" ? <OnlineBadge /> : <OfflineBadge />,
  },
  {
    key: "os",
    label: "OS",
    render: (c) =>
      c.os.system ? `${c.os.system} ${c.os.release ?? ""}`.trim() : null,
  },
  {
    key: "connection_time",
    label: "Last seen",
    align: "right",
    render: (c) => (
      <span
        style={{
          fontSize: "var(--font-xs)",
          color: "var(--text-muted)",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {formatRelative(c.connection.last_connected_at)}
      </span>
    ),
  },
];

// ── Clients page ──────────────────────────────────────────────────
export function ClientsPage() {
  const navigate = useNavigate();
  const [stateFilter, setStateFilter] = useState("");
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState("hostname");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  const { state, refetch } = useFetch(
    () =>
      api.getClients({
        state: stateFilter || undefined,
        search: search || undefined,
      }),
    [stateFilter, search],
    ['app:client_status', 'client_status'],
  );

  const handleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  };

  const rawItems: ManagedClientSummary[] =
    state.status === "success"
      ? state.data.items
      : state.status === "error" && state.staleData
        ? state.staleData.items
        : [];

  // Client-side sort
  const items = [...rawItems].sort((a, b) => {
    let av = sortKey === "hostname" ? a.hostname : "";
    let bv = sortKey === "hostname" ? b.hostname : "";
    return sortDir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
  });

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Clients</h1>
          <p className="page-description">
            Registered monitoring agents and their current status.
          </p>
        </div>
        <Button variant="quiet" size="sm" onClick={refetch}>
          Refresh
        </Button>
      </div>

      {state.status === "error" && (
        <Notice variant="warning" title="Using stale data">
          {state.staleData ? "Last successful load is shown. " : ""}
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

      <FilterBar
        stateFilter={stateFilter}
        onStateFilter={setStateFilter}
        search={search}
        onSearch={setSearch}
      />

      {state.status === "idle" || state.status === "loading" ? (
        <SkeletonTable rows={6} columns={6} />
      ) : state.status === "error" && !state.staleData ? (
        <ErrorState
          title="Unable to load clients"
          message={state.error.message}
          onRetry={refetch}
        />
      ) : items.length === 0 ? (
        <EmptyState
          icon="💻"
          title="No managed clients registered"
          body="Monitoring agents will appear here once they connect to the server."
        />
      ) : (
        <DataTable
          columns={columns}
          data={items}
          rowKey={(c) => c.id}
          onRowClick={(c) => navigate(`/clients/${encodeURIComponent(c.id)}`)}
          aria-label="Managed clients"
          sortKey={sortKey}
          sortDir={sortDir}
          onSort={handleSort}
        />
      )}
    </div>
  );
}
