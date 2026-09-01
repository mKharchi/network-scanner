import { useState } from "react";
import { useToast } from "../hooks/useToast";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, type ManagedClientSummary } from "../api/client";
import { useFetch } from "../hooks/useFetch";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import { ClientStatusBadge } from "../components/Badge";
import { Button } from "../components/Button";
import { DataTable, type Column } from "../components/DataTable";
import {
  SkeletonTable,
  ErrorState,
  EmptyState,
  Notice,
} from "../components/States";
import { formatRelative } from "../utils/format";
import { MetricCard } from "../components/Card";
import { DeployPackagePanel } from "../components/DeployPackagePanel";
import "../styles/operations.css";

// ── Filter bar ────────────────────────────────────────────────────
interface FilterBarProps {
  stateFilter: string;
  onStateFilter: (v: string) => void;
  locationFilter: string;
  onLocationFilter: (v: string) => void;
  search: string;
  onSearch: (v: string) => void;
}

function FilterBar({
  stateFilter,
  onStateFilter,
  locationFilter,
  onLocationFilter,
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
          { value: "ISOLATED", label: "Isolated" },
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
          { value: "", label: "All locations" },
          { value: "unassigned", label: "Unassigned" },
        ].map(({ value, label }) => (
          <button
            key={value || "all-locations"}
            onClick={() => onLocationFilter(value)}
            aria-pressed={locationFilter === value}
            style={{
              padding: "0 var(--space-4)",
              minHeight: 36,
              border: "none",
              background:
                locationFilter === value ? "var(--primary)" : "transparent",
              color: locationFilter === value ? "#fff" : "var(--text-muted)",
              fontFamily: "var(--font-sans)",
              fontSize: "var(--font-sm)",
              fontWeight: locationFilter === value ? 600 : 400,
              cursor: "pointer",
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
function buildClientColumns(
  onAssign: (clientId: string) => void,
  onAutoLocate: (client: ManagedClientSummary) => void,
  autoLocatingClientId: string | null,
  selectedIds: Set<string>,
  onToggleSelect: (clientId: string, checked: boolean) => void,
): Column<ManagedClientSummary>[] {
  return [
  {
    key: "select",
    label: "Select",
    render: (c) => (
      <input
        type="checkbox"
        checked={selectedIds.has(c.id)}
        aria-label={`Select ${c.hostname || c.id}`}
        onClick={(event) => event.stopPropagation()}
        onChange={(event) => onToggleSelect(c.id, event.target.checked)}
      />
    ),
  },
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
    key: "client_version",
    label: "Client version",
    mono: true,
    render: (c) => c.client_version ?? "—",
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
    render: (c) => <ClientStatusBadge state={c.connection.state} />,
  },
  {
    key: "location",
    label: "Location",
    render: (c) => (
      <span style={{ color: c.location ? "var(--text)" : "var(--warning)" }}>
        {c.location?.label || "Location not assigned"}
      </span>
    ),
  },
  {
    key: "assign",
    label: "",
    render: (c) =>
      c.location ? null : (
        <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
          <Button
            variant="secondary"
            size="sm"
            disabled={autoLocatingClientId !== null}
            onClick={(event) => {
              event.stopPropagation();
              onAutoLocate(c);
            }}
          >
            {autoLocatingClientId === c.id ? "Locating…" : "Try auto"}
          </Button>
          <Button
            variant="quiet"
            size="sm"
            disabled={autoLocatingClientId !== null}
            onClick={(event) => {
              event.stopPropagation();
              onAssign(c.id);
            }}
          >
            Assign
          </Button>
        </div>
      ),
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
}

// ── Clients page ──────────────────────────────────────────────────
export function ClientsPage() {
  const navigate = useNavigate();
  const { addToast } = useToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const [stateFilter, setStateFilter] = useState("");
  const [locationFilter, setLocationFilter] = useState(searchParams.get("location") || "");
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search);
  const [sortKey, setSortKey] = useState("hostname");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [autoLocatingClientId, setAutoLocatingClientId] = useState<string | null>(null);
  const [selectedClientIds, setSelectedClientIds] = useState<Set<string>>(new Set());
  const [showBulkDeploy, setShowBulkDeploy] = useState(false);

  const { state, refetch } = useFetch(
    () =>
      api.getClients({
        state: stateFilter || undefined,
        search: debouncedSearch || undefined,
        location: locationFilter || undefined,
      }),
    [stateFilter, debouncedSearch, locationFilter],
    ['app:client_status'],
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

  const startManualAssignment = (clientId: string) => {
    navigate(`/locations?assign=${encodeURIComponent(clientId)}`);
  };

  const tryAutomaticLocation = async (client: ManagedClientSummary) => {
    setAutoLocatingClientId(client.id);
    try {
      const outcome = await api.autoAssignClientLocation(client.id);
      const location = outcome.location as { label?: string } | undefined;
      if (outcome.assigned === true && location?.label) {
        addToast({
          title: "Automatic location assigned",
          message: `${client.hostname || client.id} was placed at ${location.label}. Open the Center layout to verify and confirm it.`,
          severity: "SUCCESS",
          action: {
            label: "Review location",
            onClick: () => navigate("/locations"),
          },
        });
      } else {
        addToast({
          title: "Automatic location not assigned",
          message: `${client.hostname || client.id} remains unassigned. Use Assign to place it manually.`,
          severity: "HIGH",
        });
      }
      refetch();
    } catch (err: any) {
      addToast({
        title: "Automatic location failed",
        message: err?.message || "Unable to calculate an automatic location.",
        severity: "CRITICAL",
      });
    } finally {
      setAutoLocatingClientId(null);
    }
  };

  const columns = buildClientColumns(
    startManualAssignment,
    tryAutomaticLocation,
    autoLocatingClientId,
    selectedClientIds,
    (clientId, checked) => {
      setSelectedClientIds((current) => {
        const next = new Set(current);
        if (checked) next.add(clientId);
        else next.delete(clientId);
        return next;
      });
    },
  );

  const selectedOnlineTargets = items
    .filter((client) => selectedClientIds.has(client.id) && client.connection.state === "ONLINE")
    .map((client) => client.id);

  const onlineCount = rawItems.filter((client) => client.connection.state === "ONLINE").length;
  const isolatedCount = rawItems.filter((client) => client.connection.state === "ISOLATED").length;
  const assignedCount = rawItems.filter((client) => client.location !== null).length;

  return (
    <div>
      <div className="page-header operations-page-header">
        <div className="client-page-header__copy">
          <span className="eyebrow eyebrow--accent">NETWORK INTELLIGENCE / CLIENTS</span>
          <h1 className="page-title">Monitoring agents</h1>
          <p className="page-description">Manage the agents that collect network evidence, health signals, and diagnostics across your infrastructure.</p>
        </div>
        
      </div>

      <div className="operations-metric-grid" aria-label="Client fleet overview">
        <MetricCard label="Registered agents" value={rawItems.length} context="Known monitoring clients" />
        <MetricCard label="Online" value={onlineCount} valueVariant="success" context="Currently connected" />
        <MetricCard label="Isolated" value={isolatedCount} valueVariant="danger" context="Network access restricted" />
        <MetricCard label="Located" value={assignedCount} valueVariant="info" context="Assigned to a physical position" />
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
        locationFilter={locationFilter}
        onLocationFilter={(value) => {
          setLocationFilter(value);
          const next = new URLSearchParams(searchParams);
          if (value) next.set("location", value);
          else next.delete("location");
          setSearchParams(next, { replace: true });
        }}
        search={search}
        onSearch={setSearch}
      />

      {selectedClientIds.size > 0 && (
        <div
          style={{
            display: "flex",
            gap: "var(--space-3)",
            alignItems: "center",
            marginBottom: "var(--space-4)",
            flexWrap: "wrap",
          }}
        >
          <span style={{ fontSize: "var(--font-sm)", color: "var(--text-muted)" }}>
            {selectedClientIds.size} selected · {selectedOnlineTargets.length} online
          </span>
          <Button
            variant="secondary"
            size="sm"
            onClick={() =>
              setSelectedClientIds(new Set(items.map((client) => client.id)))
            }
          >
            Select visible
          </Button>
          <Button variant="quiet" size="sm" onClick={() => setSelectedClientIds(new Set())}>
            Clear
          </Button>
          <Button
            variant="primary"
            size="sm"
            disabled={selectedOnlineTargets.length === 0}
            onClick={() => setShowBulkDeploy((open) => !open)}
          >
            {showBulkDeploy ? "Hide deploy panel" : "Deploy package…"}
          </Button>
        </div>
      )}

      {showBulkDeploy && selectedOnlineTargets.length > 0 && (
        <div style={{ marginBottom: "var(--space-5)" }}>
          <DeployPackagePanel
            targets={selectedOnlineTargets}
            title="Bulk package deployment"
            description="Deploy the same zip archive to every selected online client. Progress is tracked per client."
            onCompleted={(action) => {
              addToast({
                title:
                  action.status === "SUCCESS"
                    ? "Bulk deployment complete"
                    : action.status === "PARTIAL_SUCCESS"
                      ? "Bulk deployment partially complete"
                      : "Bulk deployment failed",
                message: `Action ${action.action_id} finished with status ${action.status}.`,
                severity:
                  action.status === "SUCCESS"
                    ? "SUCCESS"
                    : action.status === "PARTIAL_SUCCESS"
                      ? "HIGH"
                      : "CRITICAL",
              });
            }}
          />
        </div>
      )}

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
          title={locationFilter === "unassigned" ? "No unassigned clients" : "No managed clients registered"}
          body={locationFilter === "unassigned"
            ? "Failed or pending automatic localization appears here until an administrator assigns a seat from the center layout."
            : "Monitoring agents will appear here once they connect to the server."}
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
