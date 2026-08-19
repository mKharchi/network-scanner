/**
 * API client for GET /api/v1/...
 *
 * All responses use the envelope:
 *   { data: T, meta: {} }
 * Errors use:
 *   { error: { code: string, message: string } }
 */

const API_ORIGIN =
  import.meta.env.VITE_API_URL ||
  (typeof window !== "undefined" && window.location.port === "8080"
    ? window.location.origin
    : "http://127.0.0.1:8080");

const BASE = "/api/v1";

export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function get<T>(
  path: string,
  params?: Record<string, string>,
): Promise<T> {
  const baseWithApi = API_ORIGIN.replace(/\/+$/, "") + BASE;
  const url = new URL(baseWithApi + path);
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") {
        url.searchParams.set(k, v);
      }
    });
  }

  const fullUrl = url.toString();
  console.log(`[API ->] GET ${fullUrl}`);

  try {
    const response = await fetch(fullUrl, {
      method: "GET",
      headers: { Accept: "application/json" },
    });

    const body = await response.json().catch(() => null);

    if (!response.ok) {
      const code = body?.error?.code ?? "UNKNOWN_ERROR";
      const message = body?.error?.message ?? `HTTP ${response.status}`;
      console.warn(`[API <-] ${response.status} Error on ${path}:`, {
        code,
        message,
      });
      throw new ApiError(code, message, response.status);
    }

    console.log(`[API <-] 200 OK for ${path}`, body?.data);
    return body.data as T;
  } catch (err) {
    if (err instanceof ApiError) {
      throw err;
    }
    const message = err instanceof Error ? err.message : String(err);
    console.error(
      `[API Network Failure] Could not reach backend at ${fullUrl}:`,
      message,
    );
    throw new ApiError(
      "NETWORK_ERROR",
      `Cannot connect to server at ${API_ORIGIN}: ${message}`,
      0,
    );
  }
}

// ── Shared view models ────────────────────────────────────────────

export interface ClientOS {
  system: string | null;
  release: string | null;
  version: string | null;
  machine: string | null;
}

export interface ClientConnection {
  state: "ONLINE" | "OFFLINE";
  last_connected_at: string | null;
  last_disconnected_at: string | null;
}

export interface ManagedClientSummary {
  id: string;
  database_id: number;
  hostname: string;
  ip_address: string | null;
  mac_address: string;
  os: ClientOS;
  connection: ClientConnection;
  created_at: string;
  updated_at: string;
}

export interface NetworkDeviceOS {
  name: string | null;
  family: string | null;
  confidence: number | null;
}

export interface NetworkDevice {
  mac_address: string;
  ip_address: string | null;
  hostname: string | null;
  vendor: string | null;
  os: NetworkDeviceOS;
  classification: "MANAGED" | "UNMANAGED" | "UNKNOWN";
  is_managed: boolean;
  managed_client_id: string | null;
  last_observed_at: string | null;
  sources: string[];
}

export interface GlobalNetworkScan {
  id: string;
  status: "started" | "already_running" | "pending" | "running" | "completed" | "partial";
  total_clients: number;
  clients_dispatched: number;
  started: number;
  completed: number;
  failed: number;
  skipped: number;
  running: number;
  pending: number;
  devices_found: number;
  started_at: string;
  updated_at: string;
  finished_at: string | null;
  max_concurrent_clients: number;
}

export interface Alert {
  id: number;
  client: { id: string; hostname: string } | null;
  type: string;
  severity: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  status: "NEW" | "ACKNOWLEDGED" | "RESOLVED";
  detected_at: string;
  activity_time: string | null;
  title: string;
  description: string;
  activity_log_id: number | null;
}

export interface ActivityLogRecord {
  id: number;
  client: { id: string; hostname: string } | null;
  period: string;
  generated_at: string;
  received_at: string;
}

// ── Dashboard ─────────────────────────────────────────────────────

