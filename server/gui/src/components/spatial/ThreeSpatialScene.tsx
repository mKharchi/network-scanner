import { useMemo } from "react";
import { Canvas } from "@react-three/fiber";
import { Html, OrbitControls } from "@react-three/drei";
import type { FloorDevice, FloorReference, FloorSpatialMapResponse } from "../../api/client";
import { FLOOR_CONFIG, type FloorId } from "./floorConfig";

const TABLE_HEIGHT = 0.85;
const ROOM_HEIGHT = 0.25;
const MARKER_HEIGHT = 0.7;

function toScene(geometry: FloorSpatialMapResponse["geometry"], x: number, y: number): [number, number, number] {
  return [x - geometry.width / 2, 0, geometry.height / 2 - y];
}

function labelForDevice(device: FloorDevice): string {
  return device.hostname || device.mac_address || `Device ${device.device_id}`;
}

interface DeviceMarkerProps {
  device: FloorDevice;
  geometry: FloorSpatialMapResponse["geometry"];
  selected: boolean;
  showLabel: boolean;
  onSelect: (id: number) => void;
}

function DeviceMarker({
  device,
  geometry,
  selected,
  showLabel,
  onSelect,
}: DeviceMarkerProps) {
  const [px, , pz] = toScene(geometry, device.x, device.y);
  const color = device.is_rogue ? "#ef4444" : device.activity_source === "dhcp" ? "#a78bfa" : "#10b981";
  const markerSize = selected ? 0.43 : device.activity_source === "dhcp" ? 0.3 : 0.27;

  return (
    <group>
      {selected && (
        <mesh position={[px, MARKER_HEIGHT, pz]} rotation={[-Math.PI / 2, 0, 0]}>
          <ringGeometry args={[0.5, 0.65, 32]} />
          <meshBasicMaterial color="#f8fafc" transparent opacity={0.95} />
        </mesh>
      )}
      <mesh
        position={[px, MARKER_HEIGHT, pz]}
        onClick={(event) => {
          event.stopPropagation();
          onSelect(device.device_id);
        }}
        castShadow
      >
        <sphereGeometry args={[markerSize, 24, 24]} />
        <meshStandardMaterial
          color={color}
          emissive={color}
          emissiveIntensity={selected ? 1.0 : 0.55}
          roughness={0.22}
          metalness={0.15}
        />
      </mesh>

      {showLabel && (
        <Html position={[px, MARKER_HEIGHT + 0.65, pz]} center distanceFactor={14} style={{ pointerEvents: "none" }}>
          <div
            className={`floor1-map__gl-label${
              device.activity_source === "dhcp" ? " floor1-map__gl-label--dhcp" : ""
            }${selected ? " floor1-map__gl-label--selected" : ""}`}
          >
            {labelForDevice(device)}
          </div>
        </Html>
      )}
    </group>
  );
}

function ReferenceMarker({
  reference,
  geometry,
}: {
  reference: FloorReference;
  geometry: FloorSpatialMapResponse["geometry"];
}) {
  const [px, , pz] = toScene(geometry, reference.x, reference.y);
  return (
    <group>
      <mesh position={[px, MARKER_HEIGHT, pz]}>
        <sphereGeometry args={[0.3, 24, 24]} />
        <meshStandardMaterial color="#38bdf8" emissive="#38bdf8" emissiveIntensity={0.5} roughness={0.25} />
      </mesh>
      <Html position={[px, MARKER_HEIGHT + 0.5, pz]} center distanceFactor={14} style={{ pointerEvents: "none" }}>
        <div className="floor1-map__gl-label floor1-map__gl-label--reference">
          {reference.hostname || reference.client_id}
        </div>
      </Html>
    </group>
  );
}

export interface ThreeSpatialSceneProps {
  map: FloorSpatialMapResponse;
  selectedFloor?: FloorId;
  selectedDeviceId: number | null;
  onSelect: (id: number) => void;
}

