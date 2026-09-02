import React, { useEffect, useMemo, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  api,
  type ClientLocation,
  type ClientLocationHistoryEntry,
  type ClientPassiveNeighbourhood,
  type ClientScreenshot,
  type PhysicalNeighbor,
} from "../api/client";
import { useFetch } from "../hooks/useFetch";
import { useToast } from "../hooks/useToast";
import { ClientStatusBadge, Badge } from "../components/Badge";
import { Button } from "../components/Button";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { DeployPackagePanel } from "../components/DeployPackagePanel";
import { UpdateClientPanel } from "../components/UpdateClientPanel";
import { SectionCard, MetricCard } from "../components/Card";
import { Skeleton, ErrorState, Notice, EmptyState } from "../components/States";
import { formatDateTime, formatRelative } from "../utils/format";
import "../styles/operations.css";

const NEIGHBOR_RELATIONSHIP_LABELS: Record<
  PhysicalNeighbor["relationship"],
  string
> = {
  same_row: "Same column",
  same_table: "Facing seat",
  neighboring_table: "Neighboring table",
  same_zone: "Same room",
};

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
        display: "grid",
        gridTemplateColumns: "10rem 1fr",
        gap: "var(--space-3)",
        padding: "var(--space-2) 0",
        borderBottom: "1px solid var(--border-subtle)",
        alignItems: "baseline",
      }}
    >
      <span
        style={{
          fontSize: "var(--font-xs)",
          color: "var(--text-muted)",
          fontWeight: 500,
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
        {value ?? <span style={{ color: "var(--text-faint)" }}>—</span>}
      </span>
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return "0 B";
  }

  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = bytes;
  let unitIndex = 0;

  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }

  return `${size >= 10 || unitIndex === 0 ? size.toFixed(0) : size.toFixed(1)} ${units[unitIndex]}`;
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

type PendingConfirmation =
  | { kind: "disconnect" }
  | { kind: "restart" }
  | { kind: "shutdown" }
  | { kind: "quarantine" }
  | { kind: "release" }
  | { kind: "kill"; target: string };

