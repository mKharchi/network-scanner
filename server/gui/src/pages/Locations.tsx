import { useMemo, useState, type ReactNode } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  api,
  type CalibrationReport,
  type ClientLocation,
  type FloorLayout,
  type FloorTable,
  type ManagedClientSummary,
  type PhysicalNeighbor,
  type UnassignedClientQueueItem,
} from "../api/client";
import { useFetch } from "../hooks/useFetch";
import { useToast } from "../hooks/useToast";
import { Button } from "../components/Button";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { SectionCard } from "../components/Card";
import { EmptyState, ErrorState, Skeleton } from "../components/States";
import {
  stationVisual,
  STATION_VISUAL_LABEL,
  type StationVisual,
} from "../utils/stationVisual";
import {
  ASSIGNMENT_METHOD_GLYPH,
  assignmentMethodOf,
  formatAssignmentConfidence,
  resolveLocationAssignment,
  stationAssignmentMeta,
  stationAssignmentTitle,
} from "../utils/stationAssignment";
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

const UNASSIGNED_REASON_LABELS: Record<string, string> = {
  insufficient_evidence: "insufficient localization evidence",
  no_location_match: "no location match",
  low_confidence: "low confidence",
  localization_unavailable: "localization unavailable",
  location_occupied: "matched seat occupied",
  unassigned: "not yet localized",
};

type StatusFilter = "all" | StationVisual;

function formatUnassignedReason(reason: string, confidence?: number | null): string {
  const base = UNASSIGNED_REASON_LABELS[reason] || reason.replace(/_/g, " ");
  if (reason === "low_confidence" && confidence != null) {
    return `${base} (${Math.round(confidence * 100)}%)`;
  }
  return base;
}

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

function formatCoordinate(value: number): string {
  return value.toFixed(2);
}

function automaticLocationFailureMessage(outcome: Record<string, unknown>): string {
  if (outcome.reason !== "insufficient_evidence") {
    return typeof outcome.reason === "string"
      ? formatUnassignedReason(
          outcome.reason,
          typeof outcome.confidence === "number" ? outcome.confidence : null,
        )
      : "automatic localization could not select a reliable seat";
  }

  const evidence = outcome.evidence;
  if (!evidence || typeof evidence !== "object") {
    return "No usable localization observations are available yet.";
  }
  const details = evidence as Record<string, unknown>;
  if (details.device_id == null) {
    return "This client has not been discovered as a network device yet, so there are no observations to calculate from.";
  }
  if (details.observation_count === 0) {
    return "This client has been discovered, but no usable sensor observations are available yet.";
  }
  return "The available observations do not contain usable coordinates for a reliable location.";
}

