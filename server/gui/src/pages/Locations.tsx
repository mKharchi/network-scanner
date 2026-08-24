import { useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import {
  api,
  type ClientLocation,
  type FloorLayout,
  type FloorTable,
  type ManagedClientSummary,
  type PhysicalNeighbor,
} from "../api/client";
import { useFetch } from "../hooks/useFetch";
import { useToast } from "../hooks/useToast";
import { Button } from "../components/Button";
import { SectionCard } from "../components/Card";
import { EmptyState, ErrorState, Skeleton } from "../components/States";
import {
  stationVisual,
  STATION_VISUAL_LABEL,
  type StationVisual,
} from "../utils/stationVisual";
import "../styles/floor-visualization.css";

const NEIGHBOR_RELATIONSHIP_LABELS: Record<
  PhysicalNeighbor["relationship"],
  string
> = {
  same_row: "Same column",
  same_table: "Facing seat",
  neighboring_table: "Neighboring table",
  same_zone: "Same room",
};

type StatusFilter = "all" | StationVisual;

function locationDescription(location: ClientLocation): string {
  const parts = [
    location.zone_name || location.zone_type,
    location.aisle != null ? `Aisle ${location.aisle}` : null,
    location.table != null ? `Table ${location.table}` : null,
    (location.column ?? location.row) != null
      ? `Column ${location.column ?? location.row}`
      : null,
    location.position != null ? `Position ${location.position}` : null,
  ];
  return parts.filter(Boolean).join(" · ");
}

function stationKey(location: ClientLocation): string {
  return String(location.id);
}

export function LocationsPage() {
  const navigate = useNavigate();
  const { addToast } = useToast();
  const [selectedFloor, setSelectedFloor] = useState(1);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [aisleFilter, setAisleFilter] = useState<number | "all">("all");
  const [tableFilter, setTableFilter] = useState<number | "all">("all");
  const [selectedLocationId, setSelectedLocationId] = useState<number | null>(
    null,
  );
  const [selectedClientIds, setSelectedClientIds] = useState<string[]>([]);
  const [actionLoading, setActionLoading] = useState(false);

  const { state, refetch } = useFetch<FloorLayout>(
    () => api.getLocationLayout(selectedFloor),
    [selectedFloor],
    ["app:client_status"],
  );

  const layout: FloorLayout | null =
    state.status === "success"
      ? state.data
      : state.status === "error"
        ? state.staleData || null
        : null;

  const selectedLocation = useMemo(
    () => findLocation(layout, selectedLocationId),
    [layout, selectedLocationId],
  );

  const { state: clientState } = useFetch(
    selectedLocation?.client_id
      ? () => api.getClient(selectedLocation.client_id!)
      : null,
    [selectedLocation?.client_id],
  );
  const { state: neighborsState } = useFetch<{ items: PhysicalNeighbor[] }>(
    selectedLocation?.client_id
      ? () => api.getPhysicalNeighbors(selectedLocation.client_id!)
      : null,
    [selectedLocation?.client_id],
  );

  const neighborIds = new Set(
    neighborsState.status === "success"
      ? neighborsState.data.items.map((neighbor) => neighbor.client_id)
      : [],
  );

  const aisleOptions =
    layout?.aisles
      .map((aisle) => aisle.aisle)
      .filter((value): value is number => value != null) || [];
  const tableOptions = Array.from(
    new Set(
      (layout?.aisles || [])
        .flatMap((aisle) => aisle.tables.map((table) => table.table))
        .filter((value): value is number => value != null),
    ),
  );

  const visibleClientIds = collectVisibleClientIds(layout, {
    statusFilter,
    aisleFilter,
    tableFilter,
  });

  const runBulkAction = async (
    actionType: string,
    parameters: Record<string, unknown> = {},
  ) => {
    if (!selectedClientIds.length) return;
    setActionLoading(true);
    try {
      const action = await api.createAction({
        action_type: actionType,
        targets: selectedClientIds,
        parameters,
      });
      addToast({
        title: "Action queued",
        message: `${actionType} sent to ${selectedClientIds.length} client${selectedClientIds.length === 1 ? "" : "s"} (${action.status}).`,
        severity: "SUCCESS",
      });
      refetch();
    } catch (err: any) {
      addToast({
        title: "Action failed",
        message: err?.message || "Unable to create the action.",
        severity: "CRITICAL",
      });
    } finally {
      setActionLoading(false);
    }
  };

  const runSingleAction = async (
    actionType: string,
    parameters: Record<string, unknown> = {},
  ) => {
    if (!selectedLocation?.client_id) return;
    setActionLoading(true);
    try {
      await api.runClientCommand(
        selectedLocation.client_id,
        actionType,
        parameters,
      );
      addToast({
        title: "Action queued",
        message: `${actionType} sent to ${selectedLocation.client_id}.`,
        severity: "SUCCESS",
      });
      refetch();
    } catch (err: any) {
      addToast({
        title: "Action failed",
        message: err?.message || "Unable to run the action.",
        severity: "CRITICAL",
      });
    } finally {
      setActionLoading(false);
    }
  };

  if (state.status === "idle" || state.status === "loading") {
    return <Skeleton />;
  }
  if (state.status === "error" && !layout) {
    return (
      <ErrorState
        title="Unable to load floor layout"
        message={state.error.message}
        onRetry={refetch}
      />
    );
  }
  if (!layout) {
    return (
      <EmptyState
        title="No layout available"
        body="Create physical positions before viewing the center."
      />
    );
  }

  const client: ManagedClientSummary | null =
    clientState.status === "success" ? clientState.data.client : null;
  const floors = layout.available_floors.length
    ? layout.available_floors
    : [0, 1, 2];
  const emptyFloor = !layout.rooms.length && !layout.aisles.length;

  return (
    <div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          gap: "var(--space-3)",
          alignItems: "center",
          marginBottom: "var(--space-5)",
          flexWrap: "wrap",
        }}
      >
        <div>
          <h1 className="page-title">Center layout</h1>
          <p
            style={{ color: "var(--text-muted)", marginTop: "var(--space-1)" }}
          >
            Floors, rooms, aisles, tables, and the 56 PC seats are seeded
            automatically. Assign clients to empty positions from a client
            page.
          </p>
        </div>
        <div style={{ display: "flex", gap: "var(--space-2)" }}>
          <Button variant="quiet" size="sm" onClick={refetch}>
            Refresh
          </Button>
        </div>
      </div>

      {state.status === "error" && (
        <div style={{ marginBottom: "var(--space-4)" }}>
          <div className="notice notice--warning">
            Showing stale layout data. {state.error.message}
          </div>
        </div>
      )}

      <div
        style={{
          display: "flex",
          gap: "var(--space-2)",
          marginBottom: "var(--space-4)",
          flexWrap: "wrap",
        }}
      >
        {floors.map((floor) => (
          <Button
            key={floor}
            variant={selectedFloor === floor ? "primary" : "quiet"}
            size="sm"
            onClick={() => {
              setSelectedFloor(floor);
              setSelectedLocationId(null);
              setSelectedClientIds([]);
              setAisleFilter("all");
              setTableFilter("all");
            }}
          >
            Floor {floor}
          </Button>
        ))}
      </div>

      <div className="floor-vis__filters">
        <select
          aria-label="Filter by aisle"
          value={aisleFilter}
          onChange={(event) =>
            setAisleFilter(
              event.target.value === "all" ? "all" : Number(event.target.value),
            )
          }
        >
          <option value="all">All aisles</option>
          {aisleOptions.map((aisle) => (
            <option key={aisle} value={aisle}>
              Aisle {aisle}
            </option>
          ))}
        </select>
        <select
          aria-label="Filter by table"
          value={tableFilter}
          onChange={(event) =>
            setTableFilter(
              event.target.value === "all" ? "all" : Number(event.target.value),
            )
          }
        >
          <option value="all">All tables</option>
          {tableOptions.map((table) => (
            <option key={table} value={table}>
              Table {table}
            </option>
          ))}
        </select>
        <select
          aria-label="Filter by status"
          value={statusFilter}
          onChange={(event) =>
            setStatusFilter(event.target.value as StatusFilter)
          }
        >
          <option value="all">All statuses</option>
          {(
            [
              "healthy",
              "warning",
              "critical",
              "isolated",
              "offline",
              "empty",
            ] as StationVisual[]
          ).map((status) => (
            <option key={status} value={status}>
              {STATION_VISUAL_LABEL[status]}
            </option>
          ))}
        </select>
        <Button
          variant="secondary"
          size="sm"
          disabled={!visibleClientIds.length}
          onClick={() => setSelectedClientIds(visibleClientIds)}
        >
          Select visible clients ({visibleClientIds.length})
        </Button>
        {selectedClientIds.length > 0 && (
          <>
            <Button
              variant="quiet"
              size="sm"
              onClick={() => setSelectedClientIds([])}
            >
              Clear selection
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled={actionLoading}
              onClick={() => runBulkAction("SCREENSHOT", { format: "png" })}
            >
              Screenshot
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled={actionLoading}
              onClick={() => runBulkAction("REFRESH_HEALTH")}
            >
              Refresh health
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled={actionLoading}
              onClick={() => runBulkAction("COLLECT_DIAGNOSTICS")}
            >
              Diagnostics
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled={actionLoading}
              onClick={() => runBulkAction("RESTART", { delay_seconds: 5 })}
            >
              Restart
            </Button>
            <Button
              variant="danger"
              size="sm"
              disabled={actionLoading}
              onClick={() => runBulkAction("SHUTDOWN", { delay_seconds: 5 })}
            >
              Shutdown
            </Button>
          </>
        )}
      </div>

      <ul className="floor-vis__legend">
        {(
          [
            "healthy",
            "warning",
            "critical",
            "isolated",
            "offline",
            "empty",
          ] as StationVisual[]
        ).map((status) => (
          <li key={status} className="floor-vis__legend-item">
            <span
              className={`station station--${status}`}
              style={{ width: "0.9rem", minHeight: "0.9rem" }}
              aria-hidden="true"
            />
            {STATION_VISUAL_LABEL[status]}
          </li>
        ))}
      </ul>

      {emptyFloor ? (
        <EmptyState
          title={
            selectedFloor === 0
              ? "Floor 0 has no PCs"
              : "No positions on this floor"
          }
          body={
            selectedFloor === 0
              ? "This floor can be shown, but workstations are not visualized here."
              : "This floor has no seeded aisles or PC positions."
          }
        />
      ) : (
        <div className="floor-vis">
          <div>
            {layout.rooms.length > 0 && (
              <div className="floor-vis__rooms">
                {layout.rooms.map((room) => (
                  <button
                    key={stationKey(room)}
                    type="button"
                    className="floor-vis__room"
                    onClick={() => setSelectedLocationId(room.id)}
                  >
                    {room.zone_name || room.label}
                  </button>
                ))}
              </div>
            )}
            <div className="floor-vis__aisles">
              {layout.aisles.map((aisle) => (
                <section key={String(aisle.aisle)} className="floor-vis__aisle">
                  <div className="floor-vis__aisle-label">
                    Aisle {aisle.aisle ?? "—"}
                  </div>
                  <div className="floor-vis__tables">
                    {aisle.tables.map((table) => (
                      <div
                        key={`${table.kind || "table"}-${String(table.table)}`}
                        className={`floor-vis__table${table.kind === "stairs" ? " floor-vis__table--stairs" : ""}`}
                      >
                        {table.kind === "stairs" ? (
                          <button
                            type="button"
                            className="floor-vis__stairs"
                            onClick={() =>
                              table.location &&
                              setSelectedLocationId(table.location.id)
                            }
                          >
                            <span className="floor-vis__table-label">
                              {table.label || "Stairs"}
                            </span>
                            <span>Not a PC position</span>
                          </button>
                        ) : (
                          <>
                            <div className="floor-vis__table-label">
                              Table {table.table ?? "—"}
                            </div>
                            <div className="floor-vis__columns">
                              {tableColumns(table).map((column, index) => (
                                <div
                                  key={String(column.column ?? column.row ?? index)}
                                  className="floor-vis__column"
                                >
                                  <div className="floor-vis__row-label">
                                    C{column.column ?? column.row ?? "—"}
                                  </div>
                                  <div className="floor-vis__stations">
                                    {column.stations.map((station) => {
                                      const visual = stationVisual({
                                        client_id: station.client_id,
                                        client_state: station.client_state,
                                        health_status:
                                          station.health_status ||
                                          station.health?.status,
                                        showsClients: layout.shows_clients,
                                      });
                                      const visible = stationMatches(
                                        station,
                                        visual,
                                        { statusFilter, aisleFilter, tableFilter },
                                      );
                                      const selected =
                                        selectedLocationId === station.id ||
                                        (station.client_id != null &&
                                          selectedClientIds.includes(
                                            station.client_id,
                                          ));
                                      const neighbor =
                                        station.client_id != null &&
                                        neighborIds.has(station.client_id);
                                      return (
                                        <button
                                          key={stationKey(station)}
                                          type="button"
                                          className={[
                                            "station",
                                            `station--${visual}`,
                                            visible ? "" : "station--dim",
                                            selected ? "station--selected" : "",
                                            neighbor ? "station--neighbor" : "",
                                          ]
                                            .filter(Boolean)
                                            .join(" ")}
                                          title={`${station.label} · ${STATION_VISUAL_LABEL[visual]}`}
                                          aria-label={`${station.label}, ${STATION_VISUAL_LABEL[visual]}`}
                                          onClick={() =>
                                            setSelectedLocationId(station.id)
                                          }
                                        >
                                          <span className="station__name">
                                            {stationSeatLabel(
                                              station,
                                              layout.shows_clients,
                                            )}
                                          </span>
                                          <span className="station__meta">
                                            {layout.shows_clients && station.client_id
                                              ? STATION_VISUAL_LABEL[visual]
                                              : `P${station.position ?? "—"}`}
                                          </span>
                                        </button>
                                      );
                                    })}
                                  </div>
                                </div>
                              ))}
                            </div>
                          </>
                        )}
                      </div>
                    ))}
                  </div>
                </section>
              ))}
            </div>
          </div>

          <SectionCard
            title={selectedLocation ? selectedLocation.label : "Seat details"}
            className="floor-vis__panel"
          >
            {!selectedLocation ? (
              <div style={{ color: "var(--text-muted)" }}>
                Select a PC position to inspect it.
              </div>
            ) : (
              <div>
                <div style={{ color: "var(--text-muted)" }}>
                  {locationDescription(selectedLocation)}
                </div>
                <dl
                  className="floor-vis__panel-grid"
                  style={{ marginTop: "var(--space-3)" }}
                >
                  <PanelRow
                    label="Hostname"
                    value={
                      client?.hostname ||
                      selectedLocation.client_id ||
                      "Empty seat"
                    }
                  />
                  <PanelRow label="IP" value={client?.ip_address || "—"} />
                  <PanelRow label="MAC" value={client?.mac_address || "—"} />
                  <PanelRow label="OS" value={client?.os.system || "—"} />
                  <PanelRow
                    label="Floor"
                    value={String(selectedLocation.floor)}
                  />
                  <PanelRow
                    label="Aisle"
                    value={selectedLocation.aisle ?? "—"}
                  />
                  <PanelRow
                    label="Table"
                    value={selectedLocation.table ?? "—"}
                  />
                  <PanelRow
                    label="Column"
                    value={selectedLocation.column ?? selectedLocation.row ?? "—"}
                  />
                  <PanelRow
                    label="Position"
                    value={selectedLocation.position ?? "—"}
                  />
                  <PanelRow
                    label="Health"
                    value={
                      STATION_VISUAL_LABEL[
                        stationVisual({
                          client_id: selectedLocation.client_id,
                          client_state: selectedLocation.client_state,
                          health_status:
                            selectedLocation.health_status ||
                            selectedLocation.health?.status,
                          showsClients: layout.shows_clients,
                        })
                      ]
                    }
                  />
                  <PanelRow
                    label="CPU"
                    value={formatPercent(selectedLocation.health?.cpu_percent)}
                  />
                  <PanelRow
                    label="Memory"
                    value={formatPercent(
                      selectedLocation.health?.memory_percent,
                    )}
                  />
                  <PanelRow
                    label="Disk"
                    value={formatPercent(selectedLocation.health?.disk_percent)}
                  />
                  <PanelRow
                    label="Isolation"
                    value={
                      client?.connection.isolation?.reason ||
                      client?.connection.state ||
                      selectedLocation.client_state ||
                      "—"
                    }
                  />
                  <PanelRow
                    label="Last seen"
                    value={client?.connection.last_connected_at || "—"}
                  />
                </dl>

                {neighborsState.status === "success" &&
                  neighborsState.data.items.length > 0 && (
                    <div style={{ marginTop: "var(--space-4)" }}>
                      <div className="floor-vis__table-label">
                        Physical neighbors
                      </div>
                      <div
                        style={{
                          display: "grid",
                          gap: "var(--space-2)",
                          marginTop: "var(--space-2)",
                        }}
                      >
                        {neighborsState.data.items.map((neighbor) => (
                          <button
                            key={neighbor.client_id}
                            type="button"
                            onClick={() =>
                              navigate(
                                `/clients/${encodeURIComponent(neighbor.client_id)}`,
                              )
                            }
                            style={{
                              textAlign: "left",
                              border: 0,
                              padding: 0,
                              background: "transparent",
                              color: "var(--primary)",
                              cursor: "pointer",
                            }}
                          >
                            {neighbor.hostname} ·{" "}
                            {
                              NEIGHBOR_RELATIONSHIP_LABELS[
                                neighbor.relationship
                              ]
                            }
                          </button>
                        ))}
                      </div>
                    </div>
                  )}

                {selectedLocation.client_id && layout.shows_clients && (
                  <div className="floor-vis__actions">
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={actionLoading}
                      onClick={() =>
                        runSingleAction("SCREENSHOT", { format: "png" })
                      }
                    >
                      Screenshot
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={actionLoading}
                      onClick={() => runSingleAction("REFRESH_HEALTH")}
                    >
                      Refresh health
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={actionLoading}
                      onClick={() => runSingleAction("COLLECT_DIAGNOSTICS")}
                    >
                      Diagnostics
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={actionLoading}
                      onClick={() =>
                        runSingleAction("RESTART", { delay_seconds: 5 })
                      }
                    >
                      Restart
                    </Button>
                    <Button
                      variant="danger"
                      size="sm"
                      disabled={actionLoading}
                      onClick={() =>
                        runSingleAction("SHUTDOWN", { delay_seconds: 5 })
                      }
                    >
                      Shutdown
                    </Button>
                    <Button
                      variant="danger"
                      size="sm"
                      disabled={actionLoading}
                      onClick={() => runSingleAction("ISOLATE_DEVICE")}
                    >
                      Isolate
                    </Button>
                    <Button
                      variant="quiet"
                      size="sm"
                      onClick={() =>
                        navigate(
                          `/clients/${encodeURIComponent(selectedLocation.client_id!)}`,
                        )
                      }
                    >
                      Open client
                    </Button>
                  </div>
                )}
              </div>
            )}
          </SectionCard>
        </div>
      )}
    </div>
  );
}

