import { lazy, Suspense, useMemo, useState } from "react";
import { api, type FloorSpatialMapResponse } from "../api/client";
import { SectionCard } from "../components/Card";
import { ThreeSpatialScene } from "../components/spatial/ThreeSpatialScene";
import { FloorSelector } from "../components/spatial/FloorSelector";
import { FLOOR_CONFIG, type FloorId } from "../components/spatial/floorConfig";
import { EmptyState, ErrorState, Skeleton } from "../components/States";
import { useFetch } from "../hooks/useFetch";
import "../styles/floor1-map.css";

// Lazy-load DigitalTwin to avoid bundling it unless the operator toggles to it
const DigitalTwinPage = lazy(() =>
  import("./DigitalTwin").then((m) => ({ default: m.DigitalTwinPage }))
);

function confidenceLabel(value: number | null): string {
  return value == null ? "Unverified" : `${Math.round(value * 100)}% confidence`;
}

function activityLabel(source?: "network_scan" | "dhcp"): string {
  return source === "dhcp" ? "DHCP retained" : "Recent network scan";
}

export function SpatialPage() {
  const [selectedFloor, setSelectedFloor] = useState<FloorId>(1);
  const [selectedDeviceId, setSelectedDeviceId] = useState<number | null>(null);
  const [viewMode, setViewMode] = useState<"floor-map" | "digital-twin">("floor-map");

  const { state, refetch } = useFetch<FloorSpatialMapResponse>(
    () => api.getFloorSpatialMap(selectedFloor),
    [selectedFloor],
    ["app:client_status", "app:client_location_updated", "app:network_update"],
  );

  const map = state.status === "success" ? state.data : state.status === "error" ? state.staleData || null : null;
  const currentFloorConfig = FLOOR_CONFIG[selectedFloor] || FLOOR_CONFIG[1];
  const deviceCount = map?.devices.length || 0;
  const referenceCount = map?.references?.length || 0;
  const geometry = map?.geometry;

  const selectedDevice = useMemo(
    () => map?.devices.find((device) => device.device_id === selectedDeviceId) || null,
    [map, selectedDeviceId],
  );

  // When Digital Twin view is active, render it directly. Keep all hooks above
  // this branch so switching view modes never changes the hook call order.
  if (viewMode === "digital-twin") {
    return (
      <div className="page-shell floor1-map-page">
        <div className="spatial-page-header floor1-map-page__header">
          <div className="spatial-page-header__copy">
            <span className="eyebrow eyebrow--accent">SPATIAL / DIGITAL TWIN</span>
            <h1 className="heading-hero">Digital Twin Console</h1>
          </div>
          <div className="floor1-map__header-actions">
            <button
              className="floor1-map__refresh"
              type="button"
              onClick={() => setViewMode("floor-map")}
              title="Switch to WebGL Floor Map"
            >
              ← Floor Map
            </button>
          </div>
        </div>
        <Suspense fallback={<Skeleton variant="row" height="32rem" />}>
          <DigitalTwinPage />
        </Suspense>
      </div>
    );
  }

  const handleFloorChange = (newFloor: FloorId) => {
    if (newFloor === selectedFloor) return;
    setSelectedFloor(newFloor);
    // If a device is selected, clear selection if switching to another floor
    if (selectedDeviceId !== null) {
      setSelectedDeviceId(null);
    }
  };

  const selectDevice = (deviceId: number) => {
    setSelectedDeviceId((current) => (deviceId < 0 ? null : current === deviceId ? null : deviceId));
  };

  if (state.status === "loading" && !map) {
    return (
      <div className="page-shell floor1-map-page">
        <div className="spatial-page-header">
          <div className="spatial-page-header__copy">
            <span className="eyebrow">SPATIAL / {currentFloorConfig.name.toUpperCase()}</span>
            <h1 className="heading-hero">{currentFloorConfig.name} device map</h1>
          </div>
        </div>
        <Skeleton variant="row" height="32rem" />
      </div>
    );
  }

  if (!map || !geometry) {
    return (
      <div className="page-shell floor1-map-page">
        <header className="spatial-page-header floor1-map-page__header">
          <div className="spatial-page-header__copy">
            <span className="eyebrow eyebrow--accent">SPATIAL / {currentFloorConfig.name.toUpperCase()}</span>
            <h1 className="heading-hero">{currentFloorConfig.name} device map</h1>
          </div>
          <div className="floor1-map__header-actions">
            <FloorSelector selectedFloor={selectedFloor} onSelectFloor={handleFloorChange} />
          </div>
        </header>
        <ErrorState
          title={`${currentFloorConfig.name} map unavailable`}
          message={state.status === "error" ? state.error.message : `No ${currentFloorConfig.name} spatial data is available yet.`}
          onRetry={refetch}
        />
      </div>
    );
  }

  return (
    <div className="page-shell floor1-map-page">
      <header className="spatial-page-header floor1-map-page__header">
        <div className="spatial-page-header__copy">
          <span className="eyebrow eyebrow--accent">SPATIAL / {currentFloorConfig.name.toUpperCase()} / WEBGL</span>
          <h1 className="heading-hero">{currentFloorConfig.name} spatial map</h1>
          <p className="text-muted">{currentFloorConfig.description}</p>
        </div>
        <div className="floor1-map__header-actions">
          <FloorSelector selectedFloor={selectedFloor} onSelectFloor={handleFloorChange} />
          <button
            className="floor1-map__refresh"
            type="button"
            onClick={() => setViewMode("digital-twin")}
            title="Switch to Digital Twin & Replay Console"
          >
            Digital Twin →
          </button>
          <button className="floor1-map__refresh" type="button" onClick={() => refetch()}>
            Refresh map
          </button>
        </div>
      </header>

      <div className="floor1-map__metrics" aria-label="Floor map summary">
        <div>
          <strong>{currentFloorConfig.hasReferenceClients ? referenceCount : 0}</strong>
          <span>{currentFloorConfig.hasReferenceClients ? "Reference PCs" : "Reference PCs (N/A)"}</span>
        </div>
        <div>
          <strong>{deviceCount}</strong>
          <span>Active devices</span>
        </div>
        <div>
          <strong>{geometry.separation_meters}m</strong>
          <span>Center gap</span>
        </div>
        <div>
          <strong>±{map.meta.elevation_gate.tolerance_meters}m</strong>
          <span>Floor {selectedFloor} z gate</span>
        </div>
      </div>

      {currentFloorConfig.hasReferenceClients && referenceCount === 0 && (
        <div className="floor1-map__notice">
          <EmptyState
            icon="◎"
            title="No Floor 1 reference PCs"
            body="Assign known clients to Floor 1 PC positions to establish the spatial reference frame."
          />
        </div>
      )}

      <div className="floor1-map__workspace">
        <SectionCard floor={true} title={`Active devices (${deviceCount})`} className="floor1-map__card floor1-map__device-panel">
          <div className="floor1-map__panel-hint">
            {selectedFloor === 1
              ? `Floor 1 only: estimated z must be within ±${map.meta.elevation_gate.tolerance_meters}m of the ${map.meta.elevation_gate.floor_elevation_meters}m floor elevation. DHCP retains qualifying positions.`
              : `${currentFloorConfig.name}: displaying devices qualified for this floor (${currentFloorConfig.elevationMeters}m level).`}
          </div>
          {map.devices.length === 0 ? (
            <EmptyState
              icon="⌖"
              title={`No active devices on ${currentFloorConfig.name}`}
              body="Active devices detected or positioned on this floor will appear here."
            />
          ) : (
            <div className="floor1-map__device-list">
              {map.devices.map((device) => {
                const selected = device.device_id === selectedDeviceId;
                return (
                  <button
                    className={`floor1-map__device-row${selected ? " floor1-map__device-row--selected" : ""}${
                      device.activity_source === "dhcp" ? " floor1-map__device-row--dhcp" : ""
                    }`}
                    type="button"
                    key={device.device_id}
                    onClick={() => selectDevice(device.device_id)}
                    aria-pressed={selected}
                  >
                    <span className="floor1-map__device-row-main">
                      <strong>{device.hostname || device.mac_address || `Device ${device.device_id}`}</strong>
                      <span>{device.mac_address || device.ip_address || "No address"}</span>
                      <em>{activityLabel(device.activity_source)}</em>
                    </span>
                    <span className="floor1-map__device-coordinates">
                      <strong>
                        ({device.x.toFixed(2)}, {device.y.toFixed(2)})m
                      </strong>
                      <span>{confidenceLabel(device.confidence)}</span>
                      <span>z Δ {device.elevation_delta_meters?.toFixed(2) ?? "—"}m</span>
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </SectionCard>

        <SectionCard title={`${currentFloorConfig.name} layout`} className="floor1-map__card floor1-map__map-panel">
          <div className="floor1-map__scene-toolbar">
            <div className="floor1-map__legend">
              {currentFloorConfig.hasReferenceClients && (
                <span>
                  <i className="floor1-map__legend-dot floor1-map__legend-dot--reference" /> Reference PC
                </span>
              )}
              <span>
                <i className="floor1-map__legend-dot floor1-map__legend-dot--device" /> Recent scan
              </span>
              <span>
                <i className="floor1-map__legend-dot floor1-map__legend-dot--dhcp" /> DHCP retained
              </span>
              <span>
                <i className="floor1-map__legend-dot floor1-map__legend-dot--rogue" /> Rogue
              </span>
              {selectedDevice && (
                <button className="floor1-map__clear-focus" type="button" onClick={() => setSelectedDeviceId(null)}>
                  Clear focus ({selectedDevice.hostname || `Device ${selectedDevice.device_id}`})
                </button>
              )}
            </div>
          </div>
          <div className="floor1-map__interaction-hint">
            Drag to rotate · Scroll to zoom · Right-drag to pan · Click device to focus label
          </div>
          <div className="floor1-map__viewport">
            <ThreeSpatialScene
              map={map}
              selectedFloor={selectedFloor}
              selectedDeviceId={selectedDeviceId}
              onSelect={selectDevice}
            />
          </div>
        </SectionCard>
      </div>
    </div>
  );
}

// Backward compatible export for existing routes
export const Floor1MapPage = SpatialPage;