export interface DashboardData {
  generated_at: string;
  clients: { online: number; offline: number; total: number };
  alerts: { new: number; critical: number };
  latest_scan: {
    completed_at: string;
    devices_found: number;
    scan_id: string;
  } | null;
  dhcp_today: { date: string; observations: number } | null;
  recent_alerts: Alert[];
  online_clients: ManagedClientSummary[];
}

export const api = {
  // Dashboard
  getDashboard: () => get<DashboardData>("/dashboard"),

  // Clients
  getClients: (params?: {
    state?: string;
    search?: string;
    limit?: number;
    cursor?: string;
  }) =>
    get<{ items: ManagedClientSummary[]; next_cursor: string | null }>(
      "/clients",
      {
        state: params?.state ?? "",
        search: params?.search ?? "",
        limit: String(params?.limit ?? 50),
        cursor: params?.cursor ?? "",
      },
    ),

  getClient: (clientId: string) =>
    get<{
      client: ManagedClientSummary;
      recent_connections: {
        connected_at: string;
        disconnected_at: string | null;
      }[];
      alert_counts: { new: number; total: number };
      latest_activity_log: ActivityLogRecord | null;
    }>(`/clients/${encodeURIComponent(clientId)}`),

  // Network scans
  getLatestScan: () =>
    get<{
      scan: {
        id: string;
        completed_at: string;
        network: {
          interface: string;
          local_ip: string | null;
          network: string;
          gateway: string | null;
        };
        devices_found: number;
        devices: NetworkDevice[];
      };
    }>("/network/scans/latest"),

  getScanHistory: (params?: {
    from?: string;
    to?: string;
    limit?: number;
    cursor?: string;
  }) =>
    get<{
      items: {
        id: string;
        completed_at: string;
        devices_found: number;
        network: Record<string, unknown>;
      }[];
      next_cursor: string | null;
    }>("/network/scans", {
      from: params?.from ?? "",
      to: params?.to ?? "",
      limit: String(params?.limit ?? 50),
      cursor: params?.cursor ?? "",
    }),

  getScan: (scanId: string) =>
    get<{
      scan: {
        id: string;
        completed_at: string;
        devices_found: number;
        devices: NetworkDevice[];
      };
    }>(`/network/scans/${encodeURIComponent(scanId)}`),

  getNetworkDevice: (mac: string) =>
    get<{
      device: NetworkDevice;
      observations: {
        source_type: string;
        source_client_id: string | null;
        ip_address: string | null;
        interface: string | null;
        entry_type: string;
        observed_at: string;
      }[];
      dhcp_observations: unknown[];
    }>(`/network/devices/${encodeURIComponent(mac)}`),

  // DHCP
  getDhcp: (params?: {
    date?: string;
    reporter_mac?: string;
    limit?: number;
    cursor?: string;
  }) =>
    get<{
      date: string;
      items: {
        received_at: string;
        reporting_client_mac: string;
        neighbours: unknown[];
        dhcp: {
          message_type: number;
          vendor_class: string | null;
          client_id: string | null;
        };
      }[];
      next_cursor: string | null;
    }>("/network/dhcp", {
      date: params?.date ?? "",
      reporter_mac: params?.reporter_mac ?? "",
      limit: String(params?.limit ?? 100),
      cursor: params?.cursor ?? "",
    }),

  // Alerts
  getAlerts: (params?: {
    status?: string;
    severity?: string;
    client_id?: string;
    from?: string;
    to?: string;
    limit?: number;
    cursor?: string;
  }) =>
    get<{ items: Alert[]; next_cursor: string | null }>("/alerts", {
      status: params?.status ?? "",
      severity: params?.severity ?? "",
      client_id: params?.client_id ?? "",
      from: params?.from ?? "",
      to: params?.to ?? "",
      limit: String(params?.limit ?? 50),
      cursor: params?.cursor ?? "",
    }),

  getAlert: (alertId: number) =>
    get<{
      alert: Alert;
      client: ManagedClientSummary | null;
      activity_log: ActivityLogRecord | null;
    }>(`/alerts/${alertId}`),

  // Activity logs
  getActivityLogs: (params?: {
    client_id?: string;
    period?: string;
    from?: string;
    to?: string;
    limit?: number;
    cursor?: string;
  }) =>
    get<{ items: ActivityLogRecord[]; next_cursor: string | null }>(
      "/activity-logs",
      {
        client_id: params?.client_id ?? "",
        period: params?.period ?? "",
        from: params?.from ?? "",
        to: params?.to ?? "",
        limit: String(params?.limit ?? 50),
        cursor: params?.cursor ?? "",
      },
    ),

  getActivityLog: (logId: number) =>
    get<{
      log: ActivityLogRecord;
      since: string | null;
      activity: { time: string; type: string; detail: unknown }[];
    }>(`/activity-logs/${logId}`),

  // Settings
  getWorkingHours: () =>
    get<{
      rules: {
        day_of_week: number;
        start_time: string;
        end_time: string;
        enabled: boolean;
      }[];
      current_status: { within_working_hours: boolean; checked_at: string };
    }>("/settings/working-hours"),

  getForbiddenProcesses: () =>
    get<{
      items: {
        process_name: string;
        severity: string;
        enabled: boolean;
        description: string | null;
      }[];
    }>("/settings/forbidden-processes"),

  // Client commands
  listClientCommands: (clientId: string) =>
    get<{ items: { command: string; label: string }[] }>(
      `/clients/${encodeURIComponent(clientId)}/commands`,
    ),

  runClientCommand: (clientId: string, command: string, args?: any) =>
    (async () => {
      const baseWithApi = API_ORIGIN.replace(/\/+$/, "") + BASE;
      const url =
        baseWithApi + `/clients/${encodeURIComponent(clientId)}/commands`;
      const resp = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify({ command, args }),
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => null);
        const code = body?.error?.code ?? "UNKNOWN_ERROR";
        const message = body?.error?.message ?? `HTTP ${resp.status}`;
        throw new ApiError(code, message, resp.status);
      }
      return (await resp.json()).data;
    })(),

  triggerManualScan: () =>
    (async () => {
      const baseWithApi = API_ORIGIN.replace(/\/+$/, "") + BASE;
      const url = baseWithApi + '/network/scans';
      const resp = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
        },
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => null);
        const code = body?.error?.code ?? 'UNKNOWN_ERROR';
        const message = body?.error?.message ?? `HTTP ${resp.status}`;
        throw new ApiError(code, message, resp.status);
      }
      return (await resp.json()).data;
    })(),

  triggerActiveScan: () =>
    (async () => {
      const baseWithApi = API_ORIGIN.replace(/\/+$/, "") + BASE;
      const url = baseWithApi + '/network/scans/active';
      const resp = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
        },
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => null);
        const code = body?.error?.code ?? 'UNKNOWN_ERROR';
        const message = body?.error?.message ?? `HTTP ${resp.status}`;
        throw new ApiError(code, message, resp.status);
      }
      return (await resp.json()).data;
    })(),

  triggerGlobalActiveScan: () =>
    (async () => {
      const baseWithApi = API_ORIGIN.replace(/\/+$/, "") + BASE;
      const url = baseWithApi + "/network/scans/global-active";
      const resp = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => null);
        const code = body?.error?.code ?? "UNKNOWN_ERROR";
        const message = body?.error?.message ?? `HTTP ${resp.status}`;
        throw new ApiError(code, message, resp.status);
      }
      return (await resp.json()).data as GlobalNetworkScan;
    })(),

  getGlobalActiveScan: (scanId?: string) =>
    get<GlobalNetworkScan>(
      scanId
        ? `/network/scans/global-active/${encodeURIComponent(scanId)}`
        : "/network/scans/global-active",
    ),
};
