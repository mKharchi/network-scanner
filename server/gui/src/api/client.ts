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

async function patch<T>(path: string, payload: unknown): Promise<T> {
  const baseWithApi = API_ORIGIN.replace(/\/+$/, "") + BASE;
  const fullUrl = baseWithApi + path;
  const response = await fetch(fullUrl, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(
      body?.error?.code ?? "UNKNOWN_ERROR",
      body?.error?.message ?? `HTTP ${response.status}`,
      response.status,
    );
  }
  return body?.data as T;
}

async function post<T>(path: string, payload: unknown = {}): Promise<T> {
  const baseWithApi = API_ORIGIN.replace(/\/+$/, "") + BASE;
  const fullUrl = baseWithApi + path;
  const response = await fetch(fullUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(
      body?.error?.code ?? "UNKNOWN_ERROR",
      body?.error?.message ?? `HTTP ${response.status}`,
      response.status,
    );
  }
  return body?.data as T;
}

async function postAction<T>(path: string, payload: unknown = {}): Promise<T> {
  const fullUrl = API_ORIGIN.replace(/\/+$/, "") + path;
  const response = await fetch(fullUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(
      body?.error?.code ?? "UNKNOWN_ERROR",
      body?.error?.message ?? `HTTP ${response.status}`,
      response.status,
    );
  }
  return body?.data as T;
}