export function ClientDetailPage() {
  const { clientId } = useParams<{ clientId: string }>();
  const navigate = useNavigate();
  const { addToast } = useToast();

  const [activeCommand, setActiveCommand] = useState<string | null>(null);
  const [commandLoading, setCommandLoading] = useState(false);
  const [commandResult, setCommandResult] = useState<any>(null);
  const [neighbourhoodLoading, setNeighbourhoodLoading] = useState(false);
  const [passiveNeighbourhoodLoading, setPassiveNeighbourhoodLoading] =
    useState(false);
  const [passiveNeighbourhood, setPassiveNeighbourhood] =
    useState<ClientPassiveNeighbourhood | null>(null);
  const [screenshotLoading, setScreenshotLoading] = useState(false);
  const [quarantineLoading, setQuarantineLoading] = useState(false);
  const [locations, setLocations] = useState<ClientLocation[]>([]);
  const [locationLoading, setLocationLoading] = useState(false);
  const [locationSaving, setLocationSaving] = useState(false);
  const [assignFloor, setAssignFloor] = useState("");
  const [assignAisle, setAssignAisle] = useState("");
  const [assignTable, setAssignTable] = useState("");
  const [assignColumn, setAssignColumn] = useState("");
  const [assignPosition, setAssignPosition] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLocationLoading(true);
    api
      .getLocations({ assignable: true })
      .then((response) => {
        if (!cancelled) setLocations(response.items);
      })
      .catch(() => {
        if (!cancelled) setLocations([]);
      })
      .finally(() => {
        if (!cancelled) setLocationLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Process management states
  const [processList, setProcessList] = useState<ProcessItem[] | null>(null);
  const [processFilter, setProcessFilter] = useState("");
  const [killingProcess, setKillingProcess] = useState<string | null>(null);

  // Start process modal
  const [showStartModal, setShowStartModal] = useState(false);
  const [startProcessPath, setStartProcessPath] = useState("");
  const [pendingConfirmation, setPendingConfirmation] =
    useState<PendingConfirmation | null>(null);
  const [quarantineReason, setQuarantineReason] = useState(
    "Administrator requested network quarantine",
  );

  // Activity log period selector
  const [activityPeriod, setActivityPeriod] = useState<"1d" | "1w" | "1m">(
    "1d",
  );
  const [activeTab, setActiveTab] = useState<
    "overview" | "network" | "remote" | "security" | "history"
  >("overview");

  const tabs = [
    { id: "overview", label: "Overview" },
    { id: "network", label: "Network & observations" },
    { id: "remote", label: "Remote actions" },
    { id: "security", label: "Security & quarantine" },
    { id: "history", label: "History & diagnostics" },
  ] as const;

  const selectTab = (tab: (typeof tabs)[number]["id"]) => {
    setActiveTab(tab);
  };

  const handleTabKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    const currentIndex = tabs.findIndex((tab) => tab.id === activeTab);
    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      event.preventDefault();
      const nextTab = tabs[(currentIndex + 1) % tabs.length];
      selectTab(nextTab.id);
      document.getElementById(`client-tab-${nextTab.id}`)?.focus();
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      event.preventDefault();
      const previousTab = tabs[(currentIndex - 1 + tabs.length) % tabs.length];
      selectTab(previousTab.id);
      document.getElementById(`client-tab-${previousTab.id}`)?.focus();
    } else if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      const nextTab = event.key === "Home" ? tabs[0] : tabs[tabs.length - 1];
      selectTab(nextTab.id);
      document.getElementById(`client-tab-${nextTab.id}`)?.focus();
    }
  };

  const { state, refetch } = useFetch(
    clientId ? () => api.getClient(clientId) : null,
    [clientId],
    ["app:client_status"],
  );

  const { state: screenshotState, refetch: refetchScreenshots } = useFetch(
    clientId ? () => api.getClientScreenshots(clientId, { limit: 8 }) : null,
    [clientId],
    ["app:client_status"],
  );
  const { state: locationHistoryState } = useFetch<{
    items: ClientLocationHistoryEntry[];
  }>(clientId ? () => api.getClientLocationHistory(clientId) : null, [
    clientId,
  ]);
  const { state: neighborsState, refetch: refetchNeighbors } = useFetch<{
    items: PhysicalNeighbor[];
  }>(clientId ? () => api.getPhysicalNeighbors(clientId) : null, [clientId]);

  const availableSeats = useMemo(
    () =>
      locations.filter(
        (location) =>
          location.assignable !== false &&
          (!location.client_id || location.client_id === clientId),
      ),
    [locations, clientId],
  );

  const floorOptions = uniqueNumbers(availableSeats.map((item) => item.floor));
  const aisleOptions = uniqueNumbers(
    availableSeats
      .filter((item) => String(item.floor) === assignFloor)
      .map((item) => item.aisle),
  );
  const tableOptions = uniqueNumbers(
    availableSeats
      .filter(
        (item) =>
          String(item.floor) === assignFloor &&
          String(item.aisle) === assignAisle,
      )
      .map((item) => item.table),
  ).filter((table) => {
    // Floor 1, Aisle 1 only contains Table 2.
    if (assignFloor === "1" && assignAisle === "1") {
      return table === 2;
    }

    return true;
  });
  const columnOptions = uniqueNumbers(
    availableSeats
      .filter(
        (item) =>
          String(item.floor) === assignFloor &&
          String(item.aisle) === assignAisle &&
          String(item.table) === assignTable,
      )
      .map((item) => item.column ?? item.row),
  );
  const positionOptions = uniqueNumbers(
    availableSeats
      .filter(
        (item) =>
          String(item.floor) === assignFloor &&
          String(item.aisle) === assignAisle &&
          String(item.table) === assignTable &&
          String(item.column ?? item.row) === assignColumn,
      )
      .map((item) => item.position),
  );

  const selectedSeat = availableSeats.find(
    (item) =>
      String(item.floor) === assignFloor &&
      String(item.aisle) === assignAisle &&
      String(item.table) === assignTable &&
      String(item.column ?? item.row) === assignColumn &&
      String(item.position) === assignPosition,
  );
  const selectedLocationId = selectedSeat ? String(selectedSeat.id) : "";

  const executeCommand = async (command: string, args?: any) => {
    if (!clientId) return;
    // Keep one command result visible at a time.
    if (command !== "GET_PROCESSES") {
      setProcessList(null);
    }
    setActiveCommand(command);
    setCommandLoading(true);

    try {
      const response = await api.runClientCommand(clientId, command, args);
      setCommandResult(response);

      if (command === "GET_PROCESSES") {
        const rawData = response?.data;
        const list: ProcessItem[] = Array.isArray(rawData)
          ? rawData
          : Array.isArray(rawData?.processes)
            ? rawData.processes
            : [];
        setProcessList(list);
        addToast({
          title: "Processes Retrieved",
          message: `Loaded ${list.length} running processes from ${clientId}.`,
          severity: "INFO",
        });
      } else if (command === "KILL_PROCESS") {
        addToast({
          title: "Process Terminated",
          message: `Kill command issued for ${args}.`,
          severity: "SUCCESS",
        });
        // Auto-refresh process list if already loaded
        if (processList) {
          executeCommand("GET_PROCESSES");
        }
      } else if (command === "START_PROCESS") {
        addToast({
          title: "Process Started",
          message: `Launched ${args} on client.`,
          severity: "SUCCESS",
        });
        setShowStartModal(false);
        setStartProcessPath("");
      } else if (command === "DISCONNECT") {
        addToast({
          title: "Client Disconnected",
          message: `Client ${clientId} disconnected at server request.`,
          severity: "LOW",
        });
        refetch();
      } else {
        addToast({
          title: "Command Executed",
          message: `${command} completed successfully.`,
          severity: "SUCCESS",
        });
      }
    } catch (err: any) {
      const msg = err?.message || "Command failed";
      addToast({
        title: "Command Error",
        message: msg,
        severity: "CRITICAL",
      });
    } finally {
      setCommandLoading(false);
    }
  };

  const requestNeighbourhood = async () => {
    if (!clientId) return;
    setProcessList(null);
    setNeighbourhoodLoading(true);
    try {
      const result = await api.requestClientNeighbourhood(clientId);
      addToast({
        title: "Neighbourhood collected",
        message: `Received ${result.observations_sent} stored observation(s) from ${c.hostname}.`,
        severity: "SUCCESS",
      });
      refetch();
    } catch (err: any) {
      addToast({
        title: "Neighbourhood request failed",
        message:
          err?.message ||
          "The client did not provide its stored neighbourhood.",
        severity: "CRITICAL",
      });
    } finally {
      setNeighbourhoodLoading(false);
    }
  };

  const requestPassiveNeighbourhood = async () => {
    if (!clientId) return;
    setProcessList(null);
    setPassiveNeighbourhoodLoading(true);
    try {
      const result = await api.requestClientPassiveNeighbourhood(clientId);
      setPassiveNeighbourhood(result);
      const protocols = new Set(
        result.observations.map((observation) => observation.protocol),
      );
      addToast({
        title: "Passive information received",
        message: `Received ${result.observation_count} observation(s) across ${protocols.size} protocol(s) from ${c.hostname}.`,
        severity: "SUCCESS",
      });
    } catch (err: any) {
      addToast({
        title: "Passive information request failed",
        message:
          err?.message ||
          "The client did not provide passive network information.",
        severity: "CRITICAL",
      });
    } finally {
      setPassiveNeighbourhoodLoading(false);
    }
  };

  const requestScreenshot = async () => {
    if (!clientId) return;
    setProcessList(null);
    setScreenshotLoading(true);
    try {
      const result = await api.requestClientScreenshot(clientId);
      setCommandResult(result);
      setActiveCommand("REQUEST_SCREENSHOT");

      addToast({
        title: "Screenshot captured",
        message: result.filename
          ? `${result.filename} saved ${result.captured_at ? `at ${formatDateTime(result.captured_at)}` : "successfully"}.`
          : `Screenshot captured successfully for ${c.hostname}.`,
        severity: "SUCCESS",
      });

      refetchScreenshots();
    } catch (err: any) {
      addToast({
        title: "Screenshot request failed",
        message: err?.message || "The client did not return a screenshot.",
        severity: "CRITICAL",
      });
    } finally {
      setScreenshotLoading(false);
    }
  };

  const applyQuarantine = async (reason: string) => {
    if (!clientId) return;
    setQuarantineLoading(true);
    try {
      await api.quarantineClient(clientId, {
        reason: reason.trim() || undefined,
      });
      addToast({
        title: "Quarantine applied",
        message: `${c.hostname} has been isolated on the network.`,
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
      setQuarantineLoading(false);
    }
  };

  const handleQuarantine = () => {
    setQuarantineReason("Administrator requested network quarantine");
    setPendingConfirmation({ kind: "quarantine" });
  };

  const releaseQuarantine = async () => {
    if (!clientId) return;
    setQuarantineLoading(true);
    try {
      await api.releaseClientQuarantine(clientId);
      addToast({
        title: "Quarantine released",
        message: `${c.hostname} network access has been restored.`,
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
      setQuarantineLoading(false);
    }
  };

  const confirmPendingAction = () => {
    const pending = pendingConfirmation;
    setPendingConfirmation(null);
    if (!pending) return;

    if (pending.kind === "disconnect") {
      void executeCommand("DISCONNECT");
    } else if (pending.kind === "restart") {
      void executeCommand("RESTART", { delay_seconds: 5 });
    } else if (pending.kind === "shutdown") {
      void executeCommand("SHUTDOWN", { delay_seconds: 5 });
    } else if (pending.kind === "quarantine") {
      void applyQuarantine(quarantineReason);
    } else if (pending.kind === "release") {
      void releaseQuarantine();
    } else {
      setKillingProcess(pending.target);
      void executeCommand("KILL_PROCESS", pending.target);
    }
  };

  if (state.status === "idle" || state.status === "loading") {
    return <ClientDetailSkeleton />;
  }

  if (state.status === "error" && !state.staleData) {
    return (
      <ErrorState
        title="Unable to load client"
        message={state.error.message}
        onRetry={refetch}
      />
    );
  }

  const d = state.status === "success" ? state.data : state.staleData!;
  const c = d.client;
  const isOnline = c.connection.state === "ONLINE";
  const isIsolated = c.connection.state === "ISOLATED";

  const assignLocation = async () => {
    if (!clientId || !selectedLocationId) return;
    setLocationSaving(true);
    try {
      await api.assignClientLocation(clientId, Number(selectedLocationId));
      addToast({
        title: "Location assigned",
        message: `${c.hostname} is now assigned to the selected position.`,
        severity: "SUCCESS",
      });
      setAssignFloor("");
      setAssignAisle("");
      setAssignTable("");
      setAssignColumn("");
      setAssignPosition("");
      refetch();
      refetchNeighbors();
      api
        .getLocations({ assignable: true })
        .then((response) => setLocations(response.items))
        .catch(() => undefined);
    } catch (err: any) {
      addToast({
        title: "Location assignment failed",
        message:
          err?.message || "The selected position may already be occupied.",
        severity: "CRITICAL",
      });
    } finally {
      setLocationSaving(false);
    }
  };

  const filteredProcesses = (processList || []).filter((p) => {
    if (!processFilter) return true;
    const term = processFilter.toLowerCase();
    return (
      (p.name && p.name.toLowerCase().includes(term)) ||
      (p.pid !== undefined && String(p.pid).includes(term)) ||
      (p.username && p.username.toLowerCase().includes(term))
    );
  });

  const screenshotItems: ClientScreenshot[] =
    screenshotState.status === "success"
      ? screenshotState.data.items
      : screenshotState.status === "error" && screenshotState.staleData
        ? screenshotState.staleData.items
        : [];
  const screenshotLoadingState =
    screenshotState.status === "idle" || screenshotState.status === "loading";
  const capturedScreenshot =
    activeCommand === "REQUEST_SCREENSHOT" && commandResult?.filename
      ? screenshotItems.find((shot) => shot.filename === commandResult.filename)
      : undefined;

  return (
    <div style={{ display: "flex", flexDirection: "column" }}>
      <ConfirmDialog
        open={pendingConfirmation !== null}
        title={
          pendingConfirmation?.kind === "quarantine"
            ? "Quarantine this client?"
            : pendingConfirmation?.kind === "release"
              ? "Release quarantine?"
              : pendingConfirmation?.kind === "disconnect"
                ? "Disconnect this client?"
                : pendingConfirmation?.kind === "restart"
                  ? "Restart this client?"
                  : pendingConfirmation?.kind === "shutdown"
                    ? "Shut down this client?"
                    : "Terminate this process?"
        }
        description={
          pendingConfirmation?.kind === "quarantine"
            ? `This will isolate ${c.hostname} from the network until an administrator restores access.`
            : pendingConfirmation?.kind === "release"
              ? `This will restore network access for ${c.hostname}.`
              : pendingConfirmation?.kind === "disconnect"
                ? `Disconnect ${c.hostname} (${c.id}) from the server?`
                : pendingConfirmation?.kind === "restart"
                  ? `Restart ${c.hostname} after a short delay?`
                  : pendingConfirmation?.kind === "shutdown"
                    ? `Shut down ${c.hostname} after a short delay?`
                    : `Terminate '${pendingConfirmation?.kind === "kill" ? pendingConfirmation.target : ""}' on ${c.hostname}?`
        }
        confirmLabel={
          pendingConfirmation?.kind === "quarantine"
            ? "Quarantine"
            : pendingConfirmation?.kind === "release"
              ? "Release"
              : pendingConfirmation?.kind === "disconnect"
                ? "Disconnect"
                : pendingConfirmation?.kind === "restart"
                  ? "Restart"
                  : pendingConfirmation?.kind === "shutdown"
                    ? "Shut down"
                    : "Terminate"
        }
        danger={
          pendingConfirmation?.kind === "quarantine" ||
          pendingConfirmation?.kind === "shutdown" ||
          pendingConfirmation?.kind === "kill"
        }
        inputLabel={
          pendingConfirmation?.kind === "quarantine"
            ? "Reason (optional)"
            : undefined
        }
        inputValue={
          pendingConfirmation?.kind === "quarantine"
            ? quarantineReason
            : undefined
        }
        inputPlaceholder="Administrator requested network quarantine"
        onInputChange={
          pendingConfirmation?.kind === "quarantine"
            ? setQuarantineReason
            : undefined
        }
        onCancel={() => setPendingConfirmation(null)}
        onConfirm={confirmPendingAction}
      />
      {/* Top navigation */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "var(--space-3)",
          marginBottom: "var(--space-5)",
        }}
      >
        <Button variant="quiet" size="md" onClick={() => navigate("/clients")}>
          Clients
        </Button>
        <Button variant="quiet" size="md" onClick={refetch}>
          Refresh
        </Button>
      </div>

      {state.status === "error" && (
        <Notice variant="warning" title="Stale data shown">
          {state.error.message}
        </Notice>
      )}

      {/* Prominent Isolated Device Notice */}
      {isIsolated && (
        <div style={{ marginBottom: "var(--space-5)" }}>
          <Notice variant="danger" title="🔴 DEVICE ISOLATED">
            <div
              style={{
                display: "grid",
                gap: "var(--space-2)",
                marginTop: "var(--space-2)",
              }}
            >
              <div>
                <strong>Reason:</strong>{" "}
                {c.connection.isolation?.reason ||
                  "Administrator requested static device isolation"}
              </div>
              {c.connection.isolation?.isolated_at && (
                <div>
                  <strong>Isolated at:</strong>{" "}
                  {formatDateTime(c.connection.isolation.isolated_at)}
                </div>
              )}
              {c.ip_address && (
                <div>
                  <strong>Previous IP:</strong> {c.ip_address}
                </div>
              )}
              <div>
                <strong>Last server contact:</strong>{" "}
                {c.connection.last_connected_at
                  ? formatDateTime(c.connection.last_connected_at)
                  : "Disconnected"}
              </div>
              <div>
                <strong>Recovery:</strong> Administrator intervention required
                (physical logon / recovery script on client machine).
              </div>
            </div>
          </Notice>
        </div>
      )}

      <div className="client-detail-hero">
        <div className="client-detail-identity">
          <div className="client-detail-icon" aria-hidden="true">
            {isIsolated ? "⛨" : "◈"}
          </div>
          <div>
            <span className="eyebrow eyebrow--accent">
              CLIENT AGENT / OPERATIONS
            </span>
            <h1 className="client-detail-title">{c.hostname}</h1>
            <p className="client-detail-subtitle">
              {c.ip_address || c.mac_address} ·{" "}
              {c.os.system || "Operating system unavailable"}
            </p>
            <div className="client-detail-badges">
              <ClientStatusBadge state={c.connection.state} />
              {c.location && <Badge variant="info">{c.location.label}</Badge>}
              {c.health?.status && (
                <Badge
                  variant={
                    c.health.status === "healthy"
                      ? "success"
                      : c.health.status === "critical"
                        ? "danger"
                        : "warning"
                  }
                >
                  {c.health.status.toUpperCase()}
                </Badge>
              )}
            </div>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: "var(--space-3)",
                flexWrap: "wrap",
                marginTop: "var(--space-4)",
              }}
            >
              <Button
                variant="danger"
                size="sm"
                disabled={!isOnline || commandLoading}
                onClick={() => setPendingConfirmation({ kind: "disconnect" })}
              >
                Disconnect agent
              </Button>
              <span
                style={{
                  fontSize: "var(--font-xs)",
                  color: "var(--muted-text)",
                }}
              >
                {isIsolated
                  ? `Isolated · last contact ${formatRelative(c.connection.last_connected_at)}`
                  : isOnline
                    ? `Connected ${formatRelative(c.connection.last_connected_at)}`
                    : `Last seen ${formatRelative(c.connection.last_connected_at)}`}
              </span>
            </div>
          </div>
        </div>
        <div className="client-detail-alerts">
          <MetricCard
            label="New alerts"
            value={d.alert_counts.new}
            valueVariant={d.alert_counts.new > 0 ? "danger" : "default"}
          />
          <MetricCard label="Total alerts" value={d.alert_counts.total} />
        </div>
      </div>

      <div
        role="tablist"
        aria-label="Client detail sections"
        style={{
          display: "flex",
          gap: "var(--space-1)",
          overflowX: "auto",
          borderBottom: "1px solid var(--border)",
          marginBottom: "var(--space-5)",
        }}
      >
        {tabs.map((tab) => (
          <button
            key={tab.id}
            id={`client-tab-${tab.id}`}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.id}
            aria-controls={
              tab.id === "overview"
                ? "client-panel-overview"
                : tab.id === "network"
                  ? "client-panel-network"
                  : tab.id === "history"
                    ? "client-panel-history"
                    : "client-panel-actions"
            }
            tabIndex={activeTab === tab.id ? 0 : -1}
            onClick={() => selectTab(tab.id)}
            onKeyDown={handleTabKeyDown}
            style={{
              flexShrink: 0,
              padding: "var(--space-3) var(--space-4)",
              border: 0,
              borderBottom: `2px solid ${activeTab === tab.id ? "var(--primary)" : "transparent"}`,
              background: "transparent",
              color: activeTab === tab.id ? "var(--text)" : "var(--text-muted)",
              fontWeight: activeTab === tab.id ? 600 : 500,
              cursor: "pointer",
              whiteSpace: "nowrap",
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <section
        id="client-panel-overview"
        role="tabpanel"
        aria-labelledby="client-tab-overview"
        hidden={activeTab !== "overview"}
        style={{ display: activeTab === "overview" ? "flex" : "none" }}
      >
        <SectionCard title="Physical Location">
          <div style={{ display: "grid", gap: "var(--space-3)" }}>
            <div
              style={{
                color: c.location ? "var(--text)" : "var(--text-muted)",
              }}
            >
              {c.location ? c.location.label : "Location unassigned"}
            </div>
            <div
              style={{
                display: "flex",
                gap: "var(--space-3)",
                alignItems: "end",
                flexWrap: "wrap",
              }}
            >
              {/**  floor one aisle one only has table two make sure to only display that table and not both  */}
              <LocationSelect
                label="Floor"
                value={assignFloor}
                options={floorOptions}
                disabled={locationLoading || locationSaving}
                onChange={(value) => {
                  setAssignFloor(value);
                  setAssignAisle("");
                  setAssignTable("");
                  setAssignColumn("");
                  setAssignPosition("");
                }}
              />
              <LocationSelect
                label="Aisle"
                value={assignAisle}
                options={aisleOptions}
                disabled={!assignFloor || locationLoading || locationSaving}
                onChange={(value) => {
                  setAssignAisle(value);
                  setAssignTable("");
                  setAssignColumn("");
                  setAssignPosition("");
                }}
              />
              <LocationSelect
                label="Table"
                value={assignTable}
                options={tableOptions}
                disabled={!assignAisle || locationLoading || locationSaving}
                onChange={(value) => {
                  setAssignTable(value);
                  setAssignColumn("");
                  setAssignPosition("");
                }}
              />
              <LocationSelect
                label="Column"
                value={assignColumn}
                options={columnOptions}
                disabled={!assignTable || locationLoading || locationSaving}
                onChange={(value) => {
                  setAssignColumn(value);
                  setAssignPosition("");
                }}
              />
              <LocationSelect
                label="Position"
                value={assignPosition}
                options={positionOptions}
                disabled={!assignColumn || locationLoading || locationSaving}
                onChange={setAssignPosition}
              />
              <Button
                variant="primary"
                size="sm"
                disabled={
                  !selectedLocationId || locationSaving || locationLoading
                }
                onClick={assignLocation}
              >
                {locationSaving
                  ? "Saving…"
                  : c.location
                    ? "Change Location"
                    : "Assign Location"}
              </Button>
            </div>
            {selectedSeat && (
              <div
                style={{
                  fontSize: "var(--font-xs)",
                  color: "var(--text-muted)",
                }}
              >
                {selectedSeat.label}
              </div>
            )}
          </div>
          {locationHistoryState.status === "success" &&
            locationHistoryState.data.items.length > 0 && (
              <div
                style={{
                  marginTop: "var(--space-4)",
                  borderTop: "1px solid var(--border-subtle)",
                  paddingTop: "var(--space-3)",
                }}
              >
                <div
                  style={{
                    fontSize: "var(--font-xs)",
                    color: "var(--text-muted)",
                    marginBottom: "var(--space-2)",
                  }}
                >
                  Assignment history
                </div>
                <div style={{ display: "grid", gap: "var(--space-2)" }}>
                  {locationHistoryState.data.items.map((entry) => (
                    <div
                      key={entry.id}
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        gap: "var(--space-3)",
                        fontSize: "var(--font-xs)",
                        flexWrap: "wrap",
                      }}
                    >
                      <span>{entry.location.label}</span>
                      <span style={{ color: "var(--text-muted)" }}>
                        {formatDateTime(entry.assigned_at)} ·{" "}
                        {entry.assigned_by || "Unknown operator"}
                        {entry.unassigned_at
                          ? ` · ended ${formatDateTime(entry.unassigned_at)}`
                          : " · current"}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
        </SectionCard>

        <SectionCard title="Health">
          <div style={{ display: "grid", gap: "var(--space-2)" }}>
            <DetailRow
              label="Status"
              value={
                c.health?.status ? c.health.status.replace("_", " ") : "Unknown"
              }
            />
            <DetailRow
              label="CPU"
              value={
                typeof c.health?.cpu_percent === "number"
                  ? `${Math.round(c.health.cpu_percent)}%`
                  : "—"
              }
            />
            <DetailRow
              label="Memory"
              value={
                typeof c.health?.memory_percent === "number"
                  ? `${Math.round(c.health.memory_percent)}%`
                  : "—"
              }
            />
            <DetailRow
              label="Disk"
              value={
                typeof c.health?.disk_percent === "number"
                  ? `${Math.round(c.health.disk_percent)}%`
                  : "—"
              }
            />
            <DetailRow
              label="Updated"
              value={
                c.health?.updated_at
                  ? formatDateTime(c.health.updated_at)
                  : "Not collected yet"
              }
            />
          </div>
        </SectionCard>

        {c.location && (
          <SectionCard title="Physical Neighbors">
            {neighborsState.status === "error" ? (
              <div
                style={{
                  color: "var(--text-muted)",
                  fontSize: "var(--font-xs)",
                }}
              >
                {neighborsState.error.message}
              </div>
            ) : neighborsState.status !== "success" ||
              neighborsState.data.items.length === 0 ? (
              <div
                style={{
                  color: "var(--text-muted)",
                  fontSize: "var(--font-xs)",
                }}
              >
                {neighborsState.status === "loading"
                  ? "Loading neighbors…"
                  : "No assigned neighbors at adjacent positions."}
              </div>
            ) : (
              <div style={{ display: "grid", gap: "var(--space-2)" }}>
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
                      display: "flex",
                      justifyContent: "space-between",
                      gap: "var(--space-3)",
                      textAlign: "left",
                      border: 0,
                      padding: "var(--space-2) 0",
                      background: "transparent",
                      color: "var(--text)",
                      cursor: "pointer",
                      borderBottom: "1px solid var(--border-subtle)",
                    }}
                  >
                    <span>
                      {neighbor.hostname}{" "}
                      <span style={{ color: "var(--text-muted)" }}>
                        {NEIGHBOR_RELATIONSHIP_LABELS[neighbor.relationship]} ·{" "}
                        {neighbor.location.label}
                      </span>
                    </span>
                    <span
                      style={{
                        color:
                          neighbor.state === "ONLINE"
                            ? "var(--success)"
                            : neighbor.state === "ISOLATED"
                              ? "var(--danger)"
                              : "var(--text-muted)",
                        fontSize: "var(--font-xs)",
                      }}
                    >
                      {neighbor.state}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </SectionCard>
        )}
      </section>

      <section
        id="client-panel-actions"
        role="tabpanel"
        aria-labelledby={
          activeTab === "security" ? "client-tab-security" : "client-tab-remote"
        }
        aria-label="Client actions"
        hidden={
          activeTab !== "remote" &&
          activeTab !== "network" &&
          activeTab !== "security"
        }
        style={{
          display:
            activeTab === "remote" ||
            activeTab === "network" ||
            activeTab === "security"
              ? "block"
              : "none",
        }}
      >
        {/* Interactive Command Control Center */}
        <SectionCard title="Client actions and telemetry">
          {!isOnline && (
            <div style={{ marginBottom: "var(--space-3)" }}>
              <Notice
                variant={isIsolated ? "warning" : "info"}
                title={isIsolated ? "Client is isolated" : "Client is offline"}
              >
                {isIsolated
                  ? "Device static isolation is active. Communication with the server has been severed as expected until local administrator restoration."
                  : "Agent must be online and connected to execute remote diagnostics."}
              </Notice>
            </div>
          )}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
              gap: "var(--space-4)",
            }}
          >
            <div
              style={{
                display: activeTab === "remote" ? "grid" : "none",
                gap: "var(--space-2)",

                alignContent: "start",
              }}
            >
              <span
                style={{
                  fontSize: "var(--font-xs)",
                  color: "var(--text-muted)",
                  fontWeight: 600,
                  textTransform: "uppercase",
                  letterSpacing: "0.06em",
                }}
              >
                Diagnostics
              </span>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr",
                  gap: "var(--space-2)",
                  flexWrap: "wrap",
                }}
              >
                <Button
                  variant="primary"
                  size="md"
                  disabled={!isOnline || commandLoading}
                  onClick={() => executeCommand("GET_PROCESSES")}
                >
                  {commandLoading && activeCommand === "GET_PROCESSES"
                    ? "Fetching..."
                    : "Get Processes"}
                </Button>

                <Button
                  variant="secondary"
                  size="md"
                  disabled={!isOnline || commandLoading}
                  onClick={() => executeCommand("GET_CPU_INFO")}
                >
                  CPU Info
                </Button>

                <Button
                  variant="secondary"
                  size="md"
                  disabled={!isOnline || commandLoading}
                  onClick={() => executeCommand("GET_MEMORY_INFO")}
                >
                  Memory Info
                </Button>

                <Button
                  variant="secondary"
                  size="md"
                  disabled={!isOnline || commandLoading}
                  onClick={() => executeCommand("GET_DISK_INFO")}
                >
                  Disk Info
                </Button>

                <Button
                  variant="secondary"
                  size="md"
                  disabled={!isOnline || commandLoading}
                  onClick={() => executeCommand("GET_NETWORK_INFO")}
                >
                  Network Info
                </Button>

                <Button
                  variant="secondary"
                  size="md"
                  disabled={!isOnline || commandLoading}
                  onClick={() => executeCommand("PING")}
                >
                  Ping
                </Button>
              </div>
            </div>

            <div
              style={{
                display: activeTab === "network" ? "grid" : "none",
                gap: "var(--space-2)",
                alignContent: "start",
              }}
            >
              <span
                style={{
                  fontSize: "var(--font-xs)",
                  color: "var(--text-muted)",
                  fontWeight: 600,
                  textTransform: "uppercase",
                  letterSpacing: "0.06em",
                }}
              >
                Network collection
              </span>
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: "var(--space-2)",
                  flexWrap: "wrap",
                }}
              >
                <Button
                  variant="primary"
                  size="md"
                  disabled={
                    !isOnline ||
                    commandLoading ||
                    neighbourhoodLoading ||
                    passiveNeighbourhoodLoading
                  }
                  onClick={requestNeighbourhood}
                >
                  {neighbourhoodLoading
                    ? "Collecting Neighbourhood…"
                    : "Collect Neighbourhood"}
                </Button>
                <Button
                  variant="secondary"
                  size="md"
                  disabled={!isOnline || screenshotLoading}
                  onClick={requestScreenshot}
                >
                  {screenshotLoading
                    ? "Capturing Screenshot…"
                    : "Capture Screenshot"}
                </Button>
                <Button
                  variant="secondary"
                  size="md"
                  disabled={
                    !isOnline ||
                    commandLoading ||
                    neighbourhoodLoading ||
                    passiveNeighbourhoodLoading
                  }
                  onClick={requestPassiveNeighbourhood}
                >
                  {passiveNeighbourhoodLoading
                    ? "Requesting Passive Info…"
                    : "Get Passive Network Information"}
                </Button>
              </div>
            </div>

            <div
              style={{
                display: activeTab === "remote" ? "grid" : "none",
                gap: "var(--space-2)",
                alignContent: "start",
                }}
            >
              <span
                style={{
                  fontSize: "var(--font-xs)",
                  color: "var(--text-muted)",
                  fontWeight: 600,
                  textTransform: "uppercase",
                  letterSpacing: "0.06em",
                }}
              >
                Operations
              </span>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr",
                  gap: "8px",
                  alignItems: "start",
                }}
              >
                {/* Activity Log dropdown & button */}

                <select
                  value={activityPeriod}
                  onChange={(e) => setActivityPeriod(e.target.value as any)}
                  disabled={!isOnline || commandLoading}
                  style={{
                    background: "var(--surface)",
                    color: "var(--text)",
                    border: "1px solid var(--border)",
                    borderRadius: "var(--radius-sm)",
                    padding: "4px 8px",
                    fontSize: "var(--font-xs)",
                    width: "100%",
                  }}
                >
                  <option value="1d">Last 24h</option>
                  <option value="1w">Last 7d</option>
                  <option value="1m">Last 30d</option>
                </select>
                <Button
                  variant="primary"
                  size="md"
                  disabled={!isOnline || commandLoading}
                  onClick={() =>
                    executeCommand("GET_ACTIVITY_LOG", activityPeriod)
                  }
                  style={{ width: "100%", height: "100%" }}
                >
                  Fetch Log
                </Button>

                <Button
                  style={{
                    // i want it to take two columns
                    gridColumn: "1 / span 2",
                  }}
                  variant="secondary"
                  size="md"
                  disabled={!isOnline || commandLoading}
                  onClick={() => setShowStartModal(true)}
                >
                  Start Process
                </Button>

                <Button
                  variant="secondary"
                  size="md"
                  disabled={!isOnline || commandLoading}
                  onClick={() => setPendingConfirmation({ kind: "restart" })}
                >
                  Restart
                </Button>

                <Button
                  variant="danger"
                  size="md"
                  disabled={!isOnline || commandLoading}
                  onClick={() => setPendingConfirmation({ kind: "shutdown" })}
                >
                  Shut Down
                </Button>
              </div>
            </div>
            <div style={{
              display: activeTab === "remote" ? "grid" : "none",
              gap: "var(--space-4)",
            }}>
              {clientId && (
                <>
                  <UpdateClientPanel
                    targets={[clientId]}
                    disabled={!isOnline || commandLoading}
                    onCompleted={() => {
                      addToast({
                        title: "Client update complete",
                        message: `Update applied to ${clientId}. Client will report new version on next heartbeat.`,
                        severity: "SUCCESS",
                      });
                      refetch();
                    }}
                  />
                  <DeployPackagePanel
                    targets={[clientId]}
                    disabled={!isOnline || commandLoading}
                    onCompleted={(action) => {
                      addToast({
                        title:
                          action.status === "SUCCESS"
                            ? "Package deployed"
                            : action.status === "PARTIAL_SUCCESS"
                              ? "Package partially deployed"
                              : "Package deployment failed",
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
                </>
              )}
            </div>

            <div
              style={{
                display: activeTab === "security" ? "grid" : "none",
                gap: "var(--space-2)",
                alignContent: "start",
              }}
            >
              <span
                style={{
                  fontSize: "var(--font-xs)",
                  color: "var(--text-muted)",
                  fontWeight: 600,
                  textTransform: "uppercase",
                  letterSpacing: "0.06em",
                }}
              >
                Containment
              </span>
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: "var(--space-2)",
                  flexWrap: "wrap",
                }}
              >
                <Button
                  variant="danger"
                  size="md"
                  disabled={!isOnline || commandLoading || quarantineLoading}
                  onClick={handleQuarantine}
                >
                  {quarantineLoading ? "Quarantining…" : "Isolate / Quarantine"}
                </Button>

                <Button
                  variant="secondary"
                  size="md"
                  disabled={!isIsolated || commandLoading || quarantineLoading}
                  onClick={() => setPendingConfirmation({ kind: "release" })}
                >
                  Release Quarantine
                </Button>
              </div>
            </div>
          </div>

          {/* Start Process Modal / Bar */}
          {showStartModal && (
            <div
              style={{
                marginTop: "var(--space-4)",
                padding: "var(--space-3)",
                background: "var(--surface-muted)",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius)",
                display: "flex",
                gap: "var(--space-2)",
                alignItems: "center",
              }}
            >
              <input
                type="text"
                placeholder="Absolute path to executable (e.g. /usr/bin/htop or notepad.exe)..."
                value={startProcessPath}
                onChange={(e) => setStartProcessPath(e.target.value)}
                style={{
                  flex: 1,
                  padding: "var(--space-2)",
                  background: "var(--surface)",
                  border: "1px solid var(--border)",
                  borderRadius: "var(--radius-sm)",
                  color: "var(--text)",
                  fontSize: "var(--font-sm)",
                }}
              />
              <Button
                variant="primary"
                size="md"
                disabled={!startProcessPath.trim() || commandLoading}
                onClick={() =>
                  executeCommand("START_PROCESS", startProcessPath.trim())
                }
              >
                Launch
              </Button>
              <Button
                variant="quiet"
                size="md"
                onClick={() => setShowStartModal(false)}
              >
                Cancel
              </Button>
            </div>
          )}
        </SectionCard>
      </section>

      <section
        id="client-panel-remote-processes"
        aria-label="Remote process results"
        hidden={activeTab !== "remote"}
        style={{ display: activeTab === "remote" ? "block" : "none" }}
      >
        {/* Live Process Explorer & Manager */}
        {processList && (
          <div style={{ marginTop: "var(--space-6)" }}>
            <SectionCard
              title={`Command Result: Running Processes on ${c.hostname} (${filteredProcesses.length} / ${processList.length})`}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  marginBottom: "var(--space-3)",
                  gap: "var(--space-3)",
                  flexWrap: "wrap",
                }}
              >
                <input
                  type="search"
                  placeholder="Filter by process name, PID, or user..."
                  value={processFilter}
                  onChange={(e) => setProcessFilter(e.target.value)}
                  style={{
                    minWidth: "280px",
                    padding: "var(--space-2) var(--space-3)",
                    background: "var(--surface)",
                    border: "1px solid var(--border)",
                    borderRadius: "var(--radius-sm)",
                    color: "var(--text)",
                    fontSize: "var(--font-sm)",
                  }}
                />
                <div style={{ display: "flex", gap: "var(--space-2)" }}>
                  <Button
                    variant="quiet"
                    size="md"
                    onClick={() => executeCommand("GET_PROCESSES")}
                    disabled={commandLoading}
                  >
                    Refresh Processes
                  </Button>
                  <Button
                    variant="secondary"
                    size="md"
                    onClick={() => {
                      setProcessList(null);
                      setCommandResult(null);
                      setActiveCommand(null);
                    }}
                  >
                    Close result
                  </Button>
                </div>
              </div>

              <div
                style={{
                  overflowX: "auto",
                  maxHeight: "420px",
                  overflowY: "auto",
                }}
              >
                <table
                  style={{
                    width: "100%",
                    borderCollapse: "collapse",
                    fontSize: "var(--font-xs)",
                  }}
                >
                  <thead>
                    <tr
                      style={{
                        borderBottom: "1px solid var(--border)",
                        textAlign: "left",
                      }}
                    >
                      <th style={{ padding: "8px" }}>PID</th>
                      <th style={{ padding: "8px" }}>Process Name</th>
                      <th style={{ padding: "8px" }}>User</th>
                      <th style={{ padding: "8px" }}>CPU %</th>
                      <th style={{ padding: "8px" }}>Memory %</th>
                      <th style={{ padding: "8px" }}>Status</th>
                      <th style={{ padding: "8px", textAlign: "right" }}>
                        Action
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredProcesses.length === 0 ? (
                      <tr>
                        <td
                          colSpan={7}
                          style={{
                            padding: "16px",
                            textAlign: "center",
                            color: "var(--text-muted)",
                          }}
                        >
                          No processes matching filter.
                        </td>
                      </tr>
                    ) : (
                      filteredProcesses.map((p, idx) => (
                        <tr
                          key={p.pid ?? idx}
                          style={{
                            borderBottom: "1px solid var(--border-subtle)",
                            fontFamily: "var(--font-mono)",
                          }}
                        >
                          <td
                            style={{
                              padding: "8px",
                              color: "var(--text-muted)",
                            }}
                          >
                            {p.pid ?? "—"}
                          </td>
                          <td
                            style={{
                              padding: "8px",
                              fontWeight: 600,
                              color: "var(--text)",
                            }}
                          >
                            {p.name ?? "unknown"}
                          </td>
                          <td
                            style={{
                              padding: "8px",
                              color: "var(--text-muted)",
                            }}
                          >
                            {p.username ?? "—"}
                          </td>
                          <td style={{ padding: "8px" }}>
                            {p.cpu_percent !== undefined
                              ? `${p.cpu_percent.toFixed(1)}%`
                              : "—"}
                          </td>
                          <td style={{ padding: "8px" }}>
                            {p.memory_percent !== undefined
                              ? `${p.memory_percent.toFixed(1)}%`
                              : "—"}
                          </td>
                          <td style={{ padding: "8px" }}>
                            <Badge variant="info">
                              {p.status ?? "RUNNING"}
                            </Badge>
                          </td>
                          <td style={{ padding: "8px", textAlign: "right" }}>
                            <button
                              className="btn btn--danger btn--sm"
                              style={{ padding: "2px 8px", fontSize: "11px" }}
                              disabled={commandLoading}
                              onClick={() => {
                                const target = p.name || String(p.pid);
                                setPendingConfirmation({
                                  kind: "kill",
                                  target,
                                });
                              }}
                            >
                              {killingProcess === (p.name || String(p.pid)) &&
                              commandLoading
                                ? "Killing..."
                                : "Kill"}
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
      </section>
      <section
        id="client-panel-network"
        role="tabpanel"
        aria-labelledby="client-tab-network"
        hidden={activeTab !== "network"}
        style={{ display: activeTab === "network" ? "block" : "none" }}
      >
        {passiveNeighbourhood &&
          (() => {
            const protocols = [
              ...new Set(
                passiveNeighbourhood.observations.map(
                  (observation) => observation.protocol,
                ),
              ),
            ].sort();
            const devices = new Set(
              passiveNeighbourhood.observations.map(
                (observation) =>
                  observation.mac_address ||
                  observation.ip_address ||
                  observation.hostname ||
                  observation.service_name ||
                  observation.device_type ||
                  observation.raw_fields?.usn ||
                  observation.protocol,
              ),
            );
            const latestObservation = passiveNeighbourhood.observations.reduce<
              string | null
            >(
              (latest, observation) =>
                observation.observed_at &&
                (!latest || observation.observed_at > latest)
                  ? observation.observed_at
                  : latest,
              null,
            );

            return (
              <div style={{ marginTop: "var(--space-6)", order: 2 }}>
                <SectionCard
                  title="Passive Network Information"
                  headerAction={
                    <Button
                      variant="quiet"
                      size="md"
                      onClick={() => setPassiveNeighbourhood(null)}
                    >
                      Close
                    </Button>
                  }
                >
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns:
                        "repeat(auto-fit, minmax(150px, 1fr))",
                      gap: "var(--space-3)",
                    }}
                  >
                    <MetricCard
                      label="Observations"
                      value={String(passiveNeighbourhood.observation_count)}
                    />
                    <MetricCard
                      label="Observed endpoints"
                      value={String(devices.size)}
                    />
                    <MetricCard
                      label="Protocols"
                      value={String(protocols.length)}
                    />
                  </div>
                  <div style={{ marginTop: "var(--space-4)" }}>
                    <DetailRow
                      label="Protocols detected"
                      value={protocols.length ? protocols.join(", ") : "None"}
                    />
                    <DetailRow
                      label="Latest observation"
                      value={
                        latestObservation
                          ? formatDateTime(latestObservation)
                          : "No observations"
                      }
                    />
                    <DetailRow
                      label="Snapshot received"
                      value={formatDateTime(passiveNeighbourhood.observed_at)}
                    />
                    <DetailRow
                      label="Reporter"
                      value={passiveNeighbourhood.reporter}
                      mono
                    />
                  </div>
                  <div
                    style={{ marginTop: "var(--space-4)", overflowX: "auto" }}
                  >
                    <table
                      style={{
                        width: "100%",
                        borderCollapse: "collapse",
                        fontSize: "var(--font-xs)",
                      }}
                    >
                      <thead>
                        <tr
                          style={{
                            borderBottom: "1px solid var(--border)",
                            textAlign: "left",
                          }}
                        >
                          <th style={{ padding: "8px" }}>Protocol</th>
                          <th style={{ padding: "8px" }}>
                            Observed device or service
                          </th>
                          <th style={{ padding: "8px" }}>Address</th>
                          <th style={{ padding: "8px" }}>
                            Advertisement details
                          </th>
                          <th style={{ padding: "8px" }}>Seen</th>
                          <th style={{ padding: "8px" }}>Latest</th>
                        </tr>
                      </thead>
                      <tbody>
                        {passiveNeighbourhood.observations.length === 0 ? (
                          <tr>
                            <td
                              colSpan={6}
                              style={{
                                padding: "16px",
                                textAlign: "center",
                                color: "var(--text-muted)",
                              }}
                            >
                              No passive protocol observations have been
                              collected in this client session.
                            </td>
                          </tr>
                        ) : (
                          passiveNeighbourhood.observations.map(
                            (observation, index) => {
                              const identity =
                                `${observation.device_name}
                           ${observation.service_name}
                           ${observation.hostname}
                           ${observation.device_type}
                          ${observation.raw_fields?.usn}` ||
                                "Unidentified observation";
                              const address = [
                                observation.ip_address,
                                observation.mac_address,
                              ]
                                .filter(Boolean)
                                .join("\n");
                              const details = [
                                observation.observation_kind,
                                observation.service_type,
                                observation.service_port
                                  ? `port ${observation.service_port}`
                                  : null,
                                observation.server,
                                observation.location,
                              ]
                                .filter(Boolean)
                                .join("\n");

                              return (
                                <tr
                                  key={`${observation.protocol}-${observation.observed_at ?? index}-${index}`}
                                  style={{
                                    borderBottom:
                                      "1px solid var(--border-subtle)",
                                  }}
                                >
                                  <td
                                    style={{
                                      padding: "8px",
                                      verticalAlign: "top",
                                    }}
                                  >
                                    <Badge variant="info">
                                      {observation.protocol}
                                    </Badge>
                                  </td>
                                  <td
                                    style={{
                                      padding: "8px",
                                      verticalAlign: "top",
                                      fontWeight: 600,
                                      maxWidth: "260px",
                                      wordBreak: "break-word",
                                    }}
                                  >
                                    {identity}
                                  </td>
                                  <td
                                    style={{
                                      padding: "8px",
                                      verticalAlign: "top",
                                      whiteSpace: "pre-line",
                                      fontFamily: "var(--font-mono)",
                                    }}
                                  >
                                    {address || "—"}
                                  </td>
                                  <td
                                    style={{
                                      padding: "8px",
                                      verticalAlign: "top",
                                      whiteSpace: "pre-line",
                                      maxWidth: "360px",
                                      overflowWrap: "anywhere",
                                      color: "var(--text-muted)",
                                    }}
                                  >
                                    {details || "—"}
                                  </td>
                                  <td
                                    style={{
                                      padding: "8px",
                                      verticalAlign: "top",
                                      textAlign: "right",
                                    }}
                                  >
                                    {observation.seen_count ?? 1}
                                  </td>
                                  <td
                                    style={{
                                      padding: "8px",
                                      verticalAlign: "top",
                                      whiteSpace: "nowrap",
                                      color: "var(--text-muted)",
                                    }}
                                  >
                                    {observation.observed_at
                                      ? formatDateTime(observation.observed_at)
                                      : "—"}
                                  </td>
                                </tr>
                              );
                            },
                          )
                        )}
                      </tbody>
                    </table>
                  </div>
                </SectionCard>
              </div>
            );
          })()}
      </section>

      <section
        id="client-panel-history"
        role="tabpanel"
        aria-labelledby="client-tab-history"
        hidden={activeTab !== "history"}
        style={{ display: activeTab === "history" ? "block" : "none" }}
      >
        <div id="screenshot-history" style={{ marginTop: "var(--space-6)" }}>
          <SectionCard
            title="Screenshot History"
            headerAction={
              <Button
                variant="quiet"
                size="md"
                onClick={refetchScreenshots}
                disabled={screenshotLoadingState}
              >
                Refresh
              </Button>
            }
          >
            {screenshotState.status === "error" &&
              !screenshotState.staleData && (
                <Notice variant="warning" title="Unable to load screenshots">
                  {screenshotState.error.message}
                </Notice>
              )}

            {screenshotState.status === "error" &&
              screenshotState.staleData && (
                <div style={{ marginBottom: "var(--space-4)" }}>
                  <Notice
                    variant="warning"
                    title="Stale screenshot history shown"
                  >
                    {screenshotState.error.message}
                  </Notice>
                </div>
              )}

            {screenshotLoadingState ? (
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
                  gap: "var(--space-4)",
                }}
              >
                {Array.from({ length: 4 }).map((_, index) => (
                  <div
                    key={index}
                    style={{
                      border: "1px solid var(--border)",
                      borderRadius: "var(--radius)",
                      overflow: "hidden",
                      background: "var(--surface-muted)",
                    }}
                  >
                    <Skeleton variant="icon" width="100%" height="160px" />
                    <div
                      style={{
                        padding: "var(--space-3)",
                        display: "grid",
                        gap: "var(--space-2)",
                      }}
                    >
                      <Skeleton variant="text-sm" width="80%" />
                      <Skeleton variant="text" width="60%" />
                      <Skeleton variant="text" width="40%" />
                    </div>
                  </div>
                ))}
              </div>
            ) : screenshotItems.length === 0 ? (
              <EmptyState
                icon="🖼️"
                title="No screenshots yet"
                body="Request a screenshot from an online interactive client to start building a history."
              />
            ) : (
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
                  gap: "var(--space-4)",
                }}
              >
                {screenshotItems.map((shot) => {
                  const fileUrl = api.getScreenshotFileUrl(shot.id);
                  return (
                    <div
                      key={shot.id}
                      style={{
                        border: "1px solid var(--border)",
                        borderRadius: "var(--radius)",
                        overflow: "hidden",
                        background: "var(--surface)",
                        boxShadow: "var(--shadow-sm)",
                      }}
                    >
                      <a
                        href={fileUrl}
                        target="_blank"
                        rel="noreferrer"
                        style={{
                          display: "block",
                          aspectRatio: "16 / 9",
                          background: "var(--surface-muted)",
                          overflow: "hidden",
                        }}
                      >
                        <img
                          src={fileUrl}
                          alt={`Screenshot captured ${shot.captured_at ? formatDateTime(shot.captured_at) : "recently"}`}
                          style={{
                            width: "100%",
                            height: "100%",
                            objectFit: "cover",
                            display: "block",
                          }}
                        />
                      </a>
                      <div
                        style={{
                          padding: "var(--space-3)",
                          display: "grid",
                          gap: "var(--space-2)",
                        }}
                      >
                        <div
                          style={{
                            display: "flex",
                            justifyContent: "space-between",
                            gap: "var(--space-2)",
                          }}
                        >
                          <p style={{ fontSize: "var(--font-xs)" }}>
                            {shot.filename.slice(0, 24) + (shot.filename.length > 24 ? "…" : "")}
                          </p>
                          <Badge
                            variant={
                              shot.status === "FAILED" ? "danger" : "success"
                            }
                          >
                            {shot.status.toLowerCase()}
                          </Badge>
                        </div>
                        <div
                          style={{
                            fontSize: "var(--font-xs)",
                            color: "var(--text-muted)",
                          }}
                        >
                          {shot.captured_at
                            ? formatRelative(shot.captured_at)
                            : "Capture time unavailable"}
                        </div>
                        <div style={{ fontSize: "var(--font-xs)" }}>
                          <DetailRow
                            label="Captured"
                            value={
                              shot.captured_at
                                ? formatDateTime(shot.captured_at)
                                : null
                            }
                          />
                          <DetailRow
                            label="Size"
                            value={formatBytes(shot.file_size)}
                          />
                          <DetailRow
                            label="Requested by"
                            value={
                              shot.requested_by || "local-network-operator"
                            }
                            mono
                          />
                        </div>
                        <div
                          style={{
                            display: "flex",
                            gap: "var(--space-2)",
                            flexWrap: "wrap",
                          }}
                        >
                          <Button
                            variant="secondary"
                            size="sm"
                            onClick={() =>
                              window.open(
                                fileUrl,
                                "_blank",
                                "noopener,noreferrer",
                              )
                            }
                          >
                            Open full size
                          </Button>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </SectionCard>
        </div>

        {/* Command Output Inspector (when non-process commands are run) */}
        {commandResult && activeCommand !== "GET_PROCESSES" && (
          <div style={{ marginTop: "var(--space-6)", order: 1 }}>
            <SectionCard title={`Command Result: ${activeCommand}`}>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  marginBottom: "var(--space-3)",
                }}
              >
                <Badge variant="success">Status: OK</Badge>
                <Button
                  variant="quiet"
                  size="md"
                  onClick={() => {
                    setCommandResult(null);
                    setActiveCommand(null);
                  }}
                >
                  Close result
                </Button>
              </div>
              {activeCommand === "REQUEST_SCREENSHOT" ? (
                <div style={{ display: "grid", gap: "var(--space-3)" }}>
                  {capturedScreenshot ? (
                    <img
                      src={api.getScreenshotFileUrl(capturedScreenshot.id)}
                      alt={`Captured screenshot ${capturedScreenshot.filename}`}
                      style={{
                        width: "100%",
                        maxHeight: "520px",
                        objectFit: "contain",
                        display: "block",
                        borderRadius: "var(--radius)",
                        background: "var(--surface-muted)",
                        border: "1px solid var(--border)",
                      }}
                    />
                  ) : (
                    <Notice variant="info" title="Preparing screenshot preview">
                      The screenshot was captured. Refresh the history to load
                      its preview.
                    </Notice>
                  )}
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      flexWrap: "wrap",
                      gap: "var(--space-3)",
                      padding: "var(--space-2) var(--space-3)",
                      background: "var(--surface-muted)",
                      border: "1px solid var(--border-subtle)",
                      borderRadius: "var(--radius-sm)",
                      fontSize: "var(--font-xs)",
                    }}
                  >
                    <span>
                      <span style={{ color: "var(--text-muted)" }}>
                        Status:{" "}
                      </span>
                      <strong>{commandResult.status ?? "unknown"}</strong>
                    </span>
                    <span style={{ minWidth: 0, overflowWrap: "anywhere" }}>
                      <span style={{ color: "var(--text-muted)" }}>File: </span>
                      <strong>{commandResult.filename ?? "Unavailable"}</strong>
                    </span>
                    <span>
                      <span style={{ color: "var(--text-muted)" }}>
                        Captured:{" "}
                      </span>
                      <strong>
                        {commandResult.captured_at
                          ? formatRelative(commandResult.captured_at)
                          : "Unavailable"}
                      </strong>
                    </span>
                    <div style={{ marginLeft: "auto" }}>
                      <Button
                        variant="secondary"
                        size="md"
                        onClick={() => {
                          refetchScreenshots();
                          document
                            .getElementById("screenshot-history")
                            ?.scrollIntoView({
                              behavior: "smooth",
                              block: "start",
                            });
                        }}
                      >
                        Show in history
                      </Button>
                    </div>
                  </div>
                </div>
              ) : (
                <pre
                  style={{
                    background: "var(--surface-muted)",
                    padding: "var(--space-4)",
                    borderRadius: "var(--radius)",
                    border: "1px solid var(--border)",
                    fontFamily: "var(--font-mono)",
                    fontSize: "var(--font-xs)",
                    overflowX: "auto",
                    maxHeight: "360px",
                    color: "var(--text)",
                  }}
                >
                  {JSON.stringify(commandResult.data ?? commandResult, null, 2)}
                </pre>
              )}
            </SectionCard>
          </div>
        )}

        {/* Two columns Details */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(360px, 1fr))",
            gap: "var(--space-6)",
            marginTop: "var(--space-6)",
            order: 3,
          }}
        >
          {/* Identity */}
          <SectionCard title="Identity">
            <div>
              <DetailRow label="Client ID" value={c.id} mono />
              <DetailRow label="Hostname" value={c.hostname} />
              <DetailRow label="IP Address" value={c.ip_address} mono />
              <DetailRow label="MAC Address" value={c.mac_address} mono />
              <DetailRow label="Client version" value={c.client_version} mono />
              <DetailRow
                label="Version reported"
                value={formatDateTime(c.client_version_updated_at)}
              />
              <DetailRow
                label="Registered"
                value={formatDateTime(c.created_at)}
              />
              <DetailRow
                label="Last updated"
                value={formatDateTime(c.updated_at)}
              />
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
              <p
                style={{
                  fontSize: "var(--font-sm)",
                  color: "var(--text-muted)",
                }}
              >
                No connection records.
              </p>
            ) : (
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: "var(--space-3)",
                }}
              >
                {d.recent_connections.slice(0, 8).map((conn, i) => (
                  <div
                    key={i}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "1fr 1fr",
                      gap: "var(--space-2)",
                      fontSize: "var(--font-xs)",
                      padding: "var(--space-2)",
                      background: "var(--surface-muted)",
                      borderRadius: "var(--radius-sm)",
                    }}
                  >
                    <div>
                      <span style={{ color: "var(--text-muted)" }}>
                        Connected{" "}
                      </span>
                      {formatDateTime(conn.connected_at)}
                    </div>
                    <div>
                      <span style={{ color: "var(--text-muted)" }}>
                        Disconnected{" "}
                      </span>
                      {conn.disconnected_at ? (
                        formatDateTime(conn.disconnected_at)
                      ) : (
                        <span style={{ color: "var(--success)" }}>Active</span>
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
                <DetailRow
                  label="Log ID"
                  value={String(d.latest_activity_log.id)}
                />
                <DetailRow
                  label="Period"
                  value={d.latest_activity_log.period}
                />
                <DetailRow
                  label="Generated"
                  value={formatDateTime(d.latest_activity_log.generated_at)}
                />
                <DetailRow
                  label="Received"
                  value={formatDateTime(d.latest_activity_log.received_at)}
                />
              </div>
              <div style={{ marginTop: "var(--space-3)" }}>
                <a
                  href={`/activity/${d.latest_activity_log.id}`}
                  className="btn btn--secondary btn--sm"
                  style={{ textDecoration: "none" }}
                >
                  View log →
                </a>
              </div>
            </SectionCard>
          )}
        </div>
      </section>
    </div>
  );
}

