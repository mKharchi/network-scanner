import { useEffect, useState } from "react";
import { api, RogueDeviceSummary, SpatialSensor, SpatialLocationEvent } from "../api/client";
import { Card, SectionCard } from "../components/Card";
import { Badge, BadgeVariant } from "../components/Badge";
import { Button } from "../components/Button";
import { useToast } from "../hooks/useToast";
import { formatDateTime } from "../utils/format";

export function RogueDevicesPage() {
  const { addToast } = useToast();
  const [activeTab, setActiveTab] = useState<"rogue" | "sensors" | "timeline">("rogue");
  const [loading, setLoading] = useState(true);
  const [evaluating, setEvaluating] = useState(false);
  const [rogueDevices, setRogueDevices] = useState<RogueDeviceSummary[]>([]);
  const [sensors, setSensors] = useState<SpatialSensor[]>([]);
  const [events, setEvents] = useState<SpatialLocationEvent[]>([]);
  const [selectedDevice, setSelectedDevice] = useState<RogueDeviceSummary | null>(null);

  const fetchData = async () => {
    try {
      setLoading(true);
      const [rogueRes, sensorRes, eventRes] = await Promise.all([
        api.listRogueDevices({ min_score: 20 }),
        api.listSensors(),
        api.listSpatialEvents(50),
      ]);
      setRogueDevices(rogueRes.items || []);
      setSensors(sensorRes.items || []);
      setEvents(eventRes.items || []);
    } catch (err: any) {
      addToast({
        title: "Failed to load spatial data",
        message: err?.message || "Could not retrieve spatial rogue device information.",
        severity: "CRITICAL",
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handleEvaluate = async () => {
    try {
      setEvaluating(true);
      const res = await api.triggerSpatialEvaluation();
      addToast({
        title: "Spatial evaluation completed",
        message: `Triangulated and evaluated ${res.evaluated_devices} network devices.`,
        severity: "SUCCESS",
      });
      await fetchData();
    } catch (err: any) {
      addToast({
        title: "Evaluation failed",
        message: err?.message || "Failed to trigger spatial calculation.",
        severity: "HIGH",
      });
    } finally {
      setEvaluating(false);
    }
  };

  const getRiskBadgeVariant = (risk: string): BadgeVariant => {
    switch (risk) {
      case "CRITICAL":
        return "critical";
      case "HIGH":
        return "critical";
      case "MEDIUM":
        return "warning";
      default:
        return "muted";
    }
  };

  const criticalCount = rogueDevices.filter((d) => d.risk_level === "CRITICAL" || d.risk_level === "HIGH").length;
  const activeSensorsCount = sensors.filter((s) => s.status === "ONLINE").length;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-6)" }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "var(--space-4)" }}>
        <div>
          <h1 className="page-title">
             Spatial-Temporal Rogue Device Triangulation
          </h1>
           <p
            style={{ color: "var(--text-muted)", marginTop: "var(--space-1)" }}
          > 
            Real-time multilateration, physical location estimation, and explainable threat scoring.
          </p>
        </div>
        <div style={{ display: "flex", gap: "var(--space-2)" }}>
          <Button size="sm" variant="secondary" onClick={fetchData} disabled={loading}>
            Refresh
          </Button>
          <Button size="sm" variant="primary" onClick={handleEvaluate} disabled={evaluating}>
            {evaluating ? "Triangulating…" : "⚡ Re-evaluate Spatial Grid"}
          </Button>
        </div>
      </div>

      {/* Summary Cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "var(--space-4)" }}>
        <Card>
          <div style={{ color: "var(--text-muted)", fontSize: "var(--font-sm)", fontWeight: 600 }}>
            ROGUE CANDIDATES
          </div>
          <div style={{ fontSize: "var(--font-3xl)", fontWeight: 700, color: rogueDevices.length > 0 ? "var(--color-warning-500, #f59e0b)" : "var(--text-primary)" }}>
            {rogueDevices.length}
          </div>
          <div style={{ fontSize: "var(--font-xs)", color: "var(--text-muted)" }}>
            Unmanaged / suspicious endpoints
          </div>
        </Card>

        <Card>
          <div style={{ color: "var(--text-muted)", fontSize: "var(--font-sm)", fontWeight: 600 }}>
            HIGH / CRITICAL THREATS
          </div>
          <div style={{ fontSize: "var(--font-3xl)", fontWeight: 700, color: criticalCount > 0 ? "var(--color-danger-500, #ef4444)" : "var(--color-success-500, #10b981)" }}>
            {criticalCount}
          </div>
          <div style={{ fontSize: "var(--font-xs)", color: "var(--text-muted)" }}>
            Restricted zone or randomized MAC
          </div>
        </Card>

        <Card>
          <div style={{ color: "var(--text-muted)", fontSize: "var(--font-sm)", fontWeight: 600 }}>
            GRID SENSORS
          </div>
          <div style={{ fontSize: "var(--font-3xl)", fontWeight: 700, color: "var(--color-primary-500, #3b82f6)" }}>
            {activeSensorsCount} / {sensors.length}
          </div>
          <div style={{ fontSize: "var(--font-xs)", color: "var(--text-muted)" }}>
            Endpoint & infrastructure probes
          </div>
        </Card>

        <Card>
          <div style={{ color: "var(--text-muted)", fontSize: "var(--font-sm)", fontWeight: 600 }}>
            LOCATION TRANSITIONS
          </div>
          <div style={{ fontSize: "var(--font-3xl)", fontWeight: 700, color: "var(--text-primary)" }}>
            {events.length}
          </div>
          <div style={{ fontSize: "var(--font-xs)", color: "var(--text-muted)" }}>
            Recorded spatial movement events
          </div>
        </Card>
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", gap: "var(--space-2)", borderBottom: "1px solid var(--border)" }}>
        <button
          type="button"
          onClick={() => setActiveTab("rogue")}
          style={{
            padding: "var(--space-2) var(--space-4)",
            background: "none",
            border: "none",
            borderBottom: activeTab === "rogue" ? "2px solid var(--color-primary-500, #3b82f6)" : "none",
            color: activeTab === "rogue" ? "var(--text-primary)" : "var(--text-muted)",
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          🚨 Rogue Candidates ({rogueDevices.length})
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("sensors")}
          style={{
            padding: "var(--space-2) var(--space-4)",
            background: "none",
            border: "none",
            borderBottom: activeTab === "sensors" ? "2px solid var(--color-primary-500, #3b82f6)" : "none",
            color: activeTab === "sensors" ? "var(--text-primary)" : "var(--text-muted)",
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          📡 Sensor Grid ({sensors.length})
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("timeline")}
          style={{
            padding: "var(--space-2) var(--space-4)",
            background: "none",
            border: "none",
            borderBottom: activeTab === "timeline" ? "2px solid var(--color-primary-500, #3b82f6)" : "none",
            color: activeTab === "timeline" ? "var(--text-primary)" : "var(--text-muted)",
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          🕒 Movement Timeline ({events.length})
        </button>
      </div>

      {/* Tab Content: Rogue Candidates */}
      {activeTab === "rogue" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
          {rogueDevices.length === 0 ? (
            <SectionCard title="No Rogue Devices Detected">
              <p style={{ color: "var(--text-muted)", margin: 0 }}>
                All observed devices on the network match authorized clients or registered inventory.
              </p>
            </SectionCard>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(360px, 1fr))", gap: "var(--space-4)" }}>
              {rogueDevices.map((dev) => (
                <Card key={dev.device_id}>
                  <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                      <div>
                        <div style={{ fontFamily: "var(--font-mono)", fontWeight: 700, fontSize: "var(--font-md)" }}>
                          {dev.mac_address}
                        </div>
                        <div style={{ fontSize: "var(--font-xs)", color: "var(--text-muted)" }}>
                          {dev.ip_address || "No IP assigned"} • {dev.vendor || "Unknown vendor"}
                        </div>
                      </div>
                      <Badge variant={getRiskBadgeVariant(dev.risk_level)}>
                        Score: {dev.rogue_score} ({dev.risk_level})
                      </Badge>
                    </div>

                    {/* Estimated Location */}
                    <div style={{ padding: "var(--space-3)", background: "var(--surface-muted)", borderRadius: "var(--radius)", display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
                      <div style={{ fontSize: "var(--font-xs)", color: "var(--text-muted)", fontWeight: 600, textTransform: "uppercase" }}>
                        Probable Physical Location
                      </div>
                      <div style={{ fontWeight: 600, fontSize: "var(--font-sm)", display: "flex", alignItems: "center", gap: "var(--space-1)" }}>
                        <span>📍</span>
                        {dev.location ? (
                          <span>
                            Floor {dev.location.floor ?? 1} → {dev.location.zone_name || dev.location.label || "General Area"}
                            {dev.location.is_restricted && (
                              <span style={{ color: "var(--color-danger-500, #ef4444)", marginLeft: "var(--space-1)" }}>
                                [RESTRICTED]
                              </span>
                            )}
                          </span>
                        ) : (
                          <span style={{ color: "var(--text-muted)" }}>Localization in progress</span>
                        )}
                      </div>
                      {dev.location && (
                        <div style={{ fontSize: "var(--font-xs)", color: "var(--text-muted)", display: "flex", justifyContent: "space-between", marginTop: "var(--space-1)" }}>
                          <span>Confidence: <strong>{Math.round(dev.location.confidence * 100)}%</strong></span>
                          <span>Method: {dev.location.method}</span>
                          {dev.location.x != null && dev.location.y != null && (
                            <span>({dev.location.x}m, {dev.location.y}m)</span>
                          )}
                        </div>
                      )}
                    </div>

                    {/* Explainable Threat Reasons */}
                    <div>
                      <div style={{ fontSize: "var(--font-xs)", color: "var(--text-muted)", fontWeight: 600, marginBottom: "var(--space-1)" }}>
                        EVIDENCE & THREAT FACTORS
                      </div>
                      <ul style={{ margin: 0, paddingLeft: "var(--space-4)", fontSize: "var(--font-xs)", color: "var(--text-secondary)", display: "flex", flexDirection: "column", gap: "2px" }}>
                        {dev.reasons.map((r, i) => (
                          <li key={i}>{r}</li>
                        ))}
                      </ul>
                    </div>

                    {/* Timing & Actions */}
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "auto", paddingTop: "var(--space-2)", borderTop: "1px solid var(--border)", fontSize: "var(--font-xs)", color: "var(--text-muted)" }}>
                      <span>Last seen: {formatDateTime(dev.last_seen)}</span>
                      <Button size="sm" variant="quiet" onClick={() => setSelectedDevice(dev)}>
                        Inspect
                      </Button>
                    </div>
                  </div>
                </Card>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Tab Content: Sensors Grid */}
      {activeTab === "sensors" && (
        <SectionCard title="Active Sensor Probes & Coordinate Anchors">
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "var(--font-sm)" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid var(--border)", textAlign: "left" }}>
                  <th style={{ padding: "var(--space-2)" }}>Sensor ID / Name</th>
                  <th style={{ padding: "var(--space-2)" }}>Type</th>
                  <th style={{ padding: "var(--space-2)" }}>Assigned Location</th>
                  <th style={{ padding: "var(--space-2)" }}>3D Coordinates (X, Y, Z)</th>
                  <th style={{ padding: "var(--space-2)" }}>Capabilities</th>
                  <th style={{ padding: "var(--space-2)" }}>Status</th>
                </tr>
              </thead>
              <tbody>
                {sensors.map((s) => (
                  <tr key={s.id} style={{ borderBottom: "1px solid var(--border)" }}>
                    <td style={{ padding: "var(--space-2)" }}>
                      <div style={{ fontWeight: 600 }}>{s.name}</div>
                      <div style={{ fontSize: "var(--font-xs)", color: "var(--text-muted)" }}>{s.sensor_id}</div>
                    </td>
                    <td style={{ padding: "var(--space-2)" }}>
                      <Badge variant="muted">{s.type}</Badge>
                    </td>
                    <td style={{ padding: "var(--space-2)" }}>
                      {s.location_label ? `Floor ${s.floor} → ${s.location_label}` : "—"}
                    </td>
                    <td style={{ padding: "var(--space-2)", fontFamily: "var(--font-mono)" }}>
                      {s.x != null && s.y != null ? `(${s.x}m, ${s.y}m, ${s.z ?? 0}m)` : "Uncalibrated"}
                    </td>
                    <td style={{ padding: "var(--space-2)" }}>
                      <div style={{ display: "flex", gap: "var(--space-1)", flexWrap: "wrap" }}>
                        {s.capabilities.map((c, i) => (
                          <Badge key={i} variant="info">{c}</Badge>
                        ))}
                      </div>
                    </td>
                    <td style={{ padding: "var(--space-2)" }}>
                      <Badge variant={s.status === "ONLINE" ? "success" : "muted"}>{s.status}</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </SectionCard>
      )}

      {/* Tab Content: Movement Timeline */}
      {activeTab === "timeline" && (
        <SectionCard title="Physical Transition & Localization Audit Trail">
          {events.length === 0 ? (
            <p style={{ color: "var(--text-muted)", margin: 0 }}>No movement events recorded yet.</p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
              {events.map((ev) => (
                <div
                  key={ev.id}
                  style={{
                    padding: "var(--space-3)",
                    background: "var(--surface-muted)",
                    borderRadius: "var(--radius)",
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    flexWrap: "wrap",
                    gap: "var(--space-2)",
                  }}
                >
                  <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
                    <div style={{ fontWeight: 600, fontSize: "var(--font-sm)" }}>
                      Device: <span style={{ fontFamily: "var(--font-mono)" }}>{ev.mac_address || `Device #${ev.device_id}`}</span>
                      {ev.hostname && <span style={{ color: "var(--text-muted)", marginLeft: "var(--space-1)" }}>({ev.hostname})</span>}
                    </div>
                    <div style={{ fontSize: "var(--font-xs)", color: "var(--text-secondary)" }}>
                      {ev.previous_location ? `Moved from ${ev.previous_location.label || `Floor ${ev.previous_location.floor}`}` : "Initial localization"}
                      {" ➔ "}
                      <strong>{ev.new_location ? `${ev.new_location.label || `Floor ${ev.new_location.floor}`}` : "Unknown location"}</strong>
                    </div>
                    <div style={{ fontSize: "var(--font-xs)", color: "var(--text-muted)" }}>
                      Reason: {ev.reason || "Periodic spatial check"} • Method: {ev.method} • Confidence: {Math.round(ev.confidence * 100)}%
                    </div>
                  </div>
                  <div style={{ fontSize: "var(--font-xs)", color: "var(--text-muted)" }}>
                    {formatDateTime(ev.timestamp)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </SectionCard>
      )}

      {/* Selected Device Modal / Drawer */}
      {selectedDevice && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            backgroundColor: "rgba(0, 0, 0, 0.5)",
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
            zIndex: 1000,
            padding: "var(--space-4)",
          }}
          onClick={() => setSelectedDevice(null)}
        >
          <div
            style={{
              background: "var(--surface)",
              borderRadius: "var(--radius-lg)",
              padding: "var(--space-6)",
              maxWidth: "600px",
              width: "100%",
              maxHeight: "90vh",
              overflowY: "auto",
              display: "flex",
              flexDirection: "column",
              gap: "var(--space-4)",
              boxShadow: "var(--shadow-xl)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <h2 style={{ margin: 0, fontSize: "var(--font-xl)" }}>Device Spatial Intelligence</h2>
              <Button size="sm" variant="quiet" onClick={() => setSelectedDevice(null)}>✕</Button>
            </div>

            <div>
              <div style={{ fontFamily: "var(--font-mono)", fontWeight: 700, fontSize: "var(--font-lg)" }}>
                {selectedDevice.mac_address}
              </div>
              <div style={{ color: "var(--text-muted)", fontSize: "var(--font-sm)" }}>
                IP: {selectedDevice.ip_address || "None"} • Vendor: {selectedDevice.vendor || "Unknown"}
              </div>
            </div>

            <div style={{ padding: "var(--space-4)", background: "var(--surface-muted)", borderRadius: "var(--radius)" }}>
              <div style={{ fontWeight: 600, fontSize: "var(--font-sm)", marginBottom: "var(--space-2)" }}>
                Triangulated 3D Position
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "var(--space-2)", fontSize: "var(--font-sm)" }}>
                <div><strong>X (Grid):</strong> {selectedDevice.location?.x ?? "—"} m</div>
                <div><strong>Y (Grid):</strong> {selectedDevice.location?.y ?? "—"} m</div>
                <div><strong>Z (Floor):</strong> {selectedDevice.location?.z ?? "—"} m</div>
              </div>
              <div style={{ marginTop: "var(--space-2)", fontSize: "var(--font-xs)", color: "var(--text-muted)" }}>
                Method: {selectedDevice.location?.method} • Confidence: {Math.round((selectedDevice.location?.confidence ?? 0) * 100)}%
              </div>
            </div>

            <div>
              <div style={{ fontWeight: 600, fontSize: "var(--font-sm)", marginBottom: "var(--space-1)" }}>
                Supporting Sensors Evidence
              </div>
              <div style={{ display: "flex", gap: "var(--space-1)", flexWrap: "wrap" }}>
                {(selectedDevice.location?.supporting_sensors || ["No direct sensors"]).map((s, i) => (
                  <Badge key={i} variant="info">{s}</Badge>
                ))}
              </div>
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: "var(--space-2)", marginTop: "var(--space-2)" }}>
              <Button variant="secondary" onClick={() => setSelectedDevice(null)}>Close</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