async function getAction<T>(path: string): Promise<T> {
  const response = await fetch(API_ORIGIN.replace(/\/+$/, "") + path, {
    headers: { Accept: "application/json" },
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(
      body?.error?.code ?? "UNKNOWN_ERROR",
      body?.error?.message ?? `HTTP ${response.status}`,
      response.status,
    );
  }
  return body?.data as T;
}

async function mutate<T>(method: "PUT" | "DELETE", path: string, payload?: unknown): Promise<T> {
  const fullUrl = API_ORIGIN.replace(/\/+$/, "") + BASE + path;
  const response = await fetch(fullUrl, {
    method,
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(
      body?.error?.code ?? "UNKNOWN_ERROR",
      body?.error?.message ?? `HTTP ${response.status}`,
      response.status,
    );
  }
  return body?.data as T;
}

// ── Shared view models ────────────────────────────────────────────

export interface ClientOS {
  system: string | null;
  release: string | null;
  version: string | null;
  machine: string | null;
}

export interface ForbiddenProcessRule {
  id?: number;
  process_name: string;
  severity: string;
  enabled: boolean;
  description: string | null;
}

export interface ActionProgress {
  total: number;
  completed: number;
  succeeded: number;
  failed: number;
  in_progress: number;
  pending: number;
}

export interface ActionTargetStatus {
  client_id?: string;
  status?: string;
  result?: Record<string, unknown> | any;
  error?: Record<string, unknown> | any;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface ActionDetail {
  action_id: string;
  action_type?: string;
  status: string;
  progress?: ActionProgress;
  targets?: ActionTargetStatus[];
  result?: { targets?: ActionTargetStatus[] };
  created_at?: string;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface PackageUpload {
  package_id: string;
  filename: string;
  size_bytes: number;
  sha256: string;
  storage_path?: string;
  uploaded_by?: string | null;
  created_at?: string;
}

export interface BulkUpdatePerClientStatus {
  action_id: string;
  client_id: string;
  hostname: string;
  status: string;
  result: Record<string, unknown>;
}

export interface BulkUpdateDetail {
  bulk_update_id: string;
  package_id: string;
  created_at: string | null;
  created_by?: string | null;
  target_count: number;
  aggregate_status: {
    total: number;
    pending: number;
    running: number;
    completed: number;
    failed: number;
  };
  per_client_status: BulkUpdatePerClientStatus[];
}

export interface BulkUpdateSummary {
  bulk_update_id: string;
  package_id: string;
  created_at: string | null;
  created_by?: string | null;
  target_selection_strategy: string;
  target_count: number;
  aggregate_status: {
    total: number;
    completed: number;
    failed: number;
    pending: number;
  };
}

export interface BulkUpdateCreateResponse {
  bulk_update_id: string;
  package_id: string;
  target_count: number;
  actions: { action_id: string; client_id: string; status: string }[];
  aggregate_status: {
    total: number;
    pending: number;
    running: number;
    completed: number;
    failed: number;
  };
}

export interface ClientLocalizationDebug {
  client: {
    database_id: number;
    client_id: string;
    hostname: string;
    mac: string | null;
    ip: string | null;
  };
  location: (ClientLocation & { table?: number | null; row?: number | null }) | null;
  location_assignment?: LocationAssignment | null;
  server_coordinates: { x: number | null; y: number | null; z: number | null };
  coordinate_system: {
    name: string;
    unit: string;
    origin: string | null;
    axis: Record<string, string>;
    floor_height: number;
  };
  render_coordinates: { x: number; y: number; z: number } | null;
  transformation: { name: string; renderer: string; note: string };
  last_updated: string | null;
}

export interface ClientConnection {
  state: "ONLINE" | "OFFLINE" | "ISOLATED";
  last_connected_at: string | null;
  last_disconnected_at: string | null;
  isolation?: {
    status?: string;
    reason?: string;
    isolated_at?: string;
  };
}

export interface PassiveProtocolObservation {
  protocol: "mdns" | "llmnr" | "nbns" | "ssdp";
  observed_at?: string;
  first_observed_at?: string;
  seen_count?: number;
  observation_kind?: "query" | "response" | "announcement" | "search" | "advertisement";
  ip_address?: string;
  mac_address?: string;
  hostname?: string;
  device_name?: string;
  service_type?: string;
  service_name?: string;
  service_port?: number;
  device_type?: string;
  vendor?: string;
  model?: string;
  server?: string;
  location?: string;
  raw_fields?: {
    usn?: string;
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

export interface ClientPassiveNeighbourhood {
  status: "completed";
  client_id: string;
  timeout_seconds: number;
  observed_at: string;
  reporter: string;
  observations: PassiveProtocolObservation[];
  observation_count: number;
}

export interface ClientHealth {
  status: 'healthy' | 'warning' | 'critical' | 'isolated' | 'offline' | 'empty';
  cpu_percent: number | null;
  memory_percent: number | null;
  disk_percent: number | null;
  open_alert_severity: string | null;
  updated_at: string | null;
}

export interface LocationAssignment {
  method: 'AUTO' | 'MANUAL' | null;
  status: 'PENDING' | 'ASSIGNED' | 'CONFIRMED' | null;
  confidence: number | null;
  verified: boolean;
  assigned_at: string | null;
  assigned_by: string | null;
  last_calculated_at: string | null;
  source: string | null;
  evidence: unknown;
  failure_reason?: string | null;
}

export interface ClientLocation {
  id: number;
  floor: number;
  location_type?: string;
  zone_type: string;
  zone_name: string | null;
  aisle: number | null;
  table: number | null;
  row: number | null;
  column?: number | null;
  position: number | null;
  label: string;
  parent_id?: number | null;
  x?: number | null;
  y?: number | null;
  z?: number | null;
  is_restricted?: boolean;
  assignable?: boolean;
  hostname?: string | null;
  client_id?: string;
  client_state?: 'ONLINE' | 'OFFLINE' | 'ISOLATED';
  health?: ClientHealth;
  health_status?: string;
  assignment?: LocationAssignment | null;
}

export interface SpatialSensor {
  id: number;
  sensor_id: string;
  name: string;
  type: string;
  client_id?: number | null;
  client_code?: string | null;
  client_hostname?: string | null;
  location_id?: number | null;
  location_label?: string | null;
  floor?: number | null;
  x?: number | null;
  y?: number | null;
  z?: number | null;
  capabilities: string[];
  status: "ONLINE" | "OFFLINE" | "DEGRADED";
  last_seen?: string | null;
  created_at?: string | null;
}

export interface SpatialLocationEstimate {
  location_id?: number | null;
  label?: string | null;
  floor?: number | null;
  zone_name?: string | null;
  is_restricted?: boolean;
  x?: number | null;
  y?: number | null;
  z?: number | null;
  confidence: number;
  method: string;
  supporting_sensors: string[];
  calculated_at?: string | null;
}

export interface FloorMapGeometry {
  floor: number;
  units: "meters";
  width: number;
  height: number;
  separation_meters: number;
  rooms: Array<{ id: string; x: number; y: number; width: number; height: number; label?: string }>;
  stairs: { id: string; x: number; y: number; width: number; height: number; label?: string } | null;
  tables: Array<{
    id: string;
    aisle: number;
    table: number;
    x: number;
    y: number;
    width: number;
    height: number;
    orientation: string;
  }>;
}

export interface FloorReference {
  floor: number;
  client_id: string;
  hostname?: string | null;
  location_id?: number | null;
  label?: string | null;
  x: number;
  y: number;
  confidence: number | null;
  verified: boolean;
}

export interface FloorDevice {
  floor: number;
  device_id: number;
  mac_address?: string | null;
  ip_address?: string | null;
  hostname?: string | null;
  vendor?: string | null;
  x: number;
  y: number;
  confidence: number;
  method: string;
  rogue_score: number;
  is_rogue: boolean;
  risk_level: string;
  last_seen?: string | null;
  last_dhcp_observed_at?: string | null;
  activity_source?: "network_scan" | "dhcp";
  estimate_z?: number | null;
  elevation_delta_meters?: number | null;
}

export interface FloorSpatialMapResponse {
  floor: number;
  geometry: FloorMapGeometry;
  references: FloorReference[];
  devices: FloorDevice[];
  meta: {
    reference_count: number;
    device_count: number;
    positioning: string;
    active_filter: boolean;
    active_window_seconds: number;
    active_cutoff: string;
    dhcp_activity_retains_existing_position: boolean;
    dhcp_retention_grace_seconds: number;
    elevation_gate: {
      floor_elevation_meters: number;
      tolerance_meters: number;
    };
  };
}

export type Floor1MapGeometry = FloorMapGeometry;
export type Floor1Reference = FloorReference;
export type Floor1Device = FloorDevice;
export type Floor1SpatialMapResponse = FloorSpatialMapResponse;

export interface RogueDeviceSummary {
  device_id: number;
  mac_address: string;
  ip_address?: string | null;
  hostname?: string | null;
  vendor?: string | null;
  first_seen?: string | null;
  last_seen?: string | null;
  rogue_score: number;
  is_rogue: boolean;
  classification: string;
  risk_level: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  reasons: string[];
  location?: SpatialLocationEstimate | null;
}

export interface SpatialLocationEvent {
  id: number;
  device_id: number;
  mac_address?: string;
  hostname?: string | null;
  ip_address?: string | null;
  vendor?: string | null;
  previous_location?: {
    id?: number | null;
    label?: string | null;
    floor?: number | null;
    x?: number | null;
    y?: number | null;
    z?: number | null;
  } | null;
  new_location?: {
    id?: number | null;
    label?: string | null;
    floor?: number | null;
    x?: number | null;
    y?: number | null;
    z?: number | null;
  } | null;
  confidence: number;
  method: string;
  reason?: string | null;
  timestamp: string;
}

export interface SpatialScenePosition {
  x: number;
  y: number;
  z: number;
}

export interface SpatialSceneBounds {
  width: number;
  length: number;
  height: number;
}

export interface SpatialSceneLocation {
  id: number;
  name: string;
  label: string;
  type: string;
  floor: number;
  parent_id?: number | null;
  position: SpatialScenePosition;
  bounds: SpatialSceneBounds;
  is_restricted: boolean;
  zone_type: string;
  aisle?: string | null;
  table_no?: string | null;
  position_no?: string | null;
}

export interface SpatialSceneNode {
  id: string;
  name: string;
  label: string;
  type: 'workstation' | 'server' | 'switch' | 'gateway' | 'sensor' | 'printer' | 'rogue' | 'unknown';
  position: SpatialScenePosition;
  status: 'online' | 'offline' | 'suspicious' | 'rogue' | 'isolated';
  risk: 'low' | 'medium' | 'high' | 'critical';
  confidence: number;
  ip?: string | null;
  mac?: string | null;
  vendor?: string | null;
  location_label?: string | null;
  is_sensor: boolean;
  is_rogue: boolean;
  quarantined: boolean;
  metadata?: Record<string, any> & { floor?: number };
}

export interface SpatialSceneEdge {
  id: string;
  source: string;
  target: string;
  type: 'physical' | 'logical' | 'wireless' | 'threat';
  status: 'active' | 'inactive' | 'isolated';
  traffic_rate?: string;
  latency?: number;
  risk?: 'low' | 'medium' | 'high' | 'critical';
}

export interface SpatialThreatMarker {
  id: string;
  device_id: number;
  node_id: string;
  name: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  score: number;
  position: SpatialScenePosition;
  confidence: number;
  reasons: string[];
  detected_at: string;
  is_restricted_zone?: boolean;
}

export interface SpatialSceneMeta {
  version: number;
  floors: number[];
  total_locations: number;
  total_nodes: number;
  total_edges: number;
  total_threats: number;
  active_filter?: {
    enabled: boolean;
    max_age_seconds: number;
    cutoff: string | null;
    total_before_filter: number;
    total_after_filter: number;
  };
  bounds: {
    min_x: number;
    max_x: number;
    min_y: number;
    max_y: number;
    min_z: number;
    max_z: number;
  };
}

export interface SpatialSceneResponse {
  version: number;
  timestamp: string;
  locations: SpatialSceneLocation[];
  nodes: SpatialSceneNode[];
  edges: SpatialSceneEdge[];
  threats: SpatialThreatMarker[];
  meta: SpatialSceneMeta;
}

export interface SpatialTopologyResponse {
  nodes: SpatialSceneNode[];
  edges: SpatialSceneEdge[];
  summary: {
    total_nodes: number;
    total_edges: number;
    physical_links: number;
    wireless_links: number;
    threat_links: number;
  };
}

export interface SpatialReplayTriggerEvent {
  device_id: number;
  hostname?: string | null;
  mac_address?: string | null;
  reason?: string | null;
  from_location?: string | null;
  to_location?: string | null;
}

export interface SpatialReplayFrame {
  frame_index: number;
  timestamp: string;
  trigger_event: SpatialReplayTriggerEvent | null;
  active_nodes_count: number;
}

export interface SpatialReplayResponse {
  interval_seconds: number;
  total_frames: number;
  events: SpatialLocationEvent[];
  frames: SpatialReplayFrame[];
  base_scene: SpatialSceneResponse;
}

export interface ClientLocationHistoryEntry {
  id: number;
  assigned_at: string;
  unassigned_at: string | null;
  assigned_by: string | null;
  assignment?: LocationAssignment | null;
  location: ClientLocation;
}

export interface CalibrationComparison {
  client_id: string;
  hostname: string | null;
  history_id: number;
  location_id: number;
  location_label: string;
  assignment_method: string;
  assignment_status: string;
  verified: boolean;
  assigned_at: string;
  estimated: { x: number; y: number; z: number };
  actual: { x: number; y: number; z: number };
  error: { dx: number; dy: number; dz: number; distance: number };
}

export interface CalibrationReport {
  sample_count: number;
  comparisons: CalibrationComparison[];
  summary: {
    mean_error: { x: number; y: number; z: number };
    mean_distance: number;
    systematic_transformation_signal: boolean;
    interpretation: string;
  };
}

export type PhysicalNeighborRelationship =
  | 'same_row'
  | 'same_table'
  | 'neighboring_table'
  | 'same_zone';

export interface FloorColumn {
  column: number | null;
  row?: number | null;
  stations: ClientLocation[];
}

export interface FloorTable {
  table: number | null;
  kind?: "table" | "stairs";
  label?: string;
  location?: ClientLocation;
  columns: FloorColumn[];
  rows?: FloorColumn[];
}

export interface FloorAisle {
  aisle: number | null;
  tables: FloorTable[];
}

export interface FloorLayout {
  floor: number;
  available_floors: number[];
  rooms: ClientLocation[];
  aisles: FloorAisle[];
  shows_clients: boolean;
}

export interface PhysicalNeighbor {
  client_id: string;
  hostname: string;
  ip_address: string | null;
  mac_address: string | null;
  state: 'ONLINE' | 'OFFLINE' | 'ISOLATED';
  relationship: PhysicalNeighborRelationship;
  distance: number;
  location: ClientLocation;
}

export interface ManagedClientSummary {
  id: string;
  database_id: number;
  hostname: string;
  ip_address: string | null;
  mac_address: string;
  os: ClientOS;
  client_version?: string | null;
  client_version_updated_at?: string | null;
  connection: ClientConnection;
  location: ClientLocation | null;
  location_assignment?: LocationAssignment | null;
  health?: ClientHealth;
  created_at: string;
  updated_at: string;
}

export interface UnassignedClientQueueItem extends ManagedClientSummary {
  unassigned_reason: string;
  localization_confidence?: number | null;
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
  sni_domains: string[];
  dns_queries: string[];
  ja3_hashes: string[];
  destination_asns: Array<{ provider: string; description: string; destination_ip?: string; count: number }>;
  traffic_profile?: {
    behavioral_pattern?: string | null;
    bytes_per_window?: number | null;
    packets_per_window?: number | null;
    avg_interval_sec?: number | null;
    [key: string]: unknown;
  };
}

/** Lightweight row returned by GET /api/v1/network/devices (list all) */
export interface NetworkDeviceSummary {
  mac_address: string;
  ip_address: string | null;
  hostname: string | null;
  vendor: string | null;
  is_managed: boolean;
  managed_client_id: string | null;
  first_seen: string | null;
  last_seen: string | null;
  is_active?: boolean;
}

export interface NetworkDeviceListResponse {
  devices: NetworkDeviceSummary[];
  total: number;
  limit: number;
  offset: number;
  active_window_seconds?: number;
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

export interface GlobalNeighbourhoodCollection {
  id: string;
  status: 'started' | 'already_running' | 'pending' | 'running' | 'completed' | 'partial';
  clients_requested: number;
  clients_succeeded: number;
  clients_failed: number;
  clients_timed_out: number;
  devices_discovered: number;
  buckets_completed: number;
  buckets_total: number;
  current_bucket: number | null;
  request_timeout: number;
  finished_at: string | null;
  merge_error: string | null;
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

export interface ClientScreenshot {
  id: number;
  client_id: string;
  command_id: string | null;
  requested_by: string | null;
  filename: string;
  mime_type: string;
  file_size: number;
  device_name: string | null;
  captured_at: string | null;
  uploaded_at: string | null;
  status: "REQUESTED" | "CAPTURED" | "UPLOADED" | "FAILED";
}

export interface ClientScreenshotCaptureResult {
  status: "completed" | "client_timeout" | "client_unavailable" | "client_error" | "storage_error";
  client_id: string;
  timeout_seconds?: number;
  filename?: string;
  storage_path?: string;
  mime_type?: string;
  file_size?: number;
  device_name?: string;
  captured_at?: string;
  command_id?: string;
  message?: string;
}

// ── Dashboard ─────────────────────────────────────────────────────

export interface DashboardData {
  generated_at: string;
  clients: { online: number; isolated?: number; offline: number; total: number; unassigned?: number };
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
    location?: string;
    limit?: number;
    cursor?: string;
  }) =>
    get<{ items: ManagedClientSummary[]; next_cursor: string | null }>(
      "/clients",
      {
        state: params?.state ?? "",
        search: params?.search ?? "",
        location: params?.location ?? "",
        limit: String(params?.limit ?? 50),
        cursor: params?.cursor ?? "",
      },
    ),

  getUnassignedClients: (limit = 100) =>
    getAction<{ items: UnassignedClientQueueItem[]; total: number }>(
      `/api/clients/unassigned?limit=${limit}`,
    ),

  getClientLocalizationDebug: (clientId: string) =>
    get<ClientLocalizationDebug>(`/debug/clients/${encodeURIComponent(clientId)}/localization`),

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

  getLocations: (params?: { assignable?: boolean }) =>
    getAction<{ items: ClientLocation[] }>(
      params?.assignable ? "/api/locations?assignable=1" : "/api/locations",
    ),

  getLocationLayout: (floor: number) =>
    getAction<FloorLayout>(`/api/locations/layout?floor=${floor}`),

  getCalibrationReport: () =>
    getAction<CalibrationReport>("/api/locations/calibration"),

  createLocation: (payload: Omit<ClientLocation, "id" | "client_id">) =>
    postAction<ClientLocation>("/api/locations", payload),

  assignClientLocation: (clientId: string, locationId: number) =>
    (async () => {
      const response = await fetch(
        `${API_ORIGIN.replace(/\/+$/, "")}/api/clients/${encodeURIComponent(clientId)}/location`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify({ location_id: locationId }),
        },
      );
      const body = await response.json().catch(() => null);
      if (!response.ok) {
        throw new ApiError(
          body?.error?.code ?? "UNKNOWN_ERROR",
          body?.error?.message ?? `HTTP ${response.status}`,
          response.status,
        );
      }
      return body?.data as ClientLocation;
    })(),

  autoAssignClientLocation: (clientId: string) =>
    postAction<Record<string, unknown>>(
      `/api/clients/${encodeURIComponent(clientId)}/location/auto`,
      {},
    ),

  confirmClientLocation: (clientId: string) =>
    postAction<{ location: ClientLocation }>(
      `/api/clients/${encodeURIComponent(clientId)}/location/confirm`,
      {},
    ),

  getClientLocationHistory: (clientId: string) =>
    getAction<{ items: ClientLocationHistoryEntry[] }>(
      `/api/clients/${encodeURIComponent(clientId)}/location-history`,
    ),

  getPhysicalNeighbors: (clientId: string) =>
    getAction<{ items: PhysicalNeighbor[] }>(
      `/api/clients/${encodeURIComponent(clientId)}/physical-neighbors`,
    ),

  getClientScreenshots: (clientId: string, params?: { limit?: number }) =>
    get<{ items: ClientScreenshot[]; next_cursor: string | null }>(
      `/clients/${encodeURIComponent(clientId)}/screenshots`,
      {
        limit: String(params?.limit ?? 12),
      },
    ),

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

  updateAlertStatus: (
    alertId: number,
    status: "ACKNOWLEDGED" | "RESOLVED",
  ) =>
    patch<{
      alert: Alert;
      client: ManagedClientSummary | null;
      activity_log: ActivityLogRecord | null;
    }>(`/alerts/${alertId}`, { status }),

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

  createForbiddenProcess: (payload: {
    process_name: string;
    severity: string;
    enabled: boolean;
    description: string | null;
  }) => post<ForbiddenProcessRule>("/settings/forbidden-processes", payload),

  updateForbiddenProcess: (processName: string, payload: Omit<ForbiddenProcessRule, "process_name">) =>
    mutate<ForbiddenProcessRule>("PUT", `/settings/forbidden-processes/${encodeURIComponent(processName)}`, payload),

  deleteForbiddenProcess: (processName: string) =>
    mutate<{ deleted: boolean }>("DELETE", `/settings/forbidden-processes/${encodeURIComponent(processName)}`),

  // Client commands
  listClientCommands: (clientId: string) =>
    get<{ items: { command: string; label: string }[] }>(
      `/clients/${encodeURIComponent(clientId)}/commands`,
    ),

  runClientCommand: (clientId: string, command: string, args?: any) =>
    (async () => {
      const actionId = typeof crypto !== 'undefined' && crypto.randomUUID
        ? crypto.randomUUID()
        : `action-${Date.now()}`;
      const action = await api.createAction({
        action_id: actionId,
        action_type: command === 'REQUEST_SCREENSHOT' ? 'SCREENSHOT' : command,
        targets: [clientId],
        parameters: args ?? {},
      });
      return (action.result?.targets?.[0]?.result ?? action) as any;
    })(),

  createAction: (payload: {
    action_type: string;
    targets: string[];
    parameters?: any;
    action_id?: string;
  }) =>
    postAction<ActionDetail>('/api/actions', payload),

  getAction: (actionId: string) =>
    getAction<ActionDetail>(`/api/actions/${encodeURIComponent(actionId)}`),

  deployPackage: async (payload: {
    targets: string[];
    packageId: string;
    actionId?: string;
    timeoutSeconds?: number;
  }) => {
    const actionId =
      payload.actionId ??
      (typeof crypto !== "undefined" && crypto.randomUUID
        ? crypto.randomUUID()
        : `deploy-${Date.now()}`);
    const parameters: Record<string, unknown> = {
      package_id: payload.packageId,
    };
    if (payload.timeoutSeconds !== undefined) {
      parameters.timeout = payload.timeoutSeconds;
    }
    return api.createAction({
      action_id: actionId,
      action_type: "DEPLOY_PACKAGE",
      targets: payload.targets,
      parameters,
    });
  },

  updateClient: async (payload: {
    target: string;
    packageId: string;
    actionId?: string;
    timeoutSeconds?: number;
  }) => {
    const actionId =
      payload.actionId ??
      (typeof crypto !== "undefined" && crypto.randomUUID
        ? crypto.randomUUID()
        : `update-${Date.now()}`);
    const parameters: Record<string, unknown> = {
      package_id: payload.packageId,
    };
    if (payload.timeoutSeconds !== undefined) {
      parameters.timeout = payload.timeoutSeconds;
    }
    return api.createAction({
      action_id: actionId,
      action_type: "UPDATE_CLIENT",
      targets: [payload.target],
      parameters,
    });
  },

  createBulkUpdate: (payload: {
    packageId: string;
    targetSelection: {
      strategy: "individual" | "all";
      client_ids?: string[];
    };
    bulkUpdateId?: string;
  }) =>
    post<BulkUpdateCreateResponse>("/bulk-updates", {
      package_id: payload.packageId,
      target_selection: payload.targetSelection,
      bulk_update_id: payload.bulkUpdateId,
    }),

  getBulkUpdateStatus: (bulkUpdateId: string) =>
    get<BulkUpdateDetail>(`/bulk-updates/${encodeURIComponent(bulkUpdateId)}`),

  listBulkUpdates: (limit: number = 50) =>
    get<{ items: BulkUpdateSummary[] }>("/bulk-updates", { limit: String(limit) }),

  waitForBulkUpdate: async (
    bulkUpdateId: string,
    options?: {
      intervalMs?: number;
      timeoutMs?: number;
      onUpdate?: (status: BulkUpdateDetail) => void;
    },
  ) => {
    const intervalMs = options?.intervalMs ?? 1500;
    const timeoutMs = options?.timeoutMs ?? 10 * 60 * 1000;
    const started = Date.now();

    while (true) {
      const status = await api.getBulkUpdateStatus(bulkUpdateId);
      options?.onUpdate?.(status);

      const agg = status.aggregate_status;
      const isDone = agg.total > 0 && agg.completed + agg.failed >= agg.total;
      if (isDone) {
        return status;
      }

      if (Date.now() - started > timeoutMs) {
        throw new ApiError(
          "BULK_UPDATE_TIMEOUT",
          `Bulk update ${bulkUpdateId} timed out after ${Math.round(timeoutMs / 1000)}s`,
          408,
        );
      }

      await new Promise((resolve) => setTimeout(resolve, intervalMs));
    }
  },

  uploadPackage: async (
    file: File,
    options?: { packageId?: string },
  ): Promise<PackageUpload> => {
    const fullUrl = `${API_ORIGIN.replace(/\/+$/, "")}/api/packages`;
    const headers: Record<string, string> = {
      Accept: "application/json",
      "Content-Type": "application/zip",
      "X-Package-Filename": file.name,
    };
    if (options?.packageId) {
      headers["X-Package-Id"] = options.packageId;
    }
    const response = await fetch(fullUrl, {
      method: "POST",
      headers,
      body: file,
    });
    const body = await response.json().catch(() => null);
    if (!response.ok) {
      throw new ApiError(
        body?.error?.code ?? "UNKNOWN_ERROR",
        body?.error?.message ?? `HTTP ${response.status}`,
        response.status,
      );
    }
    return body?.data as PackageUpload;
  },

  waitForAction: async (
    actionId: string,
    options?: {
      intervalMs?: number;
      timeoutMs?: number;
      onUpdate?: (action: ActionDetail) => void;
    },
  ) => {
    const intervalMs = options?.intervalMs ?? 1500;
    const timeoutMs = options?.timeoutMs ?? 10 * 60 * 1000;
    const terminal = new Set([
      "SUCCESS",
      "FAILED",
      "PARTIAL_SUCCESS",
      "CANCELLED",
      "EXPIRED",
    ]);
    const started = Date.now();

    while (true) {
      const action = await api.getAction(actionId);
      options?.onUpdate?.(action);
      if (terminal.has(action.status)) {
        return action;
      }
      if (Date.now() - started > timeoutMs) {
        throw new ApiError(
          "ACTION_TIMEOUT",
          `Action ${actionId} did not complete within ${Math.round(timeoutMs / 1000)}s`,
          408,
        );
      }
      await new Promise((resolve) => setTimeout(resolve, intervalMs));
    }
  },

  requestClientScreenshot: (clientId: string) =>
    (async () => {
      const baseWithApi = API_ORIGIN.replace(/\/+$/, "") + BASE;
      const resp = await fetch(
        baseWithApi + `/clients/${encodeURIComponent(clientId)}/screenshot`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
        },
      );
      const body = await resp.json().catch(() => null);
      if (!resp.ok) {
        throw new ApiError(
          body?.error?.code ?? "UNKNOWN_ERROR",
          body?.error?.message ?? `HTTP ${resp.status}`,
          resp.status,
        );
      }
      return body?.data as ClientScreenshotCaptureResult;
    })(),

  requestClientNeighbourhood: (clientId: string) =>
    (async () => {
      const baseWithApi = API_ORIGIN.replace(/\/+$/, "") + BASE;
      const resp = await fetch(
        baseWithApi + `/clients/${encodeURIComponent(clientId)}/network-neighbourhood`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
        },
      );
      if (!resp.ok) {
        const body = await resp.json().catch(() => null);
        throw new ApiError(
          body?.error?.code ?? "UNKNOWN_ERROR",
          body?.error?.message ?? `HTTP ${resp.status}`,
          resp.status,
        );
      }
      return (await resp.json()).data as {
        status: "completed";
        client_id: string;
        observations_sent: number;
        timeout_seconds: number;
      };
    })(),

  requestClientPassiveNeighbourhood: (clientId: string) =>
    (async () => {
      const baseWithApi = API_ORIGIN.replace(/\/+$/, "") + BASE;
      const resp = await fetch(
        baseWithApi + `/clients/${encodeURIComponent(clientId)}/passive-neighbourhood`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
        },
      );
      if (!resp.ok) {
        const body = await resp.json().catch(() => null);
        throw new ApiError(
          body?.error?.code ?? "UNKNOWN_ERROR",
          body?.error?.message ?? `HTTP ${resp.status}`,
          resp.status,
        );
      }
      return (await resp.json()).data as ClientPassiveNeighbourhood;
    })(),

  getScreenshotFileUrl: (screenshotId: number) =>
    `${API_ORIGIN.replace(/\/+$/, "")}${BASE}/screenshots/${encodeURIComponent(String(screenshotId))}/file`,

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

  startGlobalNeighbourhoodCollection: () =>
    (async () => {
      const baseWithApi = API_ORIGIN.replace(/\/+$/, "") + BASE;
      const resp = await fetch(baseWithApi + "/network/neighbourhood/collections", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => null);
        throw new ApiError(
          body?.error?.code ?? "UNKNOWN_ERROR",
          body?.error?.message ?? `HTTP ${resp.status}`,
          resp.status,
        );
      }
      return (await resp.json()).data as GlobalNeighbourhoodCollection;
    })(),

  flushNeighbourhoodStorage: () =>
    (async () => {
      const baseWithApi = API_ORIGIN.replace(/\/+$/, "") + BASE;
      const resp = await fetch(baseWithApi + "/network/neighbourhood/flush", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => null);
        throw new ApiError(
          body?.error?.code ?? "UNKNOWN_ERROR",
          body?.error?.message ?? `HTTP ${resp.status}`,
          resp.status,
        );
      }
      return (await resp.json()).data as {
        status: string;
        clients_requested: number;
        clients_succeeded: number;
        clients_failed: number;
        server_scan_files_deleted: number;
        client_results: Array<{
          client_id: string;
          hostname?: string;
          status: string;
          deleted_count?: number;
          message?: string;
        }>;
      };
    })(),

  getGlobalNeighbourhoodCollection: (collectionId: string) =>
    get<GlobalNeighbourhoodCollection>(
      `/network/neighbourhood/collections/${encodeURIComponent(collectionId)}`,
    ),

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

  listNetworkDevices: (params?: { search?: string; limit?: number; offset?: number }) =>
    get<NetworkDeviceListResponse>("/network/devices", {
      ...(params?.search ? { search: params.search } : {}),
      ...(params?.limit != null ? { limit: String(params.limit) } : {}),
      ...(params?.offset != null ? { offset: String(params.offset) } : {}),
    }),

  quarantineClient: (clientId: string, payload?: { reason?: string; duration_minutes?: number }) =>
    post<any>(`/clients/${encodeURIComponent(clientId)}/quarantine`, payload ?? {}),

  releaseClientQuarantine: (clientId: string, payload?: { reason?: string }) =>
    post<any>(`/clients/${encodeURIComponent(clientId)}/release-quarantine`, payload ?? {}),

  getClientQuarantineStatus: (clientId: string) =>
    get<any>(`/clients/${encodeURIComponent(clientId)}/quarantine`),

  isolateClient: (clientId: string, payload?: { reason?: string }) =>
    post<any>(`/clients/${encodeURIComponent(clientId)}/isolation`, payload ?? {}),

  getClientIsolationStatus: (clientId: string) =>
    get<any>(`/clients/${encodeURIComponent(clientId)}/isolation`),

  // ── Spatial & Rogue Device Triangulation ────────────────────────
  listSensors: () =>
    get<{ items: SpatialSensor[] }>("/sensors"),

  createSensor: (payload: Partial<SpatialSensor>) =>
    post<SpatialSensor>("/sensors", payload),

  listRogueDevices: (params?: { min_score?: number; active_only?: boolean; max_age_seconds?: number }) =>
    get<{ items: RogueDeviceSummary[]; total: number }>("/rogue-devices", {
      ...(params?.min_score != null ? { min_score: String(params.min_score) } : {}),
      ...(params?.active_only ? { active_only: "true" } : {}),
      ...(params?.max_age_seconds != null ? { max_age_seconds: String(params.max_age_seconds) } : {}),
    }),

  getRogueDeviceDetail: (deviceId: string | number) =>
    get<RogueDeviceSummary & { movement_history: SpatialLocationEvent[] }>(
      `/rogue-devices/${encodeURIComponent(String(deviceId))}`,
    ),

  getDeviceSpatialLocation: (deviceId: string | number) =>
    get<any>(`/devices/${encodeURIComponent(String(deviceId))}/location`),

  getDeviceSpatialHistory: (deviceId: string | number, limit?: number) =>
    get<{ items: SpatialLocationEvent[] }>(
      `/devices/${encodeURIComponent(String(deviceId))}/location-history`,
      limit ? { limit: String(limit) } : undefined,
    ),

  listSpatialEvents: (limit?: number) =>
    get<{ items: SpatialLocationEvent[] }>(
      "/spatial/events",
      limit ? { limit: String(limit) } : undefined,
    ),

  triggerSpatialEvaluation: () =>
    post<{ status: string; evaluated_devices: number; items: any[] }>("/spatial/evaluate"),

  // ── Multi-Floor Spatial Visualization ──────────────────────────
  getFloorSpatialMap: (floor: number = 1) =>
    get<FloorSpatialMapResponse>(`/spatial/floor/${floor}`),

  getFloor1SpatialMap: () =>
    get<FloorSpatialMapResponse>("/spatial/floor/1"),

  // ── Legacy 3D-compatible scene / AR data ─────────────────────────
  getSpatialScene: (params?: { floor?: number; active_only?: boolean; max_age_seconds?: number }) =>
    get<SpatialSceneResponse>("/spatial/scene", {
      ...(params?.floor != null ? { floor: String(params.floor) } : {}),
      ...(params?.active_only === false ? { active_only: "false" } : {}),
      ...(params?.max_age_seconds != null ? { max_age_seconds: String(params.max_age_seconds) } : {}),
    }),

  getSpatialTopology: () =>
    get<SpatialTopologyResponse>("/spatial/topology"),

  getSpatialThreats: () =>
    get<{ items: SpatialThreatMarker[] }>("/spatial/threats"),

  getSpatialReplay: (params?: { from?: string; to?: string; interval?: number }) =>
    get<SpatialReplayResponse>("/spatial/replay", {
      ...(params?.from ? { from: params.from } : {}),
      ...(params?.to ? { to: params.to } : {}),
      ...(params?.interval ? { interval: String(params.interval) } : {}),
    }),

  // ── Device Intelligence & Classification ────────────────────────
  getDeviceClassification: (deviceId: string | number) =>
    get<DeviceClassification>(`/devices/${encodeURIComponent(String(deviceId))}/classification`),

  classifyDevice: (deviceId: string | number) =>
    post<DeviceClassification>(`/devices/${encodeURIComponent(String(deviceId))}/classify`),

  setDeviceHumanLabel: (deviceId: string | number, label: string, notes?: string, confirmedBy?: string) =>
    post<DeviceClassification>(`/devices/${encodeURIComponent(String(deviceId))}/label`, {
      label,
      notes,
      confirmed_by: confirmedBy,
    }),

  getClassificationReviewQueue: (limit?: number) =>
    get<{ items: any[]; total: number }>("/classification/review", limit ? { limit: String(limit) } : undefined),

  getClassificationStats: () =>
    get<ClassificationStats>("/classification/stats"),

  retrainClassificationModel: () =>
    post<any>("/classification/retrain"),
};

export interface DeviceClassification {
  device_id: number;
  predicted_class: string;
  confidence: number;
  source: 'ML' | 'RULE' | 'HUMAN' | 'HYBRID';
  model_version: string;
  status: 'ACTIVE' | 'NEEDS_REVIEW';
  probabilities?: Record<string, number>;
  evidence?: string[];
  rule_prediction?: string;
  ml_prediction?: string;
  classified_at?: string;
  updated_at?: string;
}

export interface ClassificationStats {
  total_devices: number;
  total_classified: number;
  class_distribution: Record<string, number>;
  high_confidence_count: number;
  medium_confidence_count: number;
  low_confidence_count: number;
  needs_review_count: number;
  average_confidence: number;
  human_labels_count: number;
  model_version: string;
}

export const apiClient = api;