function uniqueNumbers(values: Array<number | null | undefined>): number[] {
  return Array.from(
    new Set(values.filter((value): value is number => value != null)),
  ).sort((left, right) => left - right);
}

function LocationSelect({
  label,
  value,
  options,
  disabled,
  onChange,
}: {
  label: string;
  value: string;
  options: number[];
  disabled?: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <label
      style={{
        display: "grid",
        gap: "var(--space-1)",
        fontSize: "var(--font-xs)",
        color: "var(--text-muted)",
      }}
    >
      {label}
      <select
        aria-label={label}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        style={{
          minWidth: 90,
          background: "var(--surface)",
          color: "var(--text)",
          border: "1px solid var(--border)",
          borderRadius: "var(--radius-sm)",
          padding: "var(--space-2)",
        }}
      >
        <option value="">Select</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}

function ClientDetailSkeleton() {
  return (
    <div>
      <div
        style={{
          display: "flex",
          gap: "var(--space-3)",
          marginBottom: "var(--space-5)",
        }}
      >
        <Skeleton variant="text-sm" width="5rem" />
      </div>
      <div
        style={{
          display: "flex",
          gap: "var(--space-4)",
          marginBottom: "var(--space-6)",
          paddingBottom: "var(--space-4)",
          borderBottom: "1px solid var(--border)",
        }}
      >
        <Skeleton
          style={{
            width: 48,
            height: 48,
            borderRadius: "var(--radius)",
            flexShrink: 0,
          }}
        />
        <div style={{ flex: 1 }}>
          <Skeleton
            variant="title"
            style={{ marginBottom: "var(--space-2)" }}
          />
          <Skeleton variant="badge" />
        </div>
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(360px, 1fr))",
          gap: "var(--space-6)",
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
                    display: "grid",
                    gridTemplateColumns: "10rem 1fr",
                    gap: "var(--space-3)",
                    padding: "var(--space-2) 0",
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
