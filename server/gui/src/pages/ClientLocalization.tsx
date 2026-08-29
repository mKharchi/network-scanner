import { useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { api, type ClientLocalizationDebug, type ManagedClientSummary } from "../api/client";
import { useFetch } from "../hooks/useFetch";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import { Button } from "../components/Button";
import { SectionCard } from "../components/Card";
import { EmptyState, ErrorState, Notice, Skeleton } from "../components/States";
import { ClientStatusBadge } from "../components/Badge";

function coordinateValue(value: number | null | undefined): string {
  return value == null ? "—" : value.toFixed(2);
}

function DataRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--space-4)", padding: "var(--space-2) 0", borderBottom: "1px solid var(--border)" }}>
      <span style={{ color: "var(--text-muted)", fontSize: "var(--font-sm)" }}>{label}</span>
      <strong style={{ textAlign: "right", fontSize: "var(--font-sm)" }}>{value}</strong>
    </div>
  );
}

export function ClientLocalizationPage() {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search);
  const [selectedClientId, setSelectedClientId] = useState<string>("");
  const [highlighted, setHighlighted] = useState(false);

  const { state: clientsState, refetch: refetchClients } = useFetch<{ items: ManagedClientSummary[] }>(
    () => api.getClients({ search: debouncedSearch || undefined, limit: 200 }),
    [debouncedSearch],
    ["app:client_status"],
  );

  const clients = clientsState.status === "success"
    ? clientsState.data.items
    : clientsState.status === "error" && clientsState.staleData
      ? clientsState.staleData.items
      : [];

  const selectedClient = useMemo(
    () => clients.find((client) => client.id === selectedClientId) || null,
    [clients, selectedClientId],
  );

  const { state: debugState, refetch: refetchDebug } = useFetch<ClientLocalizationDebug>(
    selectedClient ? () => api.getClientLocalizationDebug(selectedClient.id) : null,
    [selectedClient?.id],
  );

  const debugData = debugState.status === "success"
    ? debugState.data
    : debugState.status === "error" && debugState.staleData
      ? debugState.staleData
      : null;

  const locateClient = () => {
    if (!selectedClient) return;
    const query = selectedClient.ip_address || selectedClient.mac_address || selectedClient.hostname;
    navigate(`/digital-twin?client=${encodeURIComponent(selectedClient.id)}&search=${encodeURIComponent(query)}`);
  };

  const highlightClient = () => {
    if (!selectedClient || !debugData?.location) return;
    setHighlighted(true);
    navigate(`/digital-twin?client=${encodeURIComponent(selectedClient.id)}&search=${encodeURIComponent(selectedClient.hostname)}`);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-5)" }}>
      <div className="page-header">
        <div>
          <h1 className="page-title">Client Localization</h1>
          <p className="page-description">
            Validation view for the client → location → coordinate → renderer chain.
          </p>
        </div>
        <Button variant="quiet" size="sm" onClick={() => refetchClients()}>Refresh</Button>
      </div>

      {clientsState.status === "error" && (
        <Notice variant="warning" title="Client list unavailable">
          {clientsState.error.message}
        </Notice>
      )}

      <SectionCard title="Select client">
        <div style={{ display: "grid", gridTemplateColumns: "minmax(220px, 1fr) minmax(220px, 2fr)", gap: "var(--space-3)" }}>
          <select
            value={selectedClientId}
            onChange={(event) => { setSelectedClientId(event.target.value); setHighlighted(false); }}
            aria-label="Select client for localization validation"
            style={{ minHeight: 40, padding: "0 var(--space-3)", border: "1px solid var(--border)", borderRadius: "var(--radius)", background: "var(--surface)", color: "var(--text)" }}
          >
            <option value="">Choose a registered client…</option>
            {clients.map((client) => (
              <option key={client.id} value={client.id}>{client.hostname} — {client.id}</option>
            ))}
          </select>
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search hostname, IP, MAC, or client ID…"
            aria-label="Search clients for localization validation"
            style={{ minHeight: 40, padding: "0 var(--space-3)", border: "1px solid var(--border)", borderRadius: "var(--radius)", background: "var(--surface)", color: "var(--text)" }}
          />
        </div>
      </SectionCard>

      {!selectedClient && (
        <EmptyState icon="📍" title="Select a client to inspect its localization" body="The page will show the server-assigned location and the raw coordinates used by the Digital Twin." />
      )}

      {selectedClient && debugState.status === "loading" && (
        <SectionCard title="Loading localization chain"><Skeleton variant="text-lg" width="16rem" /><Skeleton variant="text" width="24rem" /></SectionCard>
      )}

      {selectedClient && debugState.status === "error" && !debugData && (
        <ErrorState title="Unable to load localization data" message={debugState.error.message} onRetry={() => refetchDebug()} />
      )}

      {debugData && (
        <>
          {highlighted && <Notice variant="info" title="Client selected for validation">Use Locate to open the Digital Twin and focus this client.</Notice>}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "var(--space-4)" }}>
            <SectionCard title="Client">
              <DataRow label="Hostname" value={debugData.client.hostname} />
              <DataRow label="Client ID" value={<code>{debugData.client.client_id}</code>} />
              <DataRow label="MAC" value={<code>{debugData.client.mac || "—"}</code>} />
              <DataRow label="IP" value={<code>{debugData.client.ip || "—"}</code>} />
              <div style={{ marginTop: "var(--space-3)" }}><ClientStatusBadge state={selectedClient?.connection.state || "OFFLINE"} /></div>
            </SectionCard>

            <SectionCard title="Server location">
              {debugData.location ? (
                <>
                  <DataRow label="Floor" value={`Floor ${debugData.location.floor}`} />
                  <DataRow label="Location" value={debugData.location.label} />
                  <DataRow label="Zone" value={debugData.location.zone_name || debugData.location.zone_type} />
                  <DataRow label="Aisle / table" value={`${debugData.location.aisle ?? "—"} / ${debugData.location.table ?? "—"}`} />
                  <DataRow label="Position" value={debugData.location.position ?? "—"} />
                </>
              ) : (
                <Notice variant="warning" title="No location assigned">Assign this client to a seeded PC position before validating its physical placement.</Notice>
              )}
            </SectionCard>

            <SectionCard title="Raw server coordinates">
              <DataRow label="X" value={coordinateValue(debugData.server_coordinates.x)} />
              <DataRow label="Y" value={coordinateValue(debugData.server_coordinates.y)} />
              <DataRow label="Z" value={coordinateValue(debugData.server_coordinates.z)} />
              <DataRow label="Coordinate system" value={debugData.coordinate_system.name} />
              <DataRow label="Origin" value={debugData.coordinate_system.origin || "—"} />
              <DataRow label="Units" value={debugData.coordinate_system.unit} />
            </SectionCard>

            <SectionCard title="Renderer transformation">
              <DataRow label="Renderer" value={debugData.transformation.renderer} />
              <DataRow label="Projection" value={debugData.transformation.name} />
              <DataRow label="Floor height" value={`${debugData.coordinate_system.floor_height} units`} />
              <p style={{ margin: "var(--space-3) 0 0", color: "var(--text-muted)", fontSize: "var(--font-sm)" }}>{debugData.transformation.note}</p>
              <div style={{ display: "flex", gap: "var(--space-2)", marginTop: "var(--space-4)", flexWrap: "wrap" }}>
                <Button variant="primary" onClick={locateClient} disabled={!debugData.location}>Locate in 3D Twin</Button>
                <Button variant="secondary" onClick={highlightClient} disabled={!debugData.location}>Highlight</Button>
                <Button variant="quiet" onClick={() => selectedClient && navigate(`/clients/${encodeURIComponent(selectedClient.id)}`)}>Inspect client</Button>
              </div>
            </SectionCard>
          </div>
          <p style={{ color: "var(--text-muted)", fontSize: "var(--font-xs)" }}>Last server update: {debugData.last_updated || "—"}</p>
        </>
      )}
    </div>
  );
}