export function LocationsPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
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
  const [pendingBulkAction, setPendingBulkAction] = useState<{
    actionType: string;
    parameters: Record<string, unknown>;
  } | null>(null);
  const [assignLoading, setAssignLoading] = useState(false);
  const [autoLocatingClientId, setAutoLocatingClientId] = useState<string | null>(null);
  const assigningClientId = searchParams.get("assign");

  const { state, refetch } = useFetch<FloorLayout>(
    () => api.getLocationLayout(selectedFloor),
    [selectedFloor],
    ["app:client_status", "app:client_location_updated"],
  );
  const {
    state: unassignedState,
    refetch: refetchUnassigned,
  } = useFetch<{ items: UnassignedClientQueueItem[]; total: number }>(
    () => api.getUnassignedClients(100),
    [],
    ["app:client_status", "app:client_location_updated"],
  );
  const { state: calibrationState, refetch: refetchCalibration } =
    useFetch<CalibrationReport>(
      () => api.getCalibrationReport(),
      [],
      ["app:client_location_updated"],
    );
  const layout: FloorLayout | null =

    state.status === "success"
      ? state.data
      : state.status === "error"
        ? state.staleData || null
        : null;

  const unassignedItems: UnassignedClientQueueItem[] =
    unassignedState.status === "success"
      ? unassignedState.data.items
      : unassignedState.status === "error" && unassignedState.staleData
        ? unassignedState.staleData.items
        : [];

  const assigningClient = useMemo(
    () => unassignedItems.find((item) => item.id === assigningClientId) || null,
    [unassignedItems, assigningClientId],
  );

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
    if (actionType === "RESTART" || actionType === "SHUTDOWN") {
      setPendingBulkAction({ actionType, parameters });
      return;
    }
    await executeBulkAction(actionType, parameters);
  };

  const executeBulkAction = async (
    actionType: string,
    parameters: Record<string, unknown> = {},
  ) => {
    if (!selectedClientIds.length) return;
    setPendingBulkAction(null);
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

  const handleQuarantine = async () => {
    if (!selectedLocation?.client_id || !isOnline) return;
    const reason = window.prompt(
      "Enter reason for network quarantine (e.g. repeated malware policy violations):",
      "Administrator requested network quarantine",
    );
    if (reason === null) return;
    setActionLoading(true);
    try {
      await api.quarantineClient(selectedLocation.client_id, {
        reason: reason || undefined,
      });
      addToast({
        title: "Quarantine applied",
        message: `${client?.hostname || selectedLocation.client_id} has been isolated on the network.`,
        severity: "HIGH",
      });
      refetch();
    } catch (err: any) {
      addToast({
        title: "Quarantine failed",
        message: err?.message || "Failed to apply network quarantine.",
        severity: "CRITICAL",
      });
    } finally {
      setActionLoading(false);
    }
  };

  const handleReleaseQuarantine = async () => {
    if (!selectedLocation?.client_id || client?.connection.state !== "ISOLATED") return;
    if (
      !window.confirm(
        `Are you sure you want to release ${client?.hostname || selectedLocation.client_id} from network quarantine?`,
      )
    ) {
      return;
    }
    setActionLoading(true);
    try {
      await api.releaseClientQuarantine(selectedLocation.client_id);
      addToast({
        title: "Quarantine released",
        message: `${client?.hostname || selectedLocation.client_id} network access has been restored.`,
        severity: "SUCCESS",
      });
      refetch();
    } catch (err: any) {
      addToast({
        title: "Release failed",
        message: err?.message || "Failed to release network quarantine.",
        severity: "CRITICAL",
      });
    } finally {
      setActionLoading(false);
    }
  };

  const tryAutomaticLocation = async (queueItem: UnassignedClientQueueItem) => {
    setAutoLocatingClientId(queueItem.id);
    try {
      const outcome = await api.autoAssignClientLocation(queueItem.id);
      const location = (outcome.proposed_location || outcome.location) as
        | { id?: number; label?: string; floor?: number }
        | undefined;
      if (outcome.assigned === true && location?.label) {
        addToast({
          title: "Automatic location assigned",
          message: `${queueItem.hostname || queueItem.id} was placed at ${location.label}. Select that seat and confirm it after physical verification.`,
          severity: "SUCCESS",
        });
      } else if (
        outcome.reason === "low_confidence" &&
        location?.id != null &&
        location.label
      ) {
        const confidence =
          typeof outcome.confidence === "number"
            ? `${Math.round(outcome.confidence * 100)}% confidence`
            : "low confidence";
        const accepted = window.confirm(
          `${queueItem.hostname || queueItem.id} is proposed at ${location.label} (${confidence}).\\n\\nIs this the correct location?`,
        );
        if (accepted) {
          await api.assignClientLocation(queueItem.id, location.id);
          addToast({
            title: "Proposed location accepted",
            message: `${queueItem.hostname || queueItem.id} was assigned to ${location.label}. Confirm it after physical verification.`,
            severity: "SUCCESS",
          });
        } else {
          startAssignMode(queueItem.id);
          addToast({
            title: "Choose the correct location",
            message: `The proposed location was ${location.label}. Select the correct empty seat on the floor plan.`,
            severity: "INFO",
          });
        }
      } else {
        const reason = automaticLocationFailureMessage(outcome);
        addToast({
          title: "No location proposal available",
          message: `${queueItem.hostname || queueItem.id}: ${reason} Collect more neighbourhood observations or assign manually.`,
          severity: "HIGH",
        });
      }
      refetch();
      refetchUnassigned();
      refetchCalibration();
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

  const clearAssignMode = () => {
    const next = new URLSearchParams(searchParams);
    next.delete("assign");
    setSearchParams(next, { replace: true });
  };

  const startAssignMode = (clientId: string) => {
    const next = new URLSearchParams(searchParams);
    next.set("assign", clientId);
    setSearchParams(next, { replace: true });
  };

  const assignClientToSeat = async (location: ClientLocation) => {
    if (!assigningClientId) return;
    if (location.client_id && location.client_id !== assigningClientId) {
      addToast({
        title: "Seat occupied",
        message: "Choose an empty PC position for manual assignment.",
        severity: "HIGH",
      });
      return;
    }
    if (location.client_id === assigningClientId) {
      addToast({
        title: "Already here",
        message: "Select a different seat to move this client.",
        severity: "HIGH",
      });
      return;
    }
    const label =
      assigningClient?.hostname ||
      (selectedLocation?.client_id === assigningClientId
        ? client?.hostname
        : null) ||
      assigningClientId;
    if (
      !window.confirm(
        `Assign ${label} to ${location.label}?`,
      )
    ) {
      return;
    }
    setAssignLoading(true);
    try {
      await api.assignClientLocation(assigningClientId, location.id);
      addToast({
        title: "Location assigned",
        message: `${label} is now at ${location.label}.`,
        severity: "SUCCESS",
      });
      clearAssignMode();
      setSelectedLocationId(location.id);
      refetch();
      refetchUnassigned();
    } catch (err: any) {
      addToast({
        title: "Assignment failed",
        message: err?.message || "Unable to assign this client.",
        severity: "CRITICAL",
      });
    } finally {
      setAssignLoading(false);
    }
  };

  const confirmSelectedAssignment = async () => {
    if (!selectedLocation?.client_id) return;
    setActionLoading(true);
    try {
      await api.confirmClientLocation(selectedLocation.client_id);
      addToast({
        title: "Location confirmed",
        message: `${client?.hostname || selectedLocation.client_id} is confirmed at ${selectedLocation.label}.`,
        severity: "SUCCESS",
      });
      refetch();
      refetchUnassigned();
      refetchCalibration();
    } catch (err: any) {
      addToast({
        title: "Confirm failed",
        message: err?.message || "Unable to confirm this assignment.",
        severity: "CRITICAL",
      });
    } finally {
      setActionLoading(false);
    }
  };

  const handleStationClick = (station: ClientLocation) => {
    setSelectedLocationId(station.id);
    if (assigningClientId && !station.client_id) {
      void assignClientToSeat(station);
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
  const isOnline = client?.connection.state === "ONLINE";
  const floors = layout.available_floors.length
    ? layout.available_floors
    : [0, 1, 2];
  const emptyFloor = !layout.rooms.length && !layout.aisles.length;
  const selectedAssignment = resolveLocationAssignment(
    selectedLocation,
    client?.location_assignment,
  );
  const selectedMethod = assignmentMethodOf(selectedAssignment);
  const selectedConfidence = formatAssignmentConfidence(
    selectedAssignment?.confidence ?? null,
  );
  const pendingActionLabel = pendingBulkAction?.actionType === "SHUTDOWN" ? "shut down" : "restart";

  return (
    <div>
      <ConfirmDialog
        open={pendingBulkAction !== null}
        title={`${pendingActionLabel} selected clients?`}
        description={`This will ${pendingActionLabel} ${selectedClientIds.length} selected client${selectedClientIds.length === 1 ? "" : "s"}. This action affects the selected machines remotely.`}
        confirmLabel={pendingActionLabel === "shut down" ? "Shut down" : "Restart"}
        danger={pendingActionLabel === "shut down"}
        onCancel={() => setPendingBulkAction(null)}
        onConfirm={() => {
          if (pendingBulkAction) {
            void executeBulkAction(pendingBulkAction.actionType, pendingBulkAction.parameters);
          }
        }}
      />
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
            Floors, rooms, aisles, tables, and PC seats. Use the assignment
            queue to place unassigned clients on empty seats.
          </p>
        </div>
        <div style={{ display: "flex", gap: "var(--space-2)" }}>
          <Button
            variant="quiet"
            size="sm"
            onClick={() => {
              refetch();
              refetchUnassigned();
              refetchCalibration();
            }}
          >
            Refresh
          </Button>
        </div>
      </div>

      <CalibrationSummary report={calibrationState.status === "success" ? calibrationState.data : null} loading={calibrationState.status === "loading" || calibrationState.status === "idle"} error={calibrationState.status === "error" ? calibrationState.error.message : null} />

      {assigningClientId && (
        <div style={{ marginBottom: "var(--space-4)" }}>
          <div className="notice notice--info">
            Assigning{" "}
            <strong>
              {assigningClient?.hostname || assigningClientId}
            </strong>
            . Select an empty PC seat on the layout
            {assignLoading ? "…" : "."}{" "}
            <Button variant="quiet" size="sm" onClick={clearAssignMode}>
              Cancel
            </Button>
          </div>
        </div>
      )}

      <div style={{ marginBottom: "var(--space-5)" }}>
      <SectionCard
        title={`Location assignment queue (${unassignedItems.length})`}
        className="floor-vis__queue"
      >
        {unassignedItems.length === 0 ? (
          <div style={{ color: "var(--text-muted)" }}>
            All managed clients have a location assignment.
          </div>
        ) : (
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: "var(--space-2)",
            }}
          >
            {unassignedItems.map((item) => (
              <div
                key={item.id}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  gap: "var(--space-3)",
                  alignItems: "center",
                  flexWrap: "wrap",
                  padding: "var(--space-2) 0",
                  borderBottom: "1px solid var(--border)",
                }}
              >
                <div>
                  <div style={{ fontWeight: 600 }}>{item.hostname}</div>
                  <div
                    style={{
                      color: "var(--text-muted)",
                      fontSize: "var(--font-sm)",
                    }}
                  >
                    {item.mac_address} ·{" "}
                    {formatUnassignedReason(
                      item.unassigned_reason,
                      item.localization_confidence,
                    )}
                  </div>
                </div>
                <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={autoLocatingClientId !== null || assignLoading}
                    onClick={() => void tryAutomaticLocation(item)}
                  >
                    {autoLocatingClientId === item.id ? "Locating…" : "Try auto location"}
                  </Button>
                  <Button
                    variant={
                      assigningClientId === item.id ? "primary" : "quiet"
                    }
                    size="sm"
                    disabled={autoLocatingClientId !== null}
                    onClick={() => startAssignMode(item.id)}
                  >
                    {assigningClientId === item.id ? "Selecting seat…" : "Assign manually"}
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </SectionCard>
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
      <ul className="floor-vis__legend floor-vis__legend-assignment">
        <li className="floor-vis__legend-item">
          <span className="station__assignment-glyph" aria-hidden="true">
            {ASSIGNMENT_METHOD_GLYPH.AUTO}
          </span>
          Auto-assigned
        </li>
        <li className="floor-vis__legend-item">
          <span className="station__assignment-glyph" aria-hidden="true">
            {ASSIGNMENT_METHOD_GLYPH.MANUAL}
          </span>
          Manually assigned
        </li>
        <li className="floor-vis__legend-item">
          <span className="station__assignment-glyph" aria-hidden="true">
            {ASSIGNMENT_METHOD_GLYPH.EMPTY}
          </span>
          Empty seat
        </li>
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
                                      const assignment = resolveLocationAssignment(
                                        station,
                                      );
                                      const method = assignmentMethodOf(assignment);
                                      const assignmentMeta =
                                        stationAssignmentMeta(assignment);
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
                                      const title = stationAssignmentTitle(
                                        station,
                                        STATION_VISUAL_LABEL[visual],
                                      );
                                      return (
                                        <button
                                          key={stationKey(station)}
                                          type="button"
                                          className={[
                                            "station",
                                            `station--${visual}`,
                                            method
                                              ? `station--method-${method.toLowerCase()}`
                                              : "",
                                            visible ? "" : "station--dim",
                                            selected ? "station--selected" : "",
                                            neighbor ? "station--neighbor" : "",
                                          ]
                                            .filter(Boolean)
                                            .join(" ")}
                                          title={title}
                                          aria-label={title}
                                          onClick={() => handleStationClick(station)}
                                        >
                                          <span className="station__method" aria-hidden="true">
                                            {method
                                              ? ASSIGNMENT_METHOD_GLYPH[method]
                                              : ASSIGNMENT_METHOD_GLYPH.EMPTY}
                                          </span>
                                          <span className="station__name">
                                            {stationSeatLabel(
                                              station,
                                              layout.shows_clients,
                                            )}
                                          </span>
                                          <span className="station__meta">
                                            {layout.shows_clients && station.client_id
                                              ? assignmentMeta
                                                ? `${assignmentMeta} · ${STATION_VISUAL_LABEL[visual]}`
                                                : STATION_VISUAL_LABEL[visual]
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
                {assigningClientId
                  ? "Select an empty PC position to place the client."
                  : "Select a PC position to inspect it."}
              </div>
            ) : (
              <div>
                <div style={{ color: "var(--text-muted)" }}>
                  {locationDescription(selectedLocation)}
                </div>
                {assigningClientId && !selectedLocation.client_id && (
                  <div style={{ marginTop: "var(--space-3)" }}>
                    <Button
                      variant="primary"
                      size="sm"
                      disabled={assignLoading}
                      onClick={() => void assignClientToSeat(selectedLocation)}
                    >
                      Assign{" "}
                      {assigningClient?.hostname || assigningClientId} here
                    </Button>
                  </div>
                )}
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
                  {selectedLocation.client_id && (
                    <>
                      <PanelRow
                        label="Assignment"
                        value={
                          selectedMethod ? (
                            <span className="station__assignment">
                              <span
                                className="station__assignment-glyph"
                                aria-hidden="true"
                              >
                                {ASSIGNMENT_METHOD_GLYPH[selectedMethod]}
                              </span>
                              {selectedMethod}
                              {selectedAssignment?.verified
                                ? " · verified"
                                : selectedMethod === "AUTO"
                                  ? " · unconfirmed"
                                  : ""}
                            </span>
                          ) : (
                            "—"
                          )
                        }
                      />
                      <PanelRow
                        label="Confidence"
                        value={selectedConfidence || "—"}
                      />
                      <PanelRow
                        label="Assigned by"
                        value={selectedAssignment?.assigned_by || "—"}
                      />
                      <PanelRow
                        label="Source"
                        value={selectedAssignment?.source || "—"}
                      />
                      <PanelRow
                        label="Assigned at"
                        value={selectedAssignment?.assigned_at || "—"}
                      />
                    </>
                  )}
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

                {selectedLocation.client_id &&
                  selectedMethod === "AUTO" &&
                  !selectedAssignment?.verified && (
                    <div
                      style={{
                        display: "flex",
                        gap: "var(--space-2)",
                        flexWrap: "wrap",
                        marginTop: "var(--space-3)",
                      }}
                    >
                      <Button
                        variant="primary"
                        size="sm"
                        disabled={actionLoading}
                        onClick={() => void confirmSelectedAssignment()}
                      >
                        Confirm
                      </Button>
                      <Button
                        variant="quiet"
                        size="sm"
                        disabled={actionLoading}
                        onClick={() =>
                          startAssignMode(selectedLocation.client_id!)
                        }
                      >
                        Move
                      </Button>
                    </div>
                  )}

                {selectedLocation.client_id &&
                  (selectedMethod === "MANUAL" ||
                    selectedAssignment?.verified) && (
                    <div style={{ marginTop: "var(--space-3)" }}>
                      <Button
                        variant="quiet"
                        size="sm"
                        disabled={actionLoading}
                        onClick={() =>
                          startAssignMode(selectedLocation.client_id!)
                        }
                      >
                        Move
                      </Button>
                    </div>
                  )}

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
                    {client?.connection.state === "ISOLATED" ? (
                      <Button
                        variant="secondary"
                        size="sm"
                        disabled={actionLoading}
                        onClick={handleReleaseQuarantine}
                      >
                        Release quarantine
                      </Button>
                    ) : (
                      <Button
                        variant="danger"
                        size="sm"
                        disabled={actionLoading || !isOnline}
                        onClick={handleQuarantine}
                      >
                        Quarantine
                      </Button>
                    )}
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

function CalibrationSummary({
  report,
  loading,
  error,
}: {
  report: CalibrationReport | null;
  loading: boolean;
  error: string | null;
}) {
  if (loading) {
    return <div style={{ marginBottom: "var(--space-5)" }}><Skeleton variant="row" width="100%" /></div>;
  }
  if (error) {
    return (
      <div className="notice notice--warning" style={{ marginBottom: "var(--space-5)" }}>
        Calibration data is unavailable: {error}
      </div>
    );
  }
  if (!report) return null;

  const { summary } = report;
  return (
    <div style={{ marginBottom: "var(--space-5)" }}>
      <SectionCard title="Localization calibration">
        <p style={{ color: "var(--text-muted)", marginTop: 0 }}>
          Confirmed automatic assignments compare the calculated position with the physical seat.
        </p>
        <div className="floor-vis__legend" style={{ marginBottom: "var(--space-3)" }}>
          <span><strong>{report.sample_count}</strong> verified sample{report.sample_count === 1 ? "" : "s"}</span>
          <span><strong>{formatCoordinate(summary.mean_distance)}</strong> mean distance error</span>
          <span style={{ color: summary.systematic_transformation_signal ? "var(--danger)" : "var(--success)" }}>
            {summary.systematic_transformation_signal ? "Offset signal detected" : "No offset signal"}
          </span>
        </div>
        <div style={{ color: "var(--text-muted)", marginBottom: "var(--space-3)" }}>
          Mean axis error: Δx {formatCoordinate(summary.mean_error.x)}, Δy {formatCoordinate(summary.mean_error.y)}, Δz {formatCoordinate(summary.mean_error.z)}. {summary.interpretation}
        </div>
        {report.comparisons.length > 0 && (
          <div style={{ overflowX: "auto" }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Client</th>
                  <th>Confirmed seat</th>
                  <th>Δx</th>
                  <th>Δy</th>
                  <th>Δz</th>
                  <th>Distance</th>
                </tr>
              </thead>
              <tbody>
                {report.comparisons.slice(0, 10).map((comparison) => (
                  <tr key={`${comparison.history_id}-${comparison.client_id}`}>
                    <td>{comparison.hostname || comparison.client_id}</td>
                    <td>{comparison.location_label}</td>
                    <td>{formatCoordinate(comparison.error.dx)}</td>
                    <td>{formatCoordinate(comparison.error.dy)}</td>
                    <td>{formatCoordinate(comparison.error.dz)}</td>
                    <td>{formatCoordinate(comparison.error.distance)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </SectionCard>
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