function formatPercent(value: number | null | undefined): string {
  return typeof value === "number" ? `${Math.round(value)}%` : "—";
}

function PanelRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="floor-vis__panel-row">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function tableColumns(table: FloorTable) {
  return table.columns?.length ? table.columns : table.rows || [];
}

function stationSeatLabel(
  station: ClientLocation,
  showsClients: boolean,
): string {
  if (!showsClients || !station.client_id) return "EMPTY";
  return station.hostname || station.client_id;
}

function findLocation(
  layout: FloorLayout | null,
  locationId: number | null,
): ClientLocation | null {
  if (!layout || locationId == null) return null;
  for (const room of layout.rooms) {
    if (room.id === locationId) return room;
  }
  for (const aisle of layout.aisles) {
    for (const table of aisle.tables) {
      if (table.location?.id === locationId) return table.location;
      for (const column of tableColumns(table)) {
        for (const station of column.stations) {
          if (station.id === locationId) return station;
        }
      }
    }
  }
  return null;
}

function stationMatches(
  station: ClientLocation,
  visual: StationVisual,
  filters: {
    statusFilter: StatusFilter;
    aisleFilter: number | "all";
    tableFilter: number | "all";
  },
): boolean {
  if (filters.statusFilter !== "all" && visual !== filters.statusFilter)
    return false;
  if (filters.aisleFilter !== "all" && station.aisle !== filters.aisleFilter)
    return false;
  if (filters.tableFilter !== "all" && station.table !== filters.tableFilter)
    return false;
  return true;
}

function collectVisibleClientIds(
  layout: FloorLayout | null,
  filters: {
    statusFilter: StatusFilter;
    aisleFilter: number | "all";
    tableFilter: number | "all";
  },
): string[] {
  if (!layout?.shows_clients) return [];
  const ids: string[] = [];
  for (const aisle of layout.aisles) {
    for (const table of aisle.tables) {
      for (const column of tableColumns(table)) {
        for (const station of column.stations) {
          if (!station.client_id) continue;
          const visual = stationVisual({
            client_id: station.client_id,
            client_state: station.client_state,
            health_status: station.health_status || station.health?.status,
            showsClients: true,
          });
          if (stationMatches(station, visual, filters))
            ids.push(station.client_id);
        }
      }
    }
  }
  return ids;
}