export function ThreeSpatialScene({
  map,
  selectedFloor = 1,
  selectedDeviceId,
  onSelect,
}: ThreeSpatialSceneProps) {
  const { geometry } = map;
  const config = FLOOR_CONFIG[selectedFloor] || FLOOR_CONFIG[1];

  // When selectedDeviceId is null, all labels are visible.
  // When a device is selected, ONLY that device's label is visible.
  const hasSelection = selectedDeviceId !== null;

  const visibleDevices = useMemo(() => {
    return map.devices.filter((dev) => dev.floor === selectedFloor || map.floor === selectedFloor);
  }, [map.devices, map.floor, selectedFloor]);

  return (
    <Canvas
      className="floor1-map__canvas"
      camera={{ position: [0, 22, 20], fov: 45, near: 0.1, far: 200 }}
      shadows="percentage"
      onPointerMissed={() => onSelect(-1)}
    >
      <color attach="background" args={["#081329"]} />
      <fog attach="fog" args={["#081329", 40, 120]} />

      <ambientLight intensity={0.75} />
      <directionalLight position={[10, 24, 6]} intensity={1.4} castShadow shadow-mapSize={[1024, 1024]} />
      <directionalLight position={[-8, 12, -10]} intensity={0.4} color="#60a5fa" />

      <group>
        {/* Floor plane */}
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, 0]} receiveShadow>
          <planeGeometry args={[geometry.width, geometry.height]} />
          <meshStandardMaterial color="#0f1f3f" roughness={0.92} metalness={0.05} />
        </mesh>

        {/* Center aisle separation hint */}
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.02, 0]} receiveShadow>
          <planeGeometry args={[geometry.separation_meters, geometry.height]} />
          <meshStandardMaterial color="#122448" roughness={0.95} />
        </mesh>

        {/* Floor 0 open level subtle perimeter boundary */}
        {selectedFloor === 0 && (
          <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.01, 0]}>
            <planeGeometry args={[geometry.width - 0.4, geometry.height - 0.4]} />
            <meshBasicMaterial color="#1e293b" wireframe transparent opacity={0.35} />
          </mesh>
        )}

        {/* Formation Rooms (Floor 1 and Floor 2) */}
        {geometry.rooms &&
          geometry.rooms.map((room) => {
            const [rx] = toScene(geometry, room.x, room.y);
            const posX = rx + room.width / 2;
            const posZ = geometry.height / 2 - room.y - room.height / 2;
            return (
              <group key={room.id}>
                <mesh
                  position={[posX, ROOM_HEIGHT / 2, posZ]}
                  receiveShadow
                  castShadow
                >
                  <boxGeometry args={[room.width, ROOM_HEIGHT, room.height]} />
                  <meshStandardMaterial color="#2563eb" roughness={0.55} transparent opacity={0.8} />
                </mesh>
                <Html position={[posX, ROOM_HEIGHT + 0.3, posZ]} center style={{ pointerEvents: "none" }}>
                  <div className="floor1-map__room-badge">
                    {room.label || (room.id === "formation-room-1" ? "Formation Room 1" : "Formation Room 2")}
                  </div>
                </Html>
              </group>
            );
          })}

        {/* Stairs (Floor 1 and Floor 2) */}
        {geometry.stairs && (() => {
          const [sx] = toScene(geometry, geometry.stairs.x, geometry.stairs.y);
          const posX = sx + geometry.stairs.width / 2;
          const posZ = geometry.height / 2 - geometry.stairs.y - geometry.stairs.height / 2;
          return (
            <group key={geometry.stairs.id}>
              <mesh
                position={[posX, ROOM_HEIGHT / 2, posZ]}
                receiveShadow
                castShadow
              >
                <boxGeometry args={[geometry.stairs.width, ROOM_HEIGHT, geometry.stairs.height]} />
                <meshStandardMaterial color="#f59e0b" roughness={0.6} transparent opacity={0.75} />
              </mesh>
              <Html position={[posX, ROOM_HEIGHT + 0.25, posZ]} center style={{ pointerEvents: "none" }}>
                <div className="floor1-map__stairs-badge">Stairs</div>
              </Html>
            </group>
          );
        })()}

        {/* Tables (Floor 1 only) */}
        {geometry.tables &&
          geometry.tables.map((table) => {
            const [tx] = toScene(geometry, table.x, table.y);
            return (
              <mesh
                key={table.id}
                position={[
                  tx + table.width / 2,
                  TABLE_HEIGHT / 2,
                  geometry.height / 2 - table.y - table.height / 2,
                ]}
                receiveShadow
                castShadow
              >
                <boxGeometry args={[table.width, TABLE_HEIGHT, table.height]} />
                <meshStandardMaterial color="#33466e" roughness={0.45} metalness={0.2} />
              </mesh>
            );
          })}

        {/* Reference PCs (Floor 1 only) */}
        {config.hasReferenceClients &&
          map.references &&
          map.references.map((reference) => (
            <ReferenceMarker key={reference.client_id} reference={reference} geometry={geometry} />
          ))}

        {/* Visible Devices for this floor */}
        {visibleDevices.map((device) => {
          const isSelected = device.device_id === selectedDeviceId;
          const showLabel = !hasSelection || isSelected;
          return (
            <DeviceMarker
              key={device.device_id}
              device={device}
              geometry={geometry}
              selected={isSelected}
              showLabel={showLabel}
              onSelect={onSelect}
            />
          );
        })}
      </group>

      <OrbitControls
        target={[0, 0, 0]}
        enableDamping
        dampingFactor={0.08}
        minDistance={6}
        maxDistance={70}
        maxPolarAngle={Math.PI / 2.05}
      />
    </Canvas>
  );
}

// Backward-compatible Floor1Scene export
export const Floor1Scene = ThreeSpatialScene;
